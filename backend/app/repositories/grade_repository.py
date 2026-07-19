from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database.models import Grade
from app.repositories.base import BaseRepository


class GradeRepository(BaseRepository[Grade]):
    model = Grade

    async def get_by_migration_run_id(self, run_id: uuid.UUID) -> Grade | None:
        result = await self._session.execute(
            select(Grade).where(Grade.migration_run_id == run_id)
        )
        return result.scalar_one_or_none()

    async def create(self, entity: Grade) -> Grade:
        return await super().create(entity)

    async def update(self, entity: Grade) -> Grade:
        return await super().update(entity)
