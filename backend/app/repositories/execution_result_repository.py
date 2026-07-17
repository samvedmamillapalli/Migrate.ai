from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database.models import ExecutionResult
from app.repositories.base import BaseRepository


class ExecutionResultRepository(BaseRepository[ExecutionResult]):
    """Persistence for ExecutionResult (shadow migration execution outcomes)."""

    model = ExecutionResult

    async def get_by_migration_run_id(
        self,
        migration_run_id: uuid.UUID,
    ) -> ExecutionResult | None:
        query = select(ExecutionResult).where(
            ExecutionResult.migration_run_id == migration_run_id
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()
