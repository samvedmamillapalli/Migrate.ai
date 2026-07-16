from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.database.base import Base


class BaseRepository[ModelT: Base]:
    """Generic async repository for SQLAlchemy models.

    Encapsulates persistence only. Callers own commit/rollback.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: ModelT) -> ModelT:
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def get_by_id(self, entity_id: object) -> ModelT | None:
        return await self._session.get(self.model, entity_id)

    async def get_by_id_or_raise(self, entity_id: object) -> ModelT:
        entity = await self.get_by_id(entity_id)
        if entity is None:
            raise NotFoundError(f"{self.model.__name__} not found: {entity_id}")
        return entity

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        statement: Select[tuple[ModelT]] | None = None,
    ) -> list[ModelT]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1:
            raise ValueError("limit must be >= 1")

        query = statement if statement is not None else select(self.model)
        query = query.offset(offset).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count(self, statement: Select[tuple[ModelT]] | None = None) -> int:
        if statement is None:
            count_stmt = select(func.count()).select_from(self.model)
        else:
            subquery = statement.order_by(None).subquery()
            count_stmt = select(func.count()).select_from(subquery)
        result = await self._session.execute(count_stmt)
        return int(result.scalar_one())

    async def update(self, entity: ModelT) -> ModelT:
        merged = await self._session.merge(entity)
        await self._session.flush()
        await self._session.refresh(merged)
        return merged

    async def delete(self, entity: ModelT) -> None:
        await self._session.delete(entity)
        await self._session.flush()

    async def delete_by_id(self, entity_id: object) -> None:
        entity = await self.get_by_id_or_raise(entity_id)
        await self.delete(entity)
