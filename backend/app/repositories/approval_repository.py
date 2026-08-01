from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database.models import Approval
from app.repositories.base import BaseRepository


class ApprovalRepository(BaseRepository[Approval]):
    model = Approval

    async def get_by_migration_run_id(
        self,
        migration_run_id: uuid.UUID,
    ) -> Approval | None:
        result = await self._session.execute(
            select(Approval).where(Approval.migration_run_id == migration_run_id)
        )
        return result.scalar_one_or_none()
