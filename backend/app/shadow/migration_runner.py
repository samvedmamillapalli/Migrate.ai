from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.logging import get_logger
from app.schema_analysis.connection import normalize_target_database_url
from app.shadow.changefeed_watch import (
    build_sink_uri,
    start_changefeed_safely,
    stop_changefeed_safely,
)
from app.shadow.job_progress import run_with_job_progress
from app.shadow.job_watch import snapshot_schema_jobs
from app.shadow.schema_snapshot import (
    ShadowSnapshot,
    build_row_ids_for_matching,
    build_schema_diff,
    capture_shadow_snapshot,
    extract_referenced_tables,
)

# Gap left between the migration completing and CANCEL JOB, so the
# changefeed's resolved-interval checkpoint (see changefeed_watch.py) has a
# chance to flush the last events to S3 before the feed is torn down. Not a
# guarantee — CANCEL JOB is not a graceful drain — just a pragmatic mitigation.
_CHANGEFEED_DRAIN_SECONDS = 2.0

logger = get_logger(__name__)


@dataclass
class ExecutionOutcome:
    """Measured result of running a migration on the shadow cluster."""

    success: bool
    duration_seconds: float
    storage_growth_mb: float
    rollback_required: bool
    error_message: str | None = None
    timed_out: bool = False
    job_watch: list[dict] | None = None
    # Live job progress captured during execution (see app.shadow.job_progress) —
    # empty if no CockroachDB notice was ever observed carrying a job id.
    job_ids: list[str] = field(default_factory=list)
    job_progress: list[dict[str, Any]] = field(default_factory=list)
    # Structural before/after snapshots + diff (see app.shadow.schema_snapshot).
    # None when best-effort capture failed — never blocks the migration.
    schema_snapshot_before: dict[str, Any] | None = None
    schema_snapshot_after: dict[str, Any] | None = None
    schema_diff: dict[str, Any] | None = None
    # Real row sample (columns + up to 20 rows + total count) for the tables
    # the migration references — shadow-tier synthetic data, never the
    # customer's rows. None when capture wasn't attempted or failed outright.
    row_sample_before: dict[str, Any] | None = None
    row_sample_after: dict[str, Any] | None = None
    # CockroachDB Changefeed watching the migration's target table(s) — see
    # app.shadow.changefeed_watch. None when not attempted (no credentials
    # configured) or when creation failed; the caller reads the resulting S3
    # objects separately, keyed by run_id, once this is set.
    changefeed_job_id: str | None = None
    changefeed_tables: list[str] = field(default_factory=list)


def _is_timeout_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        hint in text
        for hint in (
            "statement timeout",
            "querycanceled",
            "canceling statement due to statement timeout",
            "timeout",
        )
    )


def _split_sql(sql: str) -> list[str]:
    return [part.strip() for part in sql.split(";") if part.strip()]


async def _measure_storage_mb(conn) -> float | None:
    try:
        result = await conn.execute(
            text(
                "SELECT COALESCE(sum(approximate_disk_bytes), 0) "
                "FROM crdb_internal.table_span_stats "
                "WHERE database_name = current_database()"
            )
        )
        return round(int(result.scalar_one()) / (1024 * 1024), 4)
    except Exception:  # noqa: BLE001
        # `conn` is reused by the caller for `snapshot_schema_jobs` right
        # after this — a failed statement here (this query is known to be
        # unavailable on some CockroachDB Cloud tiers) leaves the connection
        # in an aborted-transaction state otherwise, and the next query on
        # it fails with InFailedSqlTransaction instead of running at all.
        try:
            await conn.rollback()
        except Exception:  # noqa: BLE001
            # A dropped/broken connection makes the rollback itself raise.
            # Unguarded, that escapes this best-effort helper and fails the
            # whole migration with no log line explaining why — measuring
            # storage is enrichment, never a reason to fail a run that
            # already executed successfully.
            logger.warning("Storage measurement rollback failed; ignoring")
        return None


async def _post_migration_measure(
    engine,
    connection_url: str,
    referenced_tables: list[str],
    match_row_ids: dict[str, list[dict[str, Any]]] | None,
) -> tuple[float | None, list[dict[str, Any]], ShadowSnapshot | None]:
    """Run the three independent post-migration read-only measurements
    concurrently on separate pooled connections.

    These are mutually independent (storage span stats, SHOW JOBS snapshot,
    structural after-snapshot) and all read-only against the disposable
    shadow cluster. Running them serially multiplied network round-trip
    latency; the after-snapshot capture alone issues ~8 catalog queries plus
    exact row counts. Each gets its own connection from the engine's pool
    (default QueuePool: pool_size=5, max_overflow=10 safely supports 3).

    All three are best-effort enrichment on an already-measured migration:
    a failure in any one degrades the metrics, never fails the run. Each
    helper isolates its own failure so ``asyncio.gather`` never sees an
    exception escape (preserving the original "post-hoc measurement must not
    fail a run that already worked" guarantee).
    """

    async def _measure() -> float | None:
        try:
            async with engine.connect() as probe:
                return await _measure_storage_mb(probe)
        except Exception as exc:  # noqa: BLE001 - best-effort measurement
            logger.warning(
                "Post-migration storage measurement failed; reporting "
                "migration as succeeded with degraded metrics",
                extra={"error": f"{type(exc).__name__}: {exc}"},
            )
            return None

    async def _jobs() -> list[dict[str, Any]]:
        try:
            async with engine.connect() as probe:
                return await snapshot_schema_jobs(probe)
        except Exception as exc:  # noqa: BLE001 - best-effort measurement
            logger.warning(
                "Post-migration job watch failed; reporting migration as "
                "succeeded with degraded metrics",
                extra={"error": f"{type(exc).__name__}: {exc}"},
            )
            return []

    async def _snapshot() -> ShadowSnapshot | None:
        # capture_shadow_snapshot handles its own connection acquisition and
        # retries internally, returning None on total failure — it never
        # raises, so no extra guard is needed here.
        return await capture_shadow_snapshot(
            connection_url,
            sample_tables=referenced_tables,
            match_row_ids=match_row_ids,
            engine=engine,
        )

    post_mb, jobs, after_snapshot = await asyncio.gather(
        _measure(), _jobs(), _snapshot()
    )
    return post_mb, jobs, after_snapshot


async def run_migration(
    connection_url: str,
    migration_sql: str,
    *,
    statement_timeout_ms: int = 600_000,
    run_id: str | None = None,
    changefeed_s3_bucket: str | None = None,
    changefeed_access_key_id: str | None = None,
    changefeed_secret_access_key: str | None = None,
) -> ExecutionOutcome:
    """Execute ``migration_sql`` inside one transaction on the shadow cluster.

    Blast radius is measured as backfill duration and storage growth (never lock
    duration — CockroachDB runs schema changes as online background jobs). On
    failure the transaction is rolled back, so nothing is left half-applied and
    ``rollback_required`` is True.

    When ``run_id`` and the three ``changefeed_*`` credentials are all
    provided, a CockroachDB Changefeed on the migration's referenced table(s)
    runs alongside the migration — see app.shadow.changefeed_watch for why
    this augments rather than replaces the SHOW JOBS polling below. Any one
    missing skips the changefeed entirely; this is enrichment, never a
    dependency of the measured outcome.
    """
    normalized = normalize_target_database_url(connection_url, force_cockroach=True)
    engine = create_async_engine(normalized, pool_pre_ping=True)
    referenced_tables = extract_referenced_tables(migration_sql)
    changefeed_enabled = bool(
        run_id
        and changefeed_s3_bucket
        and changefeed_access_key_id
        and changefeed_secret_access_key
        and referenced_tables
    )
    changefeed_job_id: str | None = None
    try:
        baseline_mb: float | None = None
        async with engine.connect() as probe:
            baseline_mb = await _measure_storage_mb(probe)
        before_snapshot = await capture_shadow_snapshot(
            normalized, sample_tables=referenced_tables, engine=engine
        )
        schema_before = before_snapshot.schema if before_snapshot else None
        row_sample_before = before_snapshot.row_samples if before_snapshot else None
        match_row_ids = build_row_ids_for_matching(row_sample_before)

        if changefeed_enabled:
            sink_uri = build_sink_uri(
                bucket=changefeed_s3_bucket,  # type: ignore[arg-type]
                run_id=run_id,  # type: ignore[arg-type]
                access_key_id=changefeed_access_key_id,  # type: ignore[arg-type]
                secret_access_key=changefeed_secret_access_key,  # type: ignore[arg-type]
            )
            # Engine-level wrapper, not `async with engine.begin()` + a bare
            # create_changefeed: the wrapper owns the transaction so a failed
            # COMMIT can't escape past this line. See changefeed_watch.py.
            changefeed_job_id = await start_changefeed_safely(
                engine, tables=referenced_tables, sink_uri=sink_uri
            )

        started = perf_counter()
        progress = await run_with_job_progress(
            normalized,
            _split_sql(migration_sql),
            statement_timeout_ms=statement_timeout_ms,
        )
        duration = round(perf_counter() - started, 4)

        if changefeed_job_id is not None:
            # Not a graceful drain — CANCEL JOB stops the feed abruptly, so
            # give the resolved-interval checkpoint a moment to flush the
            # last events to S3 first. See changefeed_watch.py.
            await asyncio.sleep(_CHANGEFEED_DRAIN_SECONDS)
            await stop_changefeed_safely(engine, changefeed_job_id)

        if not progress.succeeded:
            exc = progress.error
            jobs: list = []
            try:
                async with engine.connect() as probe:
                    jobs = await snapshot_schema_jobs(probe)
            except Exception:  # noqa: BLE001 - best-effort watch after failure
                jobs = []
            after_snapshot = await capture_shadow_snapshot(
                normalized,
                sample_tables=referenced_tables,
                match_row_ids=match_row_ids,
                engine=engine,
            )
            schema_after = after_snapshot.schema if after_snapshot else None
            row_sample_after = after_snapshot.row_samples if after_snapshot else None
            logger.info(
                "Shadow migration failed and rolled back",
                extra={
                    "duration_seconds": duration,
                    "job_watch_count": len(jobs),
                    "job_progress_count": len(progress.observations),
                },
            )
            return ExecutionOutcome(
                success=False,
                duration_seconds=duration,
                storage_growth_mb=0.0,
                rollback_required=True,
                error_message=(
                    f"{type(exc).__name__}: {exc}"[:2000] if exc else "Migration failed"
                ),
                timed_out=_is_timeout_error(exc) if exc else False,
                job_watch=jobs,
                job_ids=progress.job_ids,
                job_progress=progress.observations,
                schema_snapshot_before=schema_before,
                schema_snapshot_after=schema_after,
                schema_diff=build_schema_diff(schema_before, schema_after),
                row_sample_before=row_sample_before,
                row_sample_after=row_sample_after,
                changefeed_job_id=changefeed_job_id,
                changefeed_tables=referenced_tables if changefeed_enabled else [],
            )

        # The migration has already executed successfully by this point — the
        # measured outcome is final. Everything below is post-hoc measurement,
        # so a transient connection failure here must degrade the numbers, not
        # fail a run that actually worked. (Before this guard, an exception
        # while acquiring or releasing this connection surfaced as a hard
        # "ExecuteMigration failed" with no log line — see the same-day
        # regression on run c1635bcc-d801-4288-9afe-5af932014d5e.)
        # The three measurements are independent and read-only, so they run
        # concurrently on separate pooled connections.
        post_mb, jobs, after_snapshot = await _post_migration_measure(
            engine,
            normalized,
            referenced_tables,
            match_row_ids,
        )
        schema_after = after_snapshot.schema if after_snapshot else None
        row_sample_after = after_snapshot.row_samples if after_snapshot else None
        growth = 0.0
        if baseline_mb is not None and post_mb is not None:
            growth = round(max(0.0, post_mb - baseline_mb), 4)

        logger.info(
            "Shadow migration succeeded",
            extra={
                "duration_seconds": duration,
                "storage_growth_mb": growth,
                "job_watch_count": len(jobs),
                "job_progress_count": len(progress.observations),
            },
        )
        return ExecutionOutcome(
            success=True,
            duration_seconds=duration,
            storage_growth_mb=growth,
            rollback_required=False,
            error_message=None,
            job_watch=jobs,
            job_ids=progress.job_ids,
            job_progress=progress.observations,
            schema_snapshot_before=schema_before,
            schema_snapshot_after=schema_after,
            schema_diff=build_schema_diff(schema_before, schema_after),
            row_sample_before=row_sample_before,
            row_sample_after=row_sample_after,
            changefeed_job_id=changefeed_job_id,
            changefeed_tables=referenced_tables if changefeed_enabled else [],
        )
    finally:
        await engine.dispose()
