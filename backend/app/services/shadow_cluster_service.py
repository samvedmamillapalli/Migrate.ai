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
    ShadowClusterStatus.MIGRATING: frozenset(
        {ShadowClusterStatus.HOLDING, ShadowClusterStatus.DESTROYING}
    ),
    ShadowClusterStatus.HOLDING: frozenset({ShadowClusterStatus.DESTROYING}),
    ShadowClusterStatus.DESTROYING: frozenset(
        {ShadowClusterStatus.DESTROYED, ShadowClusterStatus.FAILED}
    ),
    ShadowClusterStatus.DESTROYED: frozenset(),
    ShadowClusterStatus.FAILED: frozenset(),
}


# Event log is capped so a stuck/looping run can't grow the JSONB column
# unboundedly; enough to replay a full lifecycle (provision..destroyed) with
# room for retries.
_EVENT_LOG_MAX_ENTRIES = 200


def _append_event(
    existing: list[dict[str, Any]] | None,
    *,
    status: str,
    stage_timings: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    log = list(existing or [])
    log.append(
        {
            "at": datetime.now(UTC).isoformat(),
            "status": status,
            "stage_timings": dict(stage_timings or {}),
        }
    )
    return log[-_EVENT_LOG_MAX_ENTRIES:]


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
        owner_identity: str | None = None,
        max_concurrent_per_owner: int | None = None,
    ) -> ShadowCluster | None:
        """Atomically admit a run under the concurrency cap(s).

        Counts active clusters and inserts the PROVISIONING row in a single
        serializable transaction. Returns the new row if a slot was free, or
        ``None`` if a cap is currently reached. CockroachDB's serializable
        isolation plus the 40001 retry make the count-then-insert race-safe
        across processes.

        ``owner_identity``/``max_concurrent_per_owner`` are optional and
        additive: when either is unset, only the global cap applies — this is
        the default, unchanged behavior. When both are given, the run must
        also be under that owner's own count, checked in the same
        transaction as the global count so admission is still a single
        atomic decision.
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
            if owner_identity and max_concurrent_per_owner is not None:
                active_for_owner = await self._repository.count_active_for_owner(
                    owner_identity
                )
                if active_for_owner >= max_concurrent_per_owner:
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
            entity.event_log = _append_event(
                entity.event_log, status=new_status.value, stage_timings=entity.stage_timings
            )
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
            entity.event_log = _append_event(
                entity.event_log, status=entity.status.value, stage_timings=timings
            )
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

    async def set_schema_snapshot(
        self,
        shadow_id: uuid.UUID,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        row_sample_before: dict[str, Any] | None = None,
        row_sample_after: dict[str, Any] | None = None,
    ) -> ShadowCluster:
        """Best-effort structural snapshot + real row sample for the before/after
        panels. Each field is only written when provided, so a caller that only
        has the schema (no row samples this run) doesn't clobber a value it
        doesn't have."""

        async def _commit() -> ShadowCluster:
            entity = await self._repository.get_by_id_or_raise(shadow_id)
            if before is not None:
                entity.schema_snapshot_before = before
            if after is not None:
                entity.schema_snapshot_after = after
            if row_sample_before is not None:
                entity.row_sample_before = row_sample_before
            if row_sample_after is not None:
                entity.row_sample_after = row_sample_after
            updated = await self._repository.update(entity)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated

        return await with_txn_retry(_commit, on_retry=self._session.rollback)

    async def merge_timings_and_snapshot(
        self,
        shadow_id: uuid.UUID,
        *,
        timings: dict[str, Any] | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        row_sample_before: dict[str, Any] | None = None,
        row_sample_after: dict[str, Any] | None = None,
    ) -> ShadowCluster:
        """Merge stage timings AND structural/row snapshots in ONE transaction.

        This is a performance-only optimization for the ExecuteMigration
        handler, which previously issued ``merge_timings`` (get+update+
        commit+refresh) and then ``set_schema_snapshot`` (another get+update+
        commit+refresh) — two transactions, 8 DB round-trips for the same
        shadow row. Combining them into a single transaction halves the write
        cost while preserving the exact same semantics:

        * ``timings`` keys are merged into existing ``stage_timings`` (same as
          ``merge_timings``) — a None value is not written.
        * Each snapshot field is only written when provided (same as
          ``set_schema_snapshot``) — a caller that only has the schema doesn't
          clobber values it doesn't have.
        * The event log gains a single entry with the merged timings (same as
          ``record_timings`` would have appended).

        Both public methods (``merge_timings``, ``set_schema_snapshot``)
        remain unchanged for other callers.
        """

        async def _commit() -> ShadowCluster:
            entity = await self._repository.get_by_id_or_raise(shadow_id)
            if timings:
                merged = dict(entity.stage_timings or {})
                for key, value in timings.items():
                    if value is not None:
                        merged[key] = value
                entity.stage_timings = merged
            if before is not None:
                entity.schema_snapshot_before = before
            if after is not None:
                entity.schema_snapshot_after = after
            if row_sample_before is not None:
                entity.row_sample_before = row_sample_before
            if row_sample_after is not None:
                entity.row_sample_after = row_sample_after
            entity.event_log = _append_event(
                entity.event_log,
                status=entity.status.value,
                stage_timings=entity.stage_timings,
            )
            updated = await self._repository.update(entity)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated

        return await with_txn_retry(_commit, on_retry=self._session.rollback)

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

    async def start_hold(
        self,
        shadow_id: uuid.UUID,
        *,
        hold_minutes: int,
    ) -> ShadowCluster:
        """Pause teardown: hold the (still-live) cluster for inspection.

        Sets status to HOLDING and shortens ``expires_at`` to
        ``now + hold_minutes`` so the existing orphan sweeper — which already
        reaps any active status past its expiry — tears it down automatically
        once the window closes, with no separate mechanism needed. A user can
        still end the hold immediately via ``teardown_now``.
        """

        async def _commit() -> ShadowCluster:
            entity = await self._repository.get_by_id_or_raise(shadow_id)
            previous = entity.status
            if previous != ShadowClusterStatus.HOLDING:
                self._validate_transition(previous, ShadowClusterStatus.HOLDING)
                entity.status = ShadowClusterStatus.HOLDING
            entity.expires_at = datetime.now(UTC) + timedelta(minutes=hold_minutes)
            entity.event_log = _append_event(
                entity.event_log,
                status=entity.status.value,
                stage_timings=entity.stage_timings,
            )
            updated = await self._repository.update(entity)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated

        return await with_txn_retry(_commit, on_retry=self._session.rollback)

    async def teardown_now(
        self,
        shadow_id: uuid.UUID,
        *,
        provider,
    ) -> ShadowCluster:
        """End a hold immediately: destroy the cluster and mark DESTROYED.

        Idempotent — a cluster that's already DESTROYED (e.g. the sweeper won
        the race) is returned as-is rather than erroring.
        """
        entity = await self._repository.get_by_id_or_raise(shadow_id)
        if entity.status == ShadowClusterStatus.DESTROYED:
            return entity

        await self.transition(shadow_id, ShadowClusterStatus.DESTROYING)
        try:
            await provider.destroy(
                cluster_id=entity.cluster_id, cluster_name=entity.cluster_name
            )
        except Exception:  # noqa: BLE001 - still record what we know, sweeper is backstop
            await self.set_error(shadow_id, "teardown_now: provider.destroy failed")
            return await self.transition(shadow_id, ShadowClusterStatus.FAILED)
        return await self.transition(shadow_id, ShadowClusterStatus.DESTROYED)

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
