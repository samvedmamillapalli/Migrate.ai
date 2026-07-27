from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.core.logging import get_logger
from app.database.models import ShadowCluster, ShadowClusterStatus
from app.database.retry import with_txn_retry
from app.repositories.shadow_cluster_repository import ShadowClusterRepository

logger = get_logger(__name__)

# The cluster-resource lifecycle. ``status`` tracks the shadow *resource*, not
# whether the migration under test passed (that lives in the LifecycleReport /
# ExecutionResult). Teardown may begin from any active stage; DESTROYED means
# the resource was cleaned up, FAILED means teardown itself could not complete
# and the cluster may be leaked (the sweeper is the backstop).
ALLOWED_TRANSITIONS: dict[ShadowClusterStatus, frozenset[ShadowClusterStatus]] = {
    ShadowClusterStatus.PROVISIONING: frozenset(
        {ShadowClusterStatus.READY, ShadowClusterStatus.DESTROYING}
    ),
    ShadowClusterStatus.READY: frozenset(
        {ShadowClusterStatus.SEEDING, ShadowClusterStatus.DESTROYING}
    ),
    ShadowClusterStatus.SEEDING: frozenset(
        {ShadowClusterStatus.MIGRATING, ShadowClusterStatus.DESTROYING}
    ),
    ShadowClusterStatus.MIGRATING: frozenset({ShadowClusterStatus.DESTROYING}),
    ShadowClusterStatus.DESTROYING: frozenset(
        {ShadowClusterStatus.DESTROYED, ShadowClusterStatus.FAILED}
    ),
    ShadowClusterStatus.DESTROYED: frozenset(),
    ShadowClusterStatus.FAILED: frozenset(),
}


class ShadowClusterService:
    """Business logic + persistence for ShadowCluster lifecycle state.

    Owns commit/rollback and status-transition validation, consistent with the
    Phase 4 service pattern.
    """

    def __init__(
        self,
        repository: ShadowClusterRepository,
        session: AsyncSession,
    ) -> None:
        self._repository = repository
        self._session = session

    async def try_admit(
        self,
        *,
        run_id: uuid.UUID,
        region: str,
        provider: str,
        scale_tier: str,
        max_concurrent: int,
        max_lifetime_minutes: int,
    ) -> ShadowCluster | None:
        """Atomically admit a run under the concurrency cap.

        Counts active clusters and inserts the PROVISIONING row in a single
        serializable transaction. Returns the new row if a slot was free, or
        ``None`` if the cap is currently reached. CockroachDB's serializable
        isolation plus the 40001 retry make the count-then-insert race-safe
        across processes.
        """
        existing = await self._repository.get_by_migration_run_id(run_id)
        if existing is not None:
            # One shadow per run (unique constraint). Reuse the row.
            return existing

        async def _commit() -> ShadowCluster | None:
            active = await self._repository.count_active()
            if active >= max_concurrent:
                await self._session.rollback()
                return None
            now = datetime.now(UTC)
            cluster = ShadowCluster(
                migration_run_id=run_id,
                provider=provider,
                region=region,
                status=ShadowClusterStatus.PROVISIONING,
                scale_tier=scale_tier,
                expires_at=now + timedelta(minutes=max_lifetime_minutes),
            )
            created = await self._repository.create(cluster)
            await self._session.commit()
            await self._session.refresh(created)
            return created

        created = await with_txn_retry(_commit, on_retry=self._session.rollback)
        if created is not None:
            logger.info(
                "Admitted shadow run",
                extra={
                    "run_id": str(run_id),
                    "shadow_id": str(created.id),
                    "scale_tier": scale_tier,
                },
            )
        return created

    async def set_identity(
        self,
        shadow_id: uuid.UUID,
        *,
        cluster_id: str,
        cluster_name: str,
    ) -> ShadowCluster:
        async def _commit() -> ShadowCluster:
            entity = await self._repository.get_by_id_or_raise(shadow_id)
            entity.cluster_id = cluster_id
            entity.cluster_name = cluster_name
            updated = await self._repository.update(entity)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated

        return await with_txn_retry(_commit, on_retry=self._session.rollback)

    async def transition(
        self,
        shadow_id: uuid.UUID,
        new_status: ShadowClusterStatus,
    ) -> ShadowCluster:
        async def _commit() -> tuple[ShadowCluster, ShadowClusterStatus]:
            entity = await self._repository.get_by_id_or_raise(shadow_id)
            previous = entity.status
            if previous == new_status:
                return entity, previous
            self._validate_transition(previous, new_status)
            entity.status = new_status
            if new_status == ShadowClusterStatus.DESTROYED:
                entity.destroyed_at = datetime.now(UTC)
            updated = await self._repository.update(entity)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated, previous

        updated, previous = await with_txn_retry(
            _commit, on_retry=self._session.rollback
        )
        if previous != updated.status:
            logger.info(
                "Shadow cluster status transition",
                extra={
                    "shadow_id": str(shadow_id),
                    "from_status": previous.value,
                    "to_status": updated.status.value,
                },
            )
        return updated

    async def record_timings(
        self,
        shadow_id: uuid.UUID,
        timings: dict[str, Any],
    ) -> ShadowCluster:
        async def _commit() -> ShadowCluster:
            entity = await self._repository.get_by_id_or_raise(shadow_id)
            entity.stage_timings = timings
            updated = await self._repository.update(entity)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated

        return await with_txn_retry(_commit, on_retry=self._session.rollback)

    async def merge_timings(
        self,
        shadow_id: uuid.UUID,
        **partial: Any,
    ) -> ShadowCluster:
        """Merge stage timing / artifact keys without wiping earlier measurements."""
        entity = await self._repository.get_by_id_or_raise(shadow_id)
        merged = dict(entity.stage_timings or {})
        for key, value in partial.items():
            if value is not None:
                merged[key] = value
        return await self.record_timings(shadow_id, merged)

    async def set_error(
        self,
        shadow_id: uuid.UUID,
        message: str,
    ) -> ShadowCluster:
        truncated = message[:2000]

        async def _commit() -> ShadowCluster:
            entity = await self._repository.get_by_id_or_raise(shadow_id)
            entity.error_message = truncated
            updated = await self._repository.update(entity)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated

        return await with_txn_retry(_commit, on_retry=self._session.rollback)

    async def count_active(self) -> int:
        return await self._repository.count_active()

    async def list_expired_active(self, now: datetime) -> list[ShadowCluster]:
        return await self._repository.list_expired_active(now)

    async def get(self, shadow_id: uuid.UUID) -> ShadowCluster:
        return await self._repository.get_by_id_or_raise(shadow_id)

    async def get_by_run(self, run_id: uuid.UUID) -> ShadowCluster | None:
        return await self._repository.get_by_migration_run_id(run_id)

    @staticmethod
    def _validate_transition(
        current: ShadowClusterStatus,
        new_status: ShadowClusterStatus,
    ) -> None:
        allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
        if new_status not in allowed:
            raise ConflictError(
                f"Invalid shadow cluster transition: "
                f"{current.value} -> {new_status.value}"
            )


__all__ = ["ALLOWED_TRANSITIONS", "ShadowClusterService"]
