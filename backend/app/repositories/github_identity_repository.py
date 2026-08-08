"""Persistence operations for GithubIdentity entities."""

from __future__ import annotations

from sqlalchemy import select

from app.database.models import GithubIdentity
from app.repositories.base import BaseRepository


class GithubIdentityRepository(BaseRepository[GithubIdentity]):
    model = GithubIdentity

    async def get_by_owner(self, owner_identity: str) -> GithubIdentity | None:
        query = select(GithubIdentity).where(
            GithubIdentity.owner_identity == owner_identity
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def delete_by_owner(self, owner_identity: str) -> bool:
        entity = await self.get_by_owner(owner_identity)
        if entity is None:
            return False
        await self.delete(entity)
        return True
