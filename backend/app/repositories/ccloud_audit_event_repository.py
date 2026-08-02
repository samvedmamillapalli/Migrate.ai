from __future__ import annotations

import uuid

from sqlalchemy import select

from app.database.models import CCloudAuditEvent
from app.repositories.base import BaseRepository


class CCloudAuditEventRepository(BaseRepository[CCloudAuditEvent]):
    model = CCloudAuditEvent

    async def list_for_run(self, run_id: uuid.UUID) -> list[CCloudAuditEvent]:
        result = await self._session.execute(
            select(CCloudAuditEvent)
            .where(CCloudAuditEvent.migration_run_id == run_id)
            .order_by(CCloudAuditEvent.occurred_at.asc().nulls_last())
        )
        return list(result.scalars().all())

    async def bulk_create(
        self, events: list[CCloudAuditEvent]
    ) -> list[CCloudAuditEvent]:
        if not events:
            return []
        self._session.add_all(events)
        await self._session.flush()
        for event in events:
            await self._session.refresh(event)
        return events
