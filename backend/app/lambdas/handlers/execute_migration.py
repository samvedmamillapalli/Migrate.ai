"""ExecuteMigration Lambda — run migration SQL on the shadow cluster."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.database.models import ShadowClusterStatus
from app.lambdas.errors import LambdaHandlerError, LambdaValidationError
from app.lambdas.helpers import parse_run_id, shadow_secret_name
from app.lambdas.runtime import get_runtime, run_async, with_session
from app.repositories.migration_run_repository import MigrationRunRepository
from app.repositories.shadow_cluster_repository import ShadowClusterRepository
from app.services.shadow_cluster_service import ShadowClusterService
from app.shadow.migration_runner import run_migration

logger = get_logger(__name__)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    from app.lambdas.runtime import handler_correlation

    with handler_correlation(event, context, function_name="execute-migration"):
        return run_async(_handle(event))


async def _handle(event: dict[str, Any]) -> dict[str, Any]:
    run_id = parse_run_id(event)
    runtime = get_runtime()
    settings = runtime.settings

    provision = event.get("provision_shadow_cluster") or {}
    shadow_secret_arn = (
        event.get("shadow_secret_arn")
        or provision.get("shadow_secret_arn")
        or shadow_secret_name(run_id)
    )

    logger.info("ExecuteMigration started", extra={"run_id": str(run_id)})

    async def _run(session):
        run_repo = MigrationRunRepository(session)
        shadow_repo = ShadowClusterRepository(session)
        shadow_service = ShadowClusterService(repository=shadow_repo, session=session)

        run = await run_repo.get_by_id_or_raise(run_id)
        shadow = await shadow_service.get_by_run(run_id)
        if shadow is None:
            raise LambdaValidationError(f"No shadow cluster for run_id={run_id}")

        if shadow.status in {ShadowClusterStatus.SEEDING, ShadowClusterStatus.READY}:
            await shadow_service.transition(shadow.id, ShadowClusterStatus.MIGRATING)
        elif shadow.status == ShadowClusterStatus.MIGRATING:
            pass
        else:
            raise LambdaValidationError(
                f"Shadow cluster not ready for migration: {shadow.status.value}"
            )

        connection_url = await runtime.secrets.get_string(str(shadow_secret_arn))
        outcome = await run_migration(
            connection_url,
            run.migration_sql,
            statement_timeout_ms=int(settings.shadow_migrate_timeout_seconds * 1000),
        )
        return {
            "run_id": str(run_id),
            "shadow_id": str(shadow.id),
            "success": outcome.success,
            "duration_seconds": outcome.duration_seconds,
            "storage_growth_mb": outcome.storage_growth_mb,
            "rollback_required": outcome.rollback_required,
            "error_message": outcome.error_message,
            "timed_out": outcome.timed_out,
            "job_watch": outcome.job_watch or [],
            "cockroachdb_tools": (
                "Distributed Vector Indexing + Managed MCP / SQL job watch"
            ),
        }

    try:
        result = await with_session(runtime, _run)
    except LambdaValidationError:
        raise
    except Exception as exc:
        raise LambdaHandlerError(
            f"ExecuteMigration failed for run_id={run_id}"
        ) from exc

    logger.info(
        "ExecuteMigration completed",
        extra={
            "run_id": str(run_id),
            "success": result.get("success"),
            "duration_seconds": result.get("duration_seconds"),
        },
    )
    return result
