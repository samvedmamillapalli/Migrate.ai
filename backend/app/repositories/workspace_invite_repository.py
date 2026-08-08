from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database.models import WorkspaceInvite
from app.repositories.base import BaseRepository


class WorkspaceInviteRepository(BaseRepository[WorkspaceInvite]):
    model = WorkspaceInvite

    async def list_for_workspace(self, workspace_id: uuid.UUID) -> list[WorkspaceInvite]:
        query = (
            select(WorkspaceInvite)
            .where(WorkspaceInvite.workspace_id == workspace_id)
            .order_by(WorkspaceInvite.created_at.desc())
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_owned_by_id(
        self, workspace_id: uuid.UUID, invite_id: uuid.UUID
    ) -> WorkspaceInvite | None:
        query = select(WorkspaceInvite).where(
            WorkspaceInvite.id == invite_id,
            WorkspaceInvite.workspace_id == workspace_id,
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_token(self, token: str) -> WorkspaceInvite | None:
        query = select(WorkspaceInvite).where(WorkspaceInvite.token == token)
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_pending_link_invite(
        self, workspace_id: uuid.UUID
    ) -> WorkspaceInvite | None:
        """Most recent pending method="link" invite for this workspace, if
        any — lets the invite dialog reuse one shareable link instead of
        minting a fresh one every time it opens."""
        from app.database.models import WorkspaceInviteMethod, WorkspaceInviteStatus

        query = (
            select(WorkspaceInvite)
            .where(
                WorkspaceInvite.workspace_id == workspace_id,
                WorkspaceInvite.method == WorkspaceInviteMethod.LINK,
                WorkspaceInvite.status == WorkspaceInviteStatus.PENDING,
            )
            .order_by(WorkspaceInvite.created_at.desc())
        )
        result = await self._session.execute(query)
        return result.scalars().first()
