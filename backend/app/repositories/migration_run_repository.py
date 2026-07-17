from __future__ import annotations

import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import defer, selectinload

from app.core.exceptions import NotFoundError
from app.database.models import MigrationRun, MigrationRunStatus
from app.repositories.base import BaseRepository


class MigrationRunRepository(BaseRepository[MigrationRun]):
    """Persistence operations for MigrationRun entities."""

    model = MigrationRun

    def _base_query(
        self,
        *,
        load_children: bool = False,
        include_schema_snapshot: bool = True,
    ) -> Select[tuple[MigrationRun]]:
        query = select(MigrationRun)
        if not include_schema_snapshot:
            query = query.options(defer(MigrationRun.schema_snapshot))
        if load_children:
            query = query.options(
                selectinload(MigrationRun.prediction),
                selectinload(MigrationRun.execution_result),
                selectinload(MigrationRun.learned_outcome),
                selectinload(MigrationRun.shadow_cluster),
            )
        return query

    async def create(self, entity: MigrationRun) -> MigrationRun:
        return await super().create(entity)

    async def get_by_id(
        self,
        entity_id: uuid.UUID,
        *,
        load_children: bool = False,
    ) -> MigrationRun | None:
        if not load_children:
            return await super().get_by_id(entity_id)

        query = self._base_query(load_children=True).where(MigrationRun.id == entity_id)
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_id_or_raise(
        self,
        entity_id: uuid.UUID,
        *,
        load_children: bool = False,
    ) -> MigrationRun:
        entity = await self.get_by_id(entity_id, load_children=load_children)
        if entity is None:
            raise NotFoundError(f"MigrationRun not found: {entity_id}")
        return entity

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: MigrationRunStatus | None = None,
        load_children: bool = False,
    ) -> list[MigrationRun]:
        query = self._base_query(
            load_children=load_children,
            include_schema_snapshot=False,
        ).order_by(MigrationRun.created_at.desc())
        if status is not None:
            query = query.where(MigrationRun.status == status)
        return await super().list(offset=offset, limit=limit, statement=query)

    async def count(
        self,
        *,
        status: MigrationRunStatus | None = None,
    ) -> int:
        query = select(MigrationRun)
        if status is not None:
            query = query.where(MigrationRun.status == status)
        return await super().count(query)

    async def update(self, entity: MigrationRun) -> MigrationRun:
        return await super().update(entity)

    async def delete(self, entity: MigrationRun) -> None:
        await super().delete(entity)

    async def delete_by_id(self, entity_id: uuid.UUID) -> None:
        await super().delete_by_id(entity_id)
