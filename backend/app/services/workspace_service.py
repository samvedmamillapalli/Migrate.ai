"""Business logic for workspaces — docs/FUTURE_WORKSPACES_PLAN.md.

Framework-free by design: connection-secret storage/loading and the
lightweight connectivity check both need a ``Request`` (for the dev-only
in-memory secret fallback) or do a real network call, so that orchestration
lives at the route layer (``app/api/routes/workspaces.py``), matching how
``MigrationRunService`` also stays free of ``Request``/HTTP concerns. This
service only ever receives an already-resolved ``connection_secret_arn``.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError, ValidationError
from app.core.logging import get_logger
from app.database.models import Workspace, WorkspaceMember, WorkspaceMemberRole
from app.database.retry import with_txn_retry
from app.repositories.workspace_member_repository import WorkspaceMemberRepository
from app.repositories.workspace_repository import WorkspaceRepository

logger = get_logger(__name__)

_MAX_NAME_LENGTH = 256


def _clean_name(name: str) -> str:
    clean = (name or "").strip()
    if not clean:
        raise ValidationError("name is required")
    if len(clean) > _MAX_NAME_LENGTH:
        raise ValidationError(f"name must be at most {_MAX_NAME_LENGTH} characters")
    return clean


def _clean_owner(owner_identity: str) -> str:
    identity = (owner_identity or "").strip()
    if not identity:
        raise ValidationError("owner_identity is required")
    return identity


_DEFAULT_GITHUB_MIGRATION_GLOB = "backend/alembic/versions/*.py"


class WorkspaceService:
    def __init__(
        self,
        repository: WorkspaceRepository,
        session: AsyncSession,
        member_repository: WorkspaceMemberRepository | None = None,
    ) -> None:
        self._repository = repository
        self._session = session
        # Optional for backward compatibility with existing call sites/tests
        # that construct this service without membership concerns; lazily
        # built from the same session if not supplied.
        self._members = member_repository or WorkspaceMemberRepository(session)

    async def create_workspace(
        self,
        *,
        owner_identity: str,
        name: str,
        connection_secret_arn: str | None = None,
        connection_label: str | None = None,
        workspace_id: uuid.UUID | None = None,
        is_default: bool = False,
        github_repo_full_name: str | None = None,
        github_migration_glob: str | None = None,
    ) -> Workspace:
        identity = _clean_owner(owner_identity)
        clean_name = _clean_name(name)

        existing = await self._repository.get_by_owner_and_name(identity, clean_name)
        if existing is not None:
            raise ConflictError(
                f"Workspace already exists for this owner: {clean_name!r}"
            )
        repo_full_name = (github_repo_full_name or "").strip() or None
        if repo_full_name is not None:
            await self._assert_repo_available(repo_full_name, workspace_id=None)

        async def _commit() -> Workspace:
            entity = Workspace(
                id=workspace_id or uuid.uuid4(),
                owner_identity=identity,
                name=clean_name,
                connection_secret_arn=(connection_secret_arn or "").strip() or None,
                connection_label=(connection_label or "").strip() or None,
                is_default=is_default,
                github_repo_full_name=repo_full_name,
                github_migration_glob=(
                    (github_migration_glob or "").strip()
                    or _DEFAULT_GITHUB_MIGRATION_GLOB
                ),
            )
            created = await self._repository.create(entity)
            # The creator is implicitly the 'owner' member — every existing
            # workspace was backfilled the same way (see the workspace
            # invites migration), so the member list is never empty.
            await self._members.create(
                WorkspaceMember(
                    workspace_id=created.id,
                    user_identity=identity,
                    role=WorkspaceMemberRole.OWNER,
                )
            )
            await self._session.commit()
            await self._session.refresh(created)
            return created

        created = await with_txn_retry(_commit, on_retry=self._session.rollback)
        logger.info(
            "Created workspace",
            extra={
                "workspace_id": str(created.id),
                "owner_identity": identity,
                "has_connection": bool(created.connection_secret_arn),
            },
        )
        return created

    async def list_workspaces(self, owner_identity: str) -> list[Workspace]:
        identity = _clean_owner(owner_identity)
        return await self._repository.list_for_owner(identity)

    async def list_accessible_workspaces(self, user_identity: str) -> list[Workspace]:
        """Owned + member workspaces — visibility only, see
        app/database/models/workspace_member.py for the scope boundary."""
        identity = _clean_owner(user_identity)
        return await self._repository.list_accessible(identity)

    async def get_owned_workspace(
        self, workspace_id: uuid.UUID, owner_identity: str
    ) -> Workspace:
        identity = _clean_owner(owner_identity)
        workspace = await self._repository.get_owned(workspace_id, identity)
        if workspace is None:
            raise NotFoundError(f"Workspace not found: {workspace_id}")
        return workspace

    async def get_accessible_workspace(
        self, workspace_id: uuid.UUID, user_identity: str
    ) -> Workspace:
        """Owner OR member — read visibility. Settings mutations
        (update/delete) stay on ``get_owned_workspace``, owner-only."""
        identity = _clean_owner(user_identity)
        workspace = await self._repository.get_accessible(workspace_id, identity)
        if workspace is None:
            raise NotFoundError(f"Workspace not found: {workspace_id}")
        return workspace

    async def get_workspace_by_id(self, workspace_id: uuid.UUID) -> Workspace:
        """No ownership check at all — for the invite preview/accept path,
        where a valid token (not owner_identity) is the credential. Never
        call this from a route without a token or equivalent capability
        check already having happened."""
        workspace = await self._repository.get_by_id(workspace_id)
        if workspace is None:
            raise NotFoundError(f"Workspace not found: {workspace_id}")
        return workspace

    async def list_members(
        self, workspace_id: uuid.UUID, user_identity: str
    ) -> list[WorkspaceMember]:
        # Any accessible (owner or member) identity can see the roster.
        await self.get_accessible_workspace(workspace_id, user_identity)
        return await self._members.list_for_workspace(workspace_id)

    async def add_member(
        self,
        workspace_id: uuid.UUID,
        user_identity: str,
        *,
        role: WorkspaceMemberRole = WorkspaceMemberRole.MEMBER,
    ) -> WorkspaceMember:
        """Idempotent — accepting an invite twice (e.g. a double-click, or
        a token reused after already joining) must not create a duplicate
        row or raise; it just confirms membership."""
        existing = await self._members.get_by_workspace_and_user(
            workspace_id, user_identity
        )
        if existing is not None:
            return existing

        async def _commit() -> WorkspaceMember:
            created = await self._members.create(
                WorkspaceMember(
                    workspace_id=workspace_id,
                    user_identity=user_identity,
                    role=role,
                )
            )
            await self._session.commit()
            await self._session.refresh(created)
            return created

        return await with_txn_retry(_commit, on_retry=self._session.rollback)

    async def remove_member(
        self, workspace_id: uuid.UUID, member_id: uuid.UUID, owner_identity: str
    ) -> None:
        """Owner-only (matches invite management), and the workspace's
        'owner' member row can never be removed through this path — that
        would leave a workspace with no owner. Deleting the workspace
        itself is the only way to remove that row (cascades)."""
        await self.get_owned_workspace(workspace_id, owner_identity)
        member = await self._members.get_owned_by_id(workspace_id, member_id)
        if member is None:
            raise NotFoundError(f"Member not found: {member_id}")
        if member.role == WorkspaceMemberRole.OWNER:
            raise UnauthorizedError("Cannot remove the workspace owner")

        async def _commit() -> None:
            await self._members.delete(member)
            await self._session.commit()

        await with_txn_retry(_commit, on_retry=self._session.rollback)
        logger.info(
            "Removed workspace member",
            extra={"workspace_id": str(workspace_id), "member_id": str(member_id)},
        )

    async def _assert_repo_available(
        self, repo_full_name: str, *, workspace_id: uuid.UUID | None
    ) -> None:
        """docs/FUTURE_GITHUB_INTEGRATION_PLAN.md: one repo maps to at most
        one workspace, globally (not just per-owner) — a repo already linked
        elsewhere must be rejected here, before it ever reaches the
        database's partial unique index."""
        existing = await self._repository.get_by_github_repo_full_name(repo_full_name)
        if existing is not None and existing.id != workspace_id:
            raise ConflictError(
                f"Repo {repo_full_name!r} is already linked to another workspace"
            )

    async def update_workspace(
        self,
        workspace_id: uuid.UUID,
        owner_identity: str,
        *,
        name: str | None = None,
        connection_secret_arn: str | None = None,
        connection_label: str | None = None,
        clear_connection: bool = False,
        github_repo_full_name: str | None = None,
        clear_github_repo: bool = False,
        github_migration_glob: str | None = None,
    ) -> Workspace:
        """``clear_connection=True`` explicitly detaches the stored
        connection (distinct from leaving ``connection_secret_arn=None``,
        which means "don't touch the existing value"). ``clear_github_repo``
        follows the same convention for unlinking a repo."""
        workspace = await self.get_owned_workspace(workspace_id, owner_identity)

        if name is not None:
            clean_name = _clean_name(name)
            if clean_name != workspace.name:
                collision = await self._repository.get_by_owner_and_name(
                    workspace.owner_identity, clean_name
                )
                if collision is not None and collision.id != workspace.id:
                    raise ConflictError(
                        f"Workspace already exists for this owner: {clean_name!r}"
                    )
                workspace.name = clean_name

        if clear_connection:
            workspace.connection_secret_arn = None
            workspace.connection_label = None
        elif connection_secret_arn is not None:
            workspace.connection_secret_arn = connection_secret_arn.strip() or None
            workspace.connection_label = (connection_label or "").strip() or None

        if clear_github_repo:
            workspace.github_repo_full_name = None
        elif github_repo_full_name is not None:
            repo_full_name = github_repo_full_name.strip() or None
            if repo_full_name is not None:
                await self._assert_repo_available(
                    repo_full_name, workspace_id=workspace.id
                )
            workspace.github_repo_full_name = repo_full_name

        if github_migration_glob is not None:
            workspace.github_migration_glob = (
                github_migration_glob.strip() or _DEFAULT_GITHUB_MIGRATION_GLOB
            )

        async def _commit() -> Workspace:
            updated = await self._repository.update(workspace)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated

        return await with_txn_retry(_commit, on_retry=self._session.rollback)

    async def delete_workspace(self, workspace_id: uuid.UUID, owner_identity: str) -> None:
        """Deletes the workspace row only. ``migration_runs.workspace_id`` has
        ``ondelete="SET NULL"`` at the database level (see the workspaces
        migration) — CockroachDB itself orphans referencing runs back to "no
        workspace" rather than deleting run history. No application-level
        cascade logic needed here."""
        workspace = await self.get_owned_workspace(workspace_id, owner_identity)

        async def _commit() -> None:
            await self._repository.delete(workspace)
            await self._session.commit()

        await with_txn_retry(_commit, on_retry=self._session.rollback)
        logger.info(
            "Deleted workspace",
            extra={"workspace_id": str(workspace_id), "owner_identity": owner_identity},
        )
