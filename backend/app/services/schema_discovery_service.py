from __future__ import annotations

import uuid
from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.exceptions import ReadWriteCredentialsError
from app.core.logging import get_logger
from app.database.models import MigrationRun, SchemaDiscoveryStatus
from app.database.retry import with_txn_retry
from app.repositories.migration_run_repository import MigrationRunRepository
from app.schema_analysis.database_connection import DatabaseConnection
from app.schema_analysis.discovery import discover_database_metadata
from app.schema_analysis.errors import safe_log_target
from app.schema_analysis.models import DatabaseMetadata
from app.services.pipeline_progress import clear_progress, set_progress

logger = get_logger(__name__)


class SchemaDiscoveryService:
    """Persist schema discovery results on a MigrationRun.

    Discovery mechanics live entirely in ``app.schema_analysis``.
    """

    def __init__(
        self,
        repository: MigrationRunRepository,
        session: AsyncSession,
        settings: Settings | None = None,
    ) -> None:
        self._repository = repository
        self._session = session
        self._settings = settings or get_settings()

    async def discover_and_persist(
        self,
        run_id: uuid.UUID,
        connection: DatabaseConnection,
        *,
        connection_secret_arn: str | None = None,
    ) -> MigrationRun:
        run = await self._repository.get_by_id_or_raise(run_id)
        started = perf_counter()
        log_fields = {
            "run_id": str(run_id),
            **safe_log_target(connection.host, connection.database),
        }

        logger.info("Starting schema discovery", extra=log_fields)

        def _on_stage(stage: str, message: str, percent: int) -> None:
            set_progress(run_id, stage=stage, message=message, percent=percent)

        set_progress(run_id, stage="starting", message="Starting discovery…", percent=1)
        try:
            metadata = await discover_database_metadata(
                connection,
                connect_timeout=self._settings.schema_connection_timeout_seconds,
                discovery_timeout=self._settings.schema_discovery_timeout_seconds,
                on_stage=_on_stage,
            )
        except ReadWriteCredentialsError:
            duration_ms = (perf_counter() - started) * 1000
            set_progress(
                run_id,
                stage="failed",
                message="Connected, but credentials allow writes — rejected.",
                percent=100,
            )
            await self._persist_failure(
                run,
                status=SchemaDiscoveryStatus.REJECTED,
                duration_ms=duration_ms,
            )
            logger.info(
                "Schema discovery rejected writable credentials",
                extra={**log_fields, "duration_ms": round(duration_ms, 2)},
            )
            raise
        except Exception as exc:
            duration_ms = (perf_counter() - started) * 1000
            set_progress(
                run_id,
                stage="failed",
                message=f"Discovery failed: {type(exc).__name__}",
                percent=100,
            )
            await self._persist_failure(
                run,
                status=SchemaDiscoveryStatus.FAILED,
                duration_ms=duration_ms,
            )
            logger.info(
                "Schema discovery failed",
                extra={**log_fields, "duration_ms": round(duration_ms, 2)},
            )
            raise

        duration_ms = (perf_counter() - started) * 1000
        set_progress(run_id, stage="done", message="Schema discovered.", percent=100)
        updated = await self._persist_success(
            run,
            metadata=metadata,
            duration_ms=duration_ms,
            connection_secret_arn=connection_secret_arn,
        )
        clear_progress(run_id)
        logger.info(
            "Schema discovery succeeded",
            extra={
                **log_fields,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return updated

    async def persist_metadata_snapshot(
        self,
        run_id: uuid.UUID,
        metadata: DatabaseMetadata,
        *,
        duration_ms: float = 0.0,
    ) -> MigrationRun:
        """Persist an already-built metadata snapshot (idempotent local/fixture path).

        Prefer ``discover_and_persist`` for live customer databases. This method
        exists so Lambda/local runners can store a validated snapshot without
        duplicating MigrationRun field assignment.
        """
        run = await self._repository.get_by_id_or_raise(run_id)
        if (
            run.schema_discovery_status == SchemaDiscoveryStatus.SUCCEEDED
            and run.schema_snapshot
        ):
            return run
        return await self._persist_success(
            run,
            metadata=metadata,
            duration_ms=duration_ms,
        )

    async def _persist_success(
        self,
        run: MigrationRun,
        *,
        metadata: DatabaseMetadata,
        duration_ms: float,
        connection_secret_arn: str | None = None,
    ) -> MigrationRun:
        run_id = run.id

        async def _commit() -> MigrationRun:
            entity = await self._repository.get_by_id_or_raise(run_id)
            entity.schema_snapshot = metadata.model_dump(mode="json", by_alias=True)
            entity.schema_discovered_at = datetime.now(UTC)
            entity.schema_discovery_duration_ms = duration_ms
            entity.schema_database_engine = _infer_engine(metadata.server_version)
            entity.schema_database_version = metadata.server_version
            entity.schema_discovery_status = SchemaDiscoveryStatus.SUCCEEDED
            if connection_secret_arn:
                entity.connection_secret_arn = connection_secret_arn

            updated = await self._repository.update(entity)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated

        return await with_txn_retry(
            _commit,
            on_retry=self._session.rollback,
        )

    async def _persist_failure(
        self,
        run: MigrationRun,
        *,
        status: SchemaDiscoveryStatus,
        duration_ms: float,
    ) -> MigrationRun:
        run_id = run.id

        async def _commit() -> MigrationRun:
            entity = await self._repository.get_by_id_or_raise(run_id)
            entity.schema_snapshot = None
            entity.schema_discovered_at = datetime.now(UTC)
            entity.schema_discovery_duration_ms = duration_ms
            entity.schema_database_engine = None
            entity.schema_database_version = None
            entity.schema_discovery_status = status

            updated = await self._repository.update(entity)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated

        return await with_txn_retry(
            _commit,
            on_retry=self._session.rollback,
        )


def _infer_engine(server_version: str | None) -> str | None:
    if not server_version:
        return None
    lowered = server_version.lower()
    if "cockroachdb" in lowered:
        return "cockroachdb"
    if "postgresql" in lowered or "postgres" in lowered:
        return "postgresql"
    return "unknown"
