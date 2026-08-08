from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database.models import WorkspaceMember
from app.repositories.base import BaseRepository


class WorkspaceMemberRepository(BaseRepository[WorkspaceMember]):
    model = WorkspaceMember

    async def list_for_workspace(
        self, workspace_id: uuid.UUID
    ) -> list[WorkspaceMember]:
        query = (
            select(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.role.asc(), WorkspaceMember.created_at.asc())
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_by_workspace_and_user(
        self, workspace_id: uuid.UUID, user_identity: str
    ) -> WorkspaceMember | None:
        query = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_identity == user_identity,
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_owned_by_id(
        self, workspace_id: uuid.UUID, member_id: uuid.UUID
    ) -> WorkspaceMember | None:
        """A member row scoped to a specific workspace (path-param safety —
        never trust member_id alone without confirming it belongs to the
        workspace_id also present in the URL)."""
        query = select(WorkspaceMember).where(
            WorkspaceMember.id == member_id,
            WorkspaceMember.workspace_id == workspace_id,
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def list_workspace_ids_for_member(self, user_identity: str) -> list[uuid.UUID]:
        query = select(WorkspaceMember.workspace_id).where(
            WorkspaceMember.user_identity == user_identity
        )
        result = await self._session.execute(query)
        return [row[0] for row in result.all()]
