from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database.models import Workspace
from app.repositories.base import BaseRepository


class WorkspaceRepository(BaseRepository[Workspace]):
    model = Workspace

    async def list_for_owner(self, owner_identity: str) -> list[Workspace]:
        query = (
            select(Workspace)
            .where(Workspace.owner_identity == owner_identity)
            .order_by(Workspace.is_default.desc(), Workspace.name.asc())
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_by_owner_and_name(
        self, owner_identity: str, name: str
    ) -> Workspace | None:
        query = select(Workspace).where(
            Workspace.owner_identity == owner_identity, Workspace.name == name
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_default_for_owner(self, owner_identity: str) -> Workspace | None:
        query = select(Workspace).where(
            Workspace.owner_identity == owner_identity, Workspace.is_default.is_(True)
        )
        result = await self._session.execute(query)
        return result.scalars().first()

    async def get_owned(
        self, workspace_id: uuid.UUID, owner_identity: str
    ) -> Workspace | None:
        query = select(Workspace).where(
            Workspace.id == workspace_id, Workspace.owner_identity == owner_identity
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()
