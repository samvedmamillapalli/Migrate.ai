from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database.models import Grade, MigrationRun
from app.repositories.base import BaseRepository


class GradeRepository(BaseRepository[Grade]):
    model = Grade

    async def get_by_migration_run_id(self, run_id: uuid.UUID) -> Grade | None:
        result = await self._session.execute(
            select(Grade).where(Grade.migration_run_id == run_id)
        )
        return result.scalar_one_or_none()

    async def get_most_recent_for_owner(
        self, owner_identity: str
    ) -> tuple[MigrationRun, Grade] | None:
        """Newest graded run for an owner — used to build a real, live
        cross-customer sharing preview (docs/cross_customer.md §6) rather
        than an abstract example."""
        result = await self._session.execute(
            select(MigrationRun, Grade)
            .join(Grade, Grade.migration_run_id == MigrationRun.id)
            .where(MigrationRun.owner_identity == owner_identity)
            .order_by(Grade.created_at.desc())
            .limit(1)
        )
        row = result.first()
        return (row[0], row[1]) if row else None

    async def create(self, entity: Grade) -> Grade:
        return await super().create(entity)

    async def update(self, entity: Grade) -> Grade:
        return await super().update(entity)
