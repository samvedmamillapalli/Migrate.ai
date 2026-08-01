from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.logging import get_logger
from app.schema_analysis.connection import normalize_target_database_url
from app.shadow.job_progress import run_with_job_progress
from app.shadow.job_watch import snapshot_schema_jobs
from app.shadow.schema_snapshot import (
    build_row_ids_for_matching,
    build_schema_diff,
    capture_shadow_snapshot,
    extract_referenced_tables,
)

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
        await conn.rollback()
        return None


async def run_migration(
    connection_url: str,
    migration_sql: str,
    *,
    statement_timeout_ms: int = 600_000,
) -> ExecutionOutcome:
    """Execute ``migration_sql`` inside one transaction on the shadow cluster.

    Blast radius is measured as backfill duration and storage growth (never lock
    duration — CockroachDB runs schema changes as online background jobs). On
    failure the transaction is rolled back, so nothing is left half-applied and
    ``rollback_required`` is True.
    """
    normalized = normalize_target_database_url(connection_url, force_cockroach=True)
    engine = create_async_engine(normalized, pool_pre_ping=True)
    referenced_tables = extract_referenced_tables(migration_sql)
    try:
        baseline_mb: float | None = None
        async with engine.connect() as probe:
            baseline_mb = await _measure_storage_mb(probe)
        before_snapshot = await capture_shadow_snapshot(
            normalized, sample_tables=referenced_tables
        )
        schema_before = before_snapshot.schema if before_snapshot else None
        row_sample_before = before_snapshot.row_samples if before_snapshot else None
        match_row_ids = build_row_ids_for_matching(row_sample_before)

        started = perf_counter()
        progress = await run_with_job_progress(
            normalized,
            _split_sql(migration_sql),
            statement_timeout_ms=statement_timeout_ms,
        )
        duration = round(perf_counter() - started, 4)

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
            )

        post_mb: float | None = None
        jobs = []
        async with engine.connect() as probe:
            post_mb = await _measure_storage_mb(probe)
            jobs = await snapshot_schema_jobs(probe)
        after_snapshot = await capture_shadow_snapshot(
            normalized,
            sample_tables=referenced_tables,
            match_row_ids=match_row_ids,
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
        )
    finally:
        await engine.dispose()
