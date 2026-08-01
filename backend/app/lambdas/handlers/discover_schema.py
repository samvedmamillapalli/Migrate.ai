"""DiscoverSchema Lambda — inspect customer DB and persist schema snapshot."""

from __future__ import annotations

from typing import Any

from app.core.exceptions import ReadWriteCredentialsError
from app.core.logging import get_logger
from app.database.models import SchemaDiscoveryStatus
from app.lambdas.errors import LambdaHandlerError, LambdaValidationError
from app.lambdas.helpers import (
    connection_from_secret,
    discovery_already_done,
    local_fixture_metadata,
    parse_run_id,
)
from app.lambdas.runtime import (
    get_runtime,
    handler_correlation,
    is_local_mode,
    run_async,
    with_session,
)
from app.repositories.migration_run_repository import MigrationRunRepository
from app.services.schema_discovery_service import SchemaDiscoveryService

logger = get_logger(__name__)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    with handler_correlation(event, context, function_name="discover-schema"):
        return run_async(_handle(event))


async def _handle(event: dict[str, Any]) -> dict[str, Any]:
    run_id = parse_run_id(event)
    secret_arn = event.get("connection_secret_arn")
    if not secret_arn or not isinstance(secret_arn, str):
        raise LambdaValidationError("connection_secret_arn is required")

    runtime = get_runtime()
    logger.info(
        "DiscoverSchema started",
        extra={"connection_secret_arn": secret_arn},
    )

    async def _run(session):
        repository = MigrationRunRepository(session)
        service = SchemaDiscoveryService(
            repository=repository,
            session=session,
            settings=runtime.settings,
        )
        run = await repository.get_by_id_or_raise(run_id)
        if discovery_already_done(run.schema_discovery_status):
            artifact = await _maybe_upload_snapshot(runtime, str(run_id), run.schema_snapshot)
            logger.info(
                "DiscoverSchema idempotent skip",
                extra={"status": run.schema_discovery_status},
            )
            return {
                "run_id": str(run_id),
                "status": SchemaDiscoveryStatus.SUCCEEDED.value,
                "schema_database_engine": run.schema_database_engine,
                "table_count": (
                    (run.schema_snapshot or {}).get("table_count")
                    if isinstance(run.schema_snapshot, dict)
                    else None
                ),
                "schema_snapshot_uri": artifact.get("uri") if artifact else None,
                "idempotent": True,
            }

        secret = await runtime.secrets.get_json(secret_arn)
        connection = connection_from_secret(secret)

        try:
            updated = await service.discover_and_persist(run_id, connection)
        except ReadWriteCredentialsError:
            if not is_local_mode():
                raise
            logger.warning("DiscoverSchema falling back to local fixture metadata")
            updated = await service.persist_metadata_snapshot(
                run_id,
                local_fixture_metadata(),
            )
        except Exception as exc:
            raise LambdaHandlerError(
                f"Schema discovery failed for run_id={run_id}"
            ) from exc

        snapshot = (
            updated.schema_snapshot if isinstance(updated.schema_snapshot, dict) else {}
        )
        artifact = await _maybe_upload_snapshot(runtime, str(run_id), snapshot)
        return {
            "run_id": str(run_id),
            "status": (
                updated.schema_discovery_status.value
                if updated.schema_discovery_status
                else SchemaDiscoveryStatus.SUCCEEDED.value
            ),
            "schema_database_engine": updated.schema_database_engine,
            "table_count": snapshot.get("table_count"),
            "schema_snapshot_uri": artifact.get("uri") if artifact else None,
            "idempotent": False,
        }

    result = await with_session(runtime, _run)
    logger.info("DiscoverSchema completed", extra={"status": result.get("status")})
    return result


async def _maybe_upload_snapshot(runtime, run_id: str, snapshot: dict | None):
    if not snapshot or runtime.artifacts is None:
        return None
    return await runtime.artifacts.put_schema_snapshot(run_id, snapshot)
