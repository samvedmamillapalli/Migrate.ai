from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.logging import get_logger
from app.schema_analysis.connection import normalize_target_database_url

logger = get_logger(__name__)


@dataclass
class ExecutionOutcome:
    """Measured result of running a migration on the shadow cluster."""

    success: bool
    duration_seconds: float
    storage_growth_mb: float
    rollback_required: bool
    error_message: str | None = None


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
    try:
        baseline_mb: float | None = None
        async with engine.connect() as probe:
            baseline_mb = await _measure_storage_mb(probe)

        started = perf_counter()
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(f"SET statement_timeout = {int(statement_timeout_ms)}")
                )
                for statement in _split_sql(migration_sql):
                    await conn.execute(text(statement))
            duration = round(perf_counter() - started, 4)
        except Exception as exc:  # noqa: BLE001 - migration failure is an outcome
            duration = round(perf_counter() - started, 4)
            logger.info(
                "Shadow migration failed and rolled back",
                extra={"duration_seconds": duration},
            )
            return ExecutionOutcome(
                success=False,
                duration_seconds=duration,
                storage_growth_mb=0.0,
                rollback_required=True,
                error_message=f"{type(exc).__name__}: {exc}"[:2000],
            )

        post_mb: float | None = None
        async with engine.connect() as probe:
            post_mb = await _measure_storage_mb(probe)
        growth = 0.0
        if baseline_mb is not None and post_mb is not None:
            growth = round(max(0.0, post_mb - baseline_mb), 4)

        logger.info(
            "Shadow migration succeeded",
            extra={"duration_seconds": duration, "storage_growth_mb": growth},
        )
        return ExecutionOutcome(
            success=True,
            duration_seconds=duration,
            storage_growth_mb=growth,
            rollback_required=False,
            error_message=None,
        )
    finally:
        await engine.dispose()
