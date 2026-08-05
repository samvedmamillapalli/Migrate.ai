from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select

from app.database.models import (
    ACTIVE_SHADOW_STATUSES,
    MigrationRun,
    ShadowCluster,
    ShadowClusterStatus,
)
from app.repositories.base import BaseRepository


class ShadowClusterRepository(BaseRepository[ShadowCluster]):
    """Persistence operations for ShadowCluster entities."""

    model = ShadowCluster

    async def get_by_migration_run_id(
        self,
        migration_run_id: uuid.UUID,
    ) -> ShadowCluster | None:
        query = select(ShadowCluster).where(
            ShadowCluster.migration_run_id == migration_run_id
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def count_active(self) -> int:
        """Count clusters that may still hold cloud resources.

        Used by the concurrency cap. Runs inside the caller's (serializable)
        transaction so the count-then-insert admission decision is race-safe.
        """
        query = (
            select(func.count())
            .select_from(ShadowCluster)
            .where(ShadowCluster.status.in_(ACTIVE_SHADOW_STATUSES))
        )
        result = await self._session.execute(query)
        return int(result.scalar_one())

    async def count_active_for_owner(self, owner_identity: str) -> int:
        """Same predicate as ``count_active``, narrowed to one owner's runs.

        ``ShadowCluster`` carries no owner column itself, so this joins to
        ``MigrationRun`` to find out who owns each cluster. Runs inside the
        caller's transaction, same as ``count_active``.
        """
        query = (
            select(func.count())
            .select_from(ShadowCluster)
            .join(MigrationRun, MigrationRun.id == ShadowCluster.migration_run_id)
            .where(
                ShadowCluster.status.in_(ACTIVE_SHADOW_STATUSES),
                MigrationRun.owner_identity == owner_identity,
            )
        )
        result = await self._session.execute(query)
        return int(result.scalar_one())

    async def list_active(self) -> list[ShadowCluster]:
        query = select(ShadowCluster).where(
            ShadowCluster.status.in_(ACTIVE_SHADOW_STATUSES)
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_expired_active(self, now: datetime) -> list[ShadowCluster]:
        """Active clusters whose max-lifetime deadline has passed (sweeper)."""
        query = select(ShadowCluster).where(
            ShadowCluster.status.in_(ACTIVE_SHADOW_STATUSES),
            ShadowCluster.expires_at.is_not(None),
            ShadowCluster.expires_at < now,
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def get_by_cluster_name(self, cluster_name: str) -> ShadowCluster | None:
        query = select(ShadowCluster).where(
            ShadowCluster.cluster_name == cluster_name
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()
