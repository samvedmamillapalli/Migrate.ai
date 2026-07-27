"""LoadSchema Lambda — recreate customer schema structure on the shadow cluster."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from app.core.logging import get_logger
from app.database.models import ShadowClusterStatus
from app.lambdas.errors import LambdaHandlerError, LambdaValidationError
from app.lambdas.helpers import parse_run_id, shadow_secret_name, total_estimated_rows
from app.lambdas.runtime import get_runtime, run_async, with_session
from app.repositories.migration_run_repository import MigrationRunRepository
from app.repositories.shadow_cluster_repository import ShadowClusterRepository
from app.schema_analysis.models import DatabaseMetadata
from app.services.shadow_cluster_service import ShadowClusterService
from app.shadow.models import ScaleTier, select_scale_tier
from app.shadow.schema_loader import ShadowSchemaLoader
from app.shadow.seeder import ShadowSeeder

logger = get_logger(__name__)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    from app.lambdas.runtime import handler_correlation

    with handler_correlation(event, context, function_name="load-schema"):
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

    logger.info("LoadSchema started", extra={"run_id": str(run_id)})

    async def _run(session):
        run_repo = MigrationRunRepository(session)
        shadow_repo = ShadowClusterRepository(session)
        shadow_service = ShadowClusterService(repository=shadow_repo, session=session)

        run = await run_repo.get_by_id_or_raise(run_id)
        if not run.schema_snapshot:
            raise LambdaValidationError("schema_snapshot is required before load_schema")
        metadata = DatabaseMetadata.model_validate(run.schema_snapshot)

        shadow = await shadow_service.get_by_run(run_id)
        if shadow is None:
            raise LambdaValidationError(f"No shadow cluster for run_id={run_id}")

        if shadow.status == ShadowClusterStatus.READY:
            await shadow_service.transition(shadow.id, ShadowClusterStatus.SEEDING)
        elif shadow.status == ShadowClusterStatus.SEEDING:
            pass  # idempotent retry
        elif shadow.status in {
            ShadowClusterStatus.MIGRATING,
            ShadowClusterStatus.DESTROYING,
            ShadowClusterStatus.DESTROYED,
        }:
            # Already past seeding — treat as success for retries.
            return {
                "run_id": str(run_id),
                "shadow_id": str(shadow.id),
                "tables_created": 0,
                "status": shadow.status.value,
                "idempotent": True,
            }
        else:
            raise LambdaValidationError(
                f"Shadow cluster not ready for schema load: {shadow.status.value}"
            )

        connection_url = await runtime.secrets.get_string(str(shadow_secret_arn))
        loader = ShadowSchemaLoader()
        t0 = perf_counter()
        report = await loader.load(
            connection_url,
            metadata,
            statement_timeout_ms=int(settings.shadow_seed_timeout_seconds * 1000),
        )
        rows_inserted = 0
        seed_warnings: list[str] = []
        if getattr(settings, "shadow_seed_synthetic_rows", True):
            tier = ScaleTier.SMALL
            if shadow.scale_tier:
                try:
                    tier = ScaleTier(str(shadow.scale_tier).lower())
                except ValueError:
                    tier = select_scale_tier(total_estimated_rows(metadata))
            else:
                tier = select_scale_tier(total_estimated_rows(metadata))
            seed_report = await ShadowSeeder().seed_rows_only(
                connection_url,
                metadata,
                tier,
                statement_timeout_ms=int(settings.shadow_seed_timeout_seconds * 1000),
            )
            rows_inserted = seed_report.rows_inserted
            seed_warnings = list(seed_report.warnings or [])
        await shadow_service.merge_timings(
            shadow.id,
            seed_ms=round((perf_counter() - t0) * 1000.0, 1),
        )
        return {
            "run_id": str(run_id),
            "shadow_id": str(shadow.id),
            "schemas_created": report.schemas_created,
            "tables_created": report.tables_created,
            "columns_created": report.columns_created,
            "indexes_created": report.indexes_created,
            "rows_inserted": rows_inserted,
            "warnings": list(report.warnings) + seed_warnings,
            "idempotent": False,
        }

    try:
        result = await with_session(runtime, _run)
    except LambdaValidationError:
        raise
    except Exception as exc:
        raise LambdaHandlerError(f"LoadSchema failed for run_id={run_id}") from exc

    logger.info(
        "LoadSchema completed",
        extra={
            "run_id": str(run_id),
            "tables_created": result.get("tables_created"),
            "rows_inserted": result.get("rows_inserted"),
        },
    )
    return result
