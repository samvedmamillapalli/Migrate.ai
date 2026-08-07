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

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.database.models import Workspace
from app.database.retry import with_txn_retry
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
    def __init__(self, repository: WorkspaceRepository, session: AsyncSession) -> None:
        self._repository = repository
        self._session = session

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

    async def get_owned_workspace(
        self, workspace_id: uuid.UUID, owner_identity: str
    ) -> Workspace:
        identity = _clean_owner(owner_identity)
        workspace = await self._repository.get_owned(workspace_id, identity)
        if workspace is None:
            raise NotFoundError(f"Workspace not found: {workspace_id}")
        return workspace

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
