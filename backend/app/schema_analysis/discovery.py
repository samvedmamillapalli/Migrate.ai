from __future__ import annotations

import asyncio
from typing import Callable

from sqlalchemy import text

from app.core.exceptions import (
    SchemaDatabaseNotFoundError,
    UnsupportedDatabaseError,
)
from app.core.logging import get_logger
from app.schema_analysis.analyzer import SchemaAnalyzer
from app.schema_analysis.connection import SchemaAnalysisConnection
from app.schema_analysis.database_connection import DatabaseConnection
from app.schema_analysis.errors import (
    host_and_database_from_url,
    is_cockroach_version_parse_error,
    safe_log_target,
    translate_schema_error,
)
from app.schema_analysis.models import DatabaseMetadata
from app.schema_analysis.read_only import assert_read_only_connection

logger = get_logger(__name__)

# (stage_id, message, percent) — best-effort progress callback so callers can
# drive a staged UI instead of one opaque spinner. Never raises; discovery
# must not fail because a progress sink misbehaves.
OnStage = Callable[[str, str, int], None]


def _emit(on_stage: OnStage | None, stage: str, message: str, percent: int) -> None:
    if on_stage is None:
        return
    try:
        on_stage(stage, message, percent)
    except Exception:  # noqa: BLE001 - progress reporting must never break discovery
        pass


async def discover_database_metadata(
    connection: DatabaseConnection,
    *,
    connect_timeout: int = 30,
    discovery_timeout: int = 60,
    include_schemas: frozenset[str] | None = None,
    analyzer: SchemaAnalyzer | None = None,
    on_stage: OnStage | None = None,
) -> DatabaseMetadata:
    """Validate read-only access and return structured schema metadata.

    This is the only discovery entrypoint application code should call.
    Inspection internals stay inside ``app.schema_analysis``.
    """
    host = connection.host
    database = connection.database
    log_target = safe_log_target(host, database)

    try:
        database_url = connection.to_database_url()
    except ValueError as exc:
        mapped = translate_schema_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise UnsupportedDatabaseError(str(exc)) from exc

    metadata = await _discover_with_url(
        database_url,
        connect_timeout=connect_timeout,
        discovery_timeout=discovery_timeout,
        include_schemas=include_schemas,
        analyzer=analyzer or SchemaAnalyzer(),
        expected_database=database,
        log_target=log_target,
        on_stage=on_stage,
    )

    logger.info(
        "Schema discovery complete",
        extra={
            **log_target,
            "schema_count": metadata.schema_count,
            "table_count": metadata.table_count,
        },
    )
    return metadata


async def discover_from_url(
    database_url: str,
    *,
    connect_timeout: int = 30,
    discovery_timeout: int = 60,
    include_schemas: frozenset[str] | None = None,
) -> DatabaseMetadata:
    """Discover metadata from a raw URL (tests / tooling).

    Prefer ``discover_database_metadata`` with ``DatabaseConnection`` in app code.
    """
    host, database = host_and_database_from_url(database_url)
    log_target = safe_log_target(host, database)
    return await _discover_with_url(
        database_url,
        connect_timeout=connect_timeout,
        discovery_timeout=discovery_timeout,
        include_schemas=include_schemas,
        analyzer=SchemaAnalyzer(),
        expected_database=None,
        log_target=log_target,
    )


async def _discover_with_url(
    database_url: str,
    *,
    connect_timeout: int,
    discovery_timeout: int,
    include_schemas: frozenset[str] | None,
    analyzer: SchemaAnalyzer,
    expected_database: str | None,
    log_target: dict[str, str],
    on_stage: OnStage | None = None,
) -> DatabaseMetadata:
    try:
        return await _discover_once(
            database_url,
            connect_timeout=connect_timeout,
            discovery_timeout=discovery_timeout,
            include_schemas=include_schemas,
            analyzer=analyzer,
            expected_database=expected_database,
            force_cockroach=False,
            on_stage=on_stage,
        )
    except Exception as exc:
        if is_cockroach_version_parse_error(exc):
            logger.info(
                "Retrying schema discovery with CockroachDB dialect",
                extra=log_target,
            )
            try:
                return await _discover_once(
                    database_url,
                    connect_timeout=connect_timeout,
                    discovery_timeout=discovery_timeout,
                    include_schemas=include_schemas,
                    analyzer=analyzer,
                    expected_database=expected_database,
                    force_cockroach=True,
                    on_stage=on_stage,
                )
            except Exception as retry_exc:
                mapped = translate_schema_error(retry_exc)
                if mapped is not None:
                    logger.info(
                        "Schema discovery connection failed",
                        extra={**log_target, "error": mapped.message},
                    )
                    raise mapped from retry_exc
                raise

        mapped = translate_schema_error(exc)
        if mapped is not None:
            logger.info(
                "Schema discovery connection failed",
                extra={**log_target, "error": mapped.message},
            )
            raise mapped from exc
        raise


async def _discover_once(
    database_url: str,
    *,
    connect_timeout: int,
    discovery_timeout: int,
    include_schemas: frozenset[str] | None,
    analyzer: SchemaAnalyzer,
    expected_database: str | None,
    force_cockroach: bool,
    on_stage: OnStage | None = None,
) -> DatabaseMetadata:
    statement_timeout_ms = max(discovery_timeout, 1) * 1000

    async def _run() -> DatabaseMetadata:
        _emit(on_stage, "connecting", "Connecting to database…", 10)
        async with SchemaAnalysisConnection(
            database_url,
            connect_timeout=connect_timeout,
            statement_timeout_ms=statement_timeout_ms,
            force_cockroach=force_cockroach,
        ) as target:
            await target.ping()
            _emit(
                on_stage,
                "authenticating",
                "Connected — verifying read-only access…",
                40,
            )
            async with target.connection() as probe_connection:
                if expected_database is not None:
                    current_db = (
                        await probe_connection.execute(
                            text("SELECT current_database()")
                        )
                    ).scalar_one()
                    if not current_db or str(current_db) != expected_database:
                        raise SchemaDatabaseNotFoundError(
                            "Target database does not exist or is not accessible"
                        )
                await assert_read_only_connection(probe_connection)

            _emit(
                on_stage,
                "reading_schema",
                "Access confirmed — reading tables, columns, indexes…",
                70,
            )
            metadata = await analyzer.analyze_connection(
                target,
                include_schemas=include_schemas,
                enforce_read_only=True,
            )
            _emit(on_stage, "reading_schema", "Schema read complete.", 95)
            return metadata

    return await asyncio.wait_for(_run(), timeout=discovery_timeout)
