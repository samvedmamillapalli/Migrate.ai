from __future__ import annotations

import uuid
from time import perf_counter

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.database.models import ShadowCluster, ShadowClusterStatus
from app.schema_analysis.connection import normalize_target_database_url
from app.schema_analysis.models import DatabaseMetadata
from app.services.shadow_cluster_service import ShadowClusterService
from app.shadow.concurrency import acquire_slot
from app.shadow.models import (
    LifecycleReport,
    ProvisionSpec,
    ProvisionedCluster,
    ScaleTier,
    StageTimings,
    select_scale_tier,
)
from app.shadow.provider import ShadowClusterProvider
from app.shadow.schema_loader import ShadowSchemaLoader

logger = get_logger(__name__)


class ShadowClusterOrchestrator:
    """Drives one shadow cluster through its full lifecycle.

    create -> await ready -> load schema -> run migration -> destroy, with
    teardown guaranteed on every path (success, failure, timeout) via
    ``finally``.

    The "seed" stage recreates the customer's real schema structure (schemas,
    tables, columns, primary keys, foreign keys, indexes, UNIQUE/CHECK
    constraints) from the Phase 6 snapshot via ``ShadowSchemaLoader`` — the
    same fully-verified path as Phase 7B. No synthetic rows are inserted; the
    shadow cluster is always a real, correctly-shaped, empty copy of the
    customer's structure, never a mock/offline database.

    Blast radius of the migration under test is measured as backfill duration,
    storage growth, resource saturation and rollback safety — never as lock
    duration (CockroachDB runs schema changes as online background jobs).
    """

    def __init__(
        self,
        *,
        service: ShadowClusterService,
        provider: ShadowClusterProvider,
        settings: Settings | None = None,
        schema_loader: ShadowSchemaLoader | None = None,
    ) -> None:
        self._service = service
        self._provider = provider
        self._settings = settings or get_settings()
        self._schema_loader = schema_loader or ShadowSchemaLoader()

    async def run_lifecycle(
        self,
        *,
        run_id: uuid.UUID,
        metadata: DatabaseMetadata,
        migration_sql: str,
        scale_tier: ScaleTier | None = None,
    ) -> LifecycleReport:
        settings = self._settings
        tier = scale_tier or select_scale_tier(_total_rows(metadata))

        # --- Admission (concurrency cap; queues/waits when full) ---
        shadow = await acquire_slot(
            self._service,
            run_id=run_id,
            region=settings.shadow_cluster_region,
            provider=self._provider.name,
            scale_tier=tier.value,
            max_concurrent=settings.shadow_max_concurrent,
            max_lifetime_minutes=settings.shadow_max_lifetime_minutes,
            wait_timeout_seconds=settings.shadow_slot_wait_timeout_seconds,
            poll_interval_seconds=settings.shadow_slot_poll_interval_seconds,
        )

        timings = StageTimings()
        report = LifecycleReport(
            run_id=run_id,
            cluster_id=None,
            cluster_name=shadow.cluster_name or "",
            scale_tier=tier,
            succeeded=False,
            torn_down=False,
            timings=timings,
        )
        provisioned: ProvisionedCluster | None = None

        try:
            provisioned = await self._provision(shadow, run_id, tier, timings)
            report.cluster_id = provisioned.cluster_id
            report.cluster_name = provisioned.cluster_name

            await self._await_ready(shadow, provisioned, timings)
            report.seed = await self._seed(shadow, provisioned, metadata, tier, timings)
            baseline_mb = await _measure_storage_mb(provisioned.connection_url)

            migrate_seconds = await self._migrate(
                shadow, provisioned, migration_sql, timings
            )
            report.migration_duration_seconds = migrate_seconds

            post_mb = await _measure_storage_mb(provisioned.connection_url)
            if baseline_mb is not None and post_mb is not None:
                report.storage_growth_mb = round(post_mb - baseline_mb, 4)

            report.succeeded = True
        except Exception as exc:  # noqa: BLE001 - recorded, then teardown runs
            report.error = f"{type(exc).__name__}: {exc}"
            await self._service.set_error(shadow.id, report.error)
            logger.warning(
                "Shadow lifecycle stage failed; proceeding to teardown",
                extra={"run_id": str(run_id), "error": report.error},
            )
        finally:
            report.torn_down = await self._teardown(shadow, provisioned, timings)
            await self._service.record_timings(shadow.id, timings.as_dict())

        return report

    # -- stages -------------------------------------------------------------

    async def _provision(
        self,
        shadow: ShadowCluster,
        run_id: uuid.UUID,
        tier: ScaleTier,
        timings: StageTimings,
    ) -> ProvisionedCluster:
        spec = ProvisionSpec(
            run_id=run_id,
            cluster_name=_cluster_name(self._settings.shadow_app_tag, run_id),
            app_tag=self._settings.shadow_app_tag,
            cloud=self._settings.shadow_cluster_cloud,
            region=self._settings.shadow_cluster_region,
        )
        started = perf_counter()
        provisioned = await self._provider.create(spec)
        timings.provision_ms = _ms_since(started)
        await self._service.set_identity(
            shadow.id,
            cluster_id=provisioned.cluster_id,
            cluster_name=provisioned.cluster_name,
        )
        return provisioned

    async def _await_ready(
        self,
        shadow: ShadowCluster,
        provisioned: ProvisionedCluster,
        timings: StageTimings,
    ) -> None:
        started = perf_counter()
        await self._provider.await_ready(
            provisioned,
            timeout_seconds=self._settings.shadow_provision_timeout_seconds,
            poll_interval_seconds=self._settings.shadow_ready_poll_interval_seconds,
        )
        # Some providers (the real ccloud_api one) only know the connection
        # shape once a SQL user is minted on the now-ready cluster; others
        # (mock) already attached it in create(). Always ensure it here so
        # every downstream stage can rely on provisioned.connection_url.
        await self._provider.provision_sql_access(provisioned)
        timings.ready_ms = _ms_since(started)
        await self._service.transition(shadow.id, ShadowClusterStatus.READY)

    async def _seed(
        self,
        shadow: ShadowCluster,
        provisioned: ProvisionedCluster,
        metadata: DatabaseMetadata,
        tier: ScaleTier,
        timings: StageTimings,
    ):  # noqa: ANN201 - returns SchemaLoadReport
        await self._service.transition(shadow.id, ShadowClusterStatus.SEEDING)
        started = perf_counter()
        load_report = await self._schema_loader.load(
            provisioned.connection_url,
            metadata,
            statement_timeout_ms=self._settings.shadow_seed_timeout_seconds * 1000,
        )
        timings.seed_ms = _ms_since(started)
        return load_report

    async def _migrate(
        self,
        shadow: ShadowCluster,
        provisioned: ProvisionedCluster,
        migration_sql: str,
        timings: StageTimings,
    ) -> float:
        await self._service.transition(shadow.id, ShadowClusterStatus.MIGRATING)
        normalized = normalize_target_database_url(
            provisioned.connection_url, force_cockroach=True
        )
        engine = create_async_engine(normalized, pool_pre_ping=True)
        started = perf_counter()
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "SET statement_timeout = "
                        f"{self._settings.shadow_migrate_timeout_seconds * 1000}"
                    )
                )
                for statement in _split_sql(migration_sql):
                    await conn.execute(text(statement))
        finally:
            await engine.dispose()
            timings.migrate_ms = _ms_since(started)
        return round(perf_counter() - started, 4)

    async def _teardown(
        self,
        shadow: ShadowCluster,
        provisioned: ProvisionedCluster | None,
        timings: StageTimings,
    ) -> bool:
        """Destroy the cluster. Runs on every path; idempotent."""
        started = perf_counter()
        cluster_id = provisioned.cluster_id if provisioned else shadow.cluster_id
        cluster_name = provisioned.cluster_name if provisioned else shadow.cluster_name
        try:
            await self._service.transition(shadow.id, ShadowClusterStatus.DESTROYING)
            await self._provider.destroy(
                cluster_id=cluster_id,
                cluster_name=cluster_name,
            )
            timings.teardown_ms = _ms_since(started)
            await self._service.transition(shadow.id, ShadowClusterStatus.DESTROYED)
            return True
        except Exception as exc:  # noqa: BLE001
            timings.teardown_ms = _ms_since(started)
            # Teardown itself failed: the cluster may be leaked. Mark FAILED so
            # the sweeper is the backstop.
            logger.error(
                "Shadow teardown failed; sweeper will reap",
                extra={"shadow_id": str(shadow.id), "error": str(exc)},
            )
            await self._service.set_error(shadow.id, f"teardown failed: {exc}")
            try:
                await self._service.transition(shadow.id, ShadowClusterStatus.FAILED)
            except Exception:  # noqa: BLE001
                pass
            return False


def _cluster_name(app_tag: str, run_id: uuid.UUID) -> str:
    return f"{app_tag}-{run_id.hex[:12]}"


def _total_rows(metadata: DatabaseMetadata) -> int | None:
    total = 0
    seen = False
    for schema in metadata.schemas:
        for table in schema.tables:
            if table.estimated_row_count is not None:
                total += table.estimated_row_count
                seen = True
    return total if seen else None


def _split_sql(sql: str) -> list[str]:
    """Naive multi-statement split.

    Sufficient for the DDL this phase runs. Multi-statement migrations with
    semicolons inside string literals should be submitted one statement per run
    until a real SQL parser is wired in.
    """
    return [part.strip() for part in sql.split(";") if part.strip()]


def _ms_since(started: float) -> float:
    return round((perf_counter() - started) * 1000, 3)


async def _measure_storage_mb(connection_url: str) -> float | None:
    """Best-effort on-disk size of the shadow database, in MB.

    Uses ``crdb_internal.table_span_stats``. Returns ``None`` if the estimate is
    unavailable, so callers treat storage growth as best-effort.
    """
    normalized = normalize_target_database_url(connection_url, force_cockroach=True)
    engine = create_async_engine(normalized, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT COALESCE(sum(approximate_disk_bytes), 0) "
                    "FROM crdb_internal.table_span_stats "
                    "WHERE database_name = current_database()"
                )
            )
            value = result.scalar_one()
            return round(int(value) / (1024 * 1024), 4)
    except Exception:  # noqa: BLE001 - storage estimate is best-effort
        return None
    finally:
        await engine.dispose()
