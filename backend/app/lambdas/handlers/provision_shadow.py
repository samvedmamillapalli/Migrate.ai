"""ProvisionShadowCluster Lambda — admit, create, ready, store shadow secret."""

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
from app.shadow.concurrency import acquire_slot
from app.shadow.models import ProvisionSpec, select_scale_tier

logger = get_logger(__name__)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    from app.lambdas.runtime import handler_correlation

    with handler_correlation(event, context, function_name="provision-shadow-cluster"):
        return run_async(_handle(event))


def _cluster_name(app_tag: str, run_id) -> str:
    return f"{app_tag}-{run_id.hex[:12]}"


async def _handle(event: dict[str, Any]) -> dict[str, Any]:
    run_id = parse_run_id(event)
    runtime = get_runtime()
    settings = runtime.settings

    logger.info("ProvisionShadowCluster started", extra={"run_id": str(run_id)})

    provider = runtime.create_provider()
    try:

        async def _run(session):
            run_repo = MigrationRunRepository(session)
            shadow_repo = ShadowClusterRepository(session)
            shadow_service = ShadowClusterService(repository=shadow_repo, session=session)

            run = await run_repo.get_by_id_or_raise(run_id)
            if not run.schema_snapshot:
                raise LambdaValidationError(
                    "schema_snapshot is required before provisioning"
                )
            metadata = DatabaseMetadata.model_validate(run.schema_snapshot)
            tier = select_scale_tier(total_estimated_rows(metadata))

            existing = await shadow_service.get_by_run(run_id)
            if existing is not None and existing.status in {
                ShadowClusterStatus.READY,
                ShadowClusterStatus.SEEDING,
                ShadowClusterStatus.MIGRATING,
            }:
                secret_id = shadow_secret_name(run_id)
                # Secret should already exist from the first successful provision.
                logger.info(
                    "ProvisionShadowCluster idempotent skip",
                    extra={
                        "run_id": str(run_id),
                        "shadow_id": str(existing.id),
                        "status": existing.status.value,
                    },
                )
                return {
                    "run_id": str(run_id),
                    "shadow_id": str(existing.id),
                    "cluster_id": existing.cluster_id,
                    "cluster_name": existing.cluster_name,
                    "scale_tier": existing.scale_tier,
                    "shadow_secret_arn": secret_id,
                    "status": existing.status.value,
                    "idempotent": True,
                }

            t0 = perf_counter()
            shadow = await acquire_slot(
                shadow_service,
                run_id=run_id,
                region=settings.shadow_cluster_region,
                provider=provider.name,
                scale_tier=tier.value,
                max_concurrent=settings.shadow_max_concurrent,
                max_lifetime_minutes=settings.shadow_max_lifetime_minutes,
                wait_timeout_seconds=settings.shadow_slot_wait_timeout_seconds,
                poll_interval_seconds=settings.shadow_slot_poll_interval_seconds,
            )

            if (
                shadow.cluster_id
                and shadow.status == ShadowClusterStatus.PROVISIONING
            ):
                # Partial retry: identity already set; resume ready + secret.
                pass

            spec = ProvisionSpec(
                run_id=run_id,
                cluster_name=_cluster_name(settings.shadow_app_tag, run_id),
                app_tag=settings.shadow_app_tag,
                cloud=settings.shadow_cluster_cloud,
                region=settings.shadow_cluster_region,
            )

            t_create = perf_counter()
            if not shadow.cluster_id:
                provisioned = await provider.create(spec)
                await shadow_service.set_identity(
                    shadow.id,
                    cluster_id=provisioned.cluster_id,
                    cluster_name=provisioned.cluster_name,
                )
            else:
                # Rebuild handle for resume; connection comes from provider create
                # only once — for resume we require the secret to already exist.
                from app.shadow.models import ProvisionedCluster

                try:
                    connection_url = await runtime.secrets.get_string(
                        shadow_secret_name(run_id)
                    )
                except Exception:
                    # Recreate if secret missing.
                    provisioned = await provider.create(spec)
                    await shadow_service.set_identity(
                        shadow.id,
                        cluster_id=provisioned.cluster_id,
                        cluster_name=provisioned.cluster_name,
                    )
                else:
                    provisioned = ProvisionedCluster(
                        cluster_id=shadow.cluster_id,
                        cluster_name=shadow.cluster_name or shadow.cluster_id,
                        region=shadow.region,
                        connection_url=connection_url,
                    )
            provision_ms = (perf_counter() - t_create) * 1000.0

            t_ready = perf_counter()
            await provider.await_ready(
                provisioned,
                timeout_seconds=settings.shadow_provision_timeout_seconds,
                poll_interval_seconds=settings.shadow_ready_poll_interval_seconds,
            )
            connection_url = await provider.provision_sql_access(provisioned)
            provisioned.attach_connection_url(connection_url)
            ready_ms = (perf_counter() - t_ready) * 1000.0

            secret_arn = await runtime.secrets.put_string(
                shadow_secret_name(run_id),
                connection_url,
            )

            if shadow.status == ShadowClusterStatus.PROVISIONING:
                shadow = await shadow_service.transition(
                    shadow.id,
                    ShadowClusterStatus.READY,
                )

            # Include slot-wait in provision_ms when admission was slow.
            admit_ms = (t_create - t0) * 1000.0
            await shadow_service.merge_timings(
                shadow.id,
                provision_ms=round(provision_ms + max(admit_ms, 0.0), 1),
                ready_ms=round(ready_ms, 1),
            )

            return {
                "run_id": str(run_id),
                "shadow_id": str(shadow.id),
                "cluster_id": shadow.cluster_id,
                "cluster_name": shadow.cluster_name,
                "scale_tier": tier.value,
                "shadow_secret_arn": secret_arn,
                "status": shadow.status.value,
                "idempotent": False,
            }

        try:
            result = await with_session(runtime, _run)
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            # Never echo Authorization headers / tokens if present in nested text.
            if "Bearer " in detail:
                detail = exc.__class__.__name__
            raise LambdaHandlerError(
                f"Shadow provisioning failed for run_id={run_id}: {detail}"
            ) from exc
    finally:
        await provider.aclose()

    logger.info(
        "ProvisionShadowCluster completed",
        extra={
            "run_id": str(result.get("run_id")),
            "shadow_id": result.get("shadow_id"),
            "status": result.get("status"),
        },
    )
    return result
