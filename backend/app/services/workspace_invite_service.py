"""Workspace invites: create/list/revoke (owner-only), public token preview,
and accept (creates the accepting identity's membership row).

Invite management (create/list/revoke) requires the same owner-only access
as workspace settings — ``get_owned_workspace``, not the wider
``get_accessible`` used for read visibility. A member can see who else is
in the workspace but cannot invite or remove people; only the owner can.
This is a scope choice, not a technical limit — widen it later if wanted.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.database.models import (
    Workspace,
    WorkspaceInvite,
    WorkspaceInviteMethod,
    WorkspaceInviteStatus,
    WorkspaceMemberRole,
)
from app.database.retry import with_txn_retry
from app.repositories.workspace_invite_repository import WorkspaceInviteRepository
from app.services.email_service import EmailService
from app.services.workspace_service import WorkspaceService

logger = get_logger(__name__)

_INVITE_TTL_DAYS = 14
_TOKEN_BYTES = 32


def _effective_status(invite: WorkspaceInvite) -> str:
    """Lazily computed — "expired" is never stored, just derived by
    comparing ``expires_at`` to now, so no background job is needed to
    flip a status column. See the model's module docstring."""
    if invite.status == WorkspaceInviteStatus.PENDING and invite.expires_at < datetime.now(
        UTC
    ):
        return "expired"
    return invite.status.value


class WorkspaceInviteService:
    def __init__(
        self,
        *,
        repository: WorkspaceInviteRepository,
        workspace_service: WorkspaceService,
        session: AsyncSession,
        email_service: EmailService | None = None,
    ) -> None:
        self._repository = repository
        self._workspaces = workspace_service
        self._session = session
        self._email = email_service

    async def create_invite(
        self,
        workspace_id: uuid.UUID,
        owner_identity: str,
        *,
        method: WorkspaceInviteMethod,
        email: str | None = None,
        github_username: str | None = None,
    ) -> tuple[WorkspaceInvite, bool | None]:
        """Returns (invite, email_delivered). email_delivered is None for
        every method except EMAIL, where it reports whether SES actually
        accepted the send — the invite row is never rolled back on a
        delivery failure, but the caller needs to know so the UI can stop
        claiming "sent" when nothing went out."""
        workspace = await self._workspaces.get_owned_workspace(
            workspace_id, owner_identity
        )
        if method == WorkspaceInviteMethod.EMAIL and not (email or "").strip():
            raise ValidationError("email is required for method=email")
        if method == WorkspaceInviteMethod.GITHUB and not (
            github_username or ""
        ).strip():
            raise ValidationError("github_username is required for method=github")

        token = secrets.token_urlsafe(_TOKEN_BYTES)
        expires_at = datetime.now(UTC) + timedelta(days=_INVITE_TTL_DAYS)

        async def _commit() -> WorkspaceInvite:
            entity = WorkspaceInvite(
                workspace_id=workspace_id,
                inviter_identity=owner_identity,
                method=method,
                email=(email or "").strip() or None,
                github_username=(github_username or "").strip() or None,
                token=token,
                status=WorkspaceInviteStatus.PENDING,
                expires_at=expires_at,
            )
            created = await self._repository.create(entity)
            await self._session.commit()
            await self._session.refresh(created)
            return created

        created = await with_txn_retry(_commit, on_retry=self._session.rollback)
        logger.info(
            "Created workspace invite",
            extra={
                "workspace_id": str(workspace_id),
                "invite_id": str(created.id),
                "method": method.value,
            },
        )

        email_delivered: bool | None = None
        if method == WorkspaceInviteMethod.EMAIL:
            # Best-effort, same posture as Slack/GitHub notifications
            # elsewhere in this app — a delivery failure must never undo or
            # block the invite record that already exists.
            email_delivered = (
                await self._email.send_workspace_invite(
                    to_email=created.email or "",
                    inviter_identity=owner_identity,
                    workspace_name=workspace.name,
                    token=token,
                )
                if self._email is not None
                else False
            )

        return created, email_delivered

    async def list_invites(
        self, workspace_id: uuid.UUID, owner_identity: str
    ) -> list[WorkspaceInvite]:
        await self._workspaces.get_owned_workspace(workspace_id, owner_identity)
        return await self._repository.list_for_workspace(workspace_id)

    async def revoke_invite(
        self, workspace_id: uuid.UUID, invite_id: uuid.UUID, owner_identity: str
    ) -> WorkspaceInvite:
        await self._workspaces.get_owned_workspace(workspace_id, owner_identity)
        invite = await self._repository.get_owned_by_id(workspace_id, invite_id)
        if invite is None:
            raise NotFoundError(f"Invite not found: {invite_id}")

        invite.status = WorkspaceInviteStatus.REVOKED

        async def _commit() -> WorkspaceInvite:
            updated = await self._repository.update(invite)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated

        return await with_txn_retry(_commit, on_retry=self._session.rollback)

    async def get_preview(self, token: str) -> tuple[WorkspaceInvite, Workspace, str]:
        """Public, token-keyed — no ownership check, the token itself is
        the credential. Returns (invite, workspace, effective_status) so
        the route can build the preview without a second lookup."""
        invite = await self._repository.get_by_token(token)
        if invite is None:
            raise NotFoundError("Invite not found")
        workspace = await self._workspaces.get_workspace_by_id(invite.workspace_id)
        return invite, workspace, _effective_status(invite)

    async def accept_invite(self, token: str, accepting_identity: str) -> Workspace:
        invite = await self._repository.get_by_token(token)
        if invite is None:
            raise NotFoundError("Invite not found")

        status = _effective_status(invite)
        if status != "pending":
            raise ConflictError(f"This invite is {status}, not pending")

        workspace = await self._workspaces.get_workspace_by_id(invite.workspace_id)
        await self._workspaces.add_member(
            invite.workspace_id,
            accepting_identity,
            role=WorkspaceMemberRole.MEMBER,
        )

        invite.status = WorkspaceInviteStatus.ACCEPTED
        invite.accepted_at = datetime.now(UTC)
        invite.accepted_by = accepting_identity

        async def _commit() -> None:
            await self._repository.update(invite)
            await self._session.commit()

        await with_txn_retry(_commit, on_retry=self._session.rollback)
        logger.info(
            "Invite accepted",
            extra={
                "invite_id": str(invite.id),
                "workspace_id": str(invite.workspace_id),
                "accepted_by": accepting_identity,
            },
        )
        return workspace


__all__ = ["WorkspaceInviteService", "_effective_status"]
