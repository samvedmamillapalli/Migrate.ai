"""Cleanup Lambda — tear down shadow cluster and delete temporary secrets."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.database.models import ShadowClusterStatus
from app.lambdas.errors import LambdaHandlerError
from app.lambdas.helpers import parse_run_id, shadow_secret_name
from app.lambdas.runtime import (
    get_runtime,
    handler_correlation,
    run_async,
    with_session,
)
from app.repositories.shadow_cluster_repository import ShadowClusterRepository
from app.services.shadow_cluster_service import ShadowClusterService

logger = get_logger(__name__)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    with handler_correlation(event, context, function_name="cleanup"):
        return run_async(_handle(event))


async def _handle(event: dict[str, Any]) -> dict[str, Any]:
    run_id = parse_run_id(event)
    runtime = get_runtime()
    provider = runtime.create_provider()

    logger.info("Cleanup started")

    try:

        async def _run(session):
            shadow_service = ShadowClusterService(
                repository=ShadowClusterRepository(session),
                session=session,
            )
            shadow = await shadow_service.get_by_run(run_id)
            if shadow is None:
                logger.info("Cleanup: no shadow row; nothing to destroy")
                await _delete_secret(runtime, run_id)
                return {
                    "run_id": str(run_id),
                    "destroyed": True,
                    "status": "absent",
                    "idempotent": True,
                }

            if shadow.status == ShadowClusterStatus.DESTROYED:
                await _delete_secret(runtime, run_id)
                return {
                    "run_id": str(run_id),
                    "shadow_id": str(shadow.id),
                    "destroyed": True,
                    "status": shadow.status.value,
                    "idempotent": True,
                }

            if shadow.status != ShadowClusterStatus.DESTROYING:
                try:
                    await shadow_service.transition(
                        shadow.id,
                        ShadowClusterStatus.DESTROYING,
                    )
                except Exception:  # noqa: BLE001 - continue teardown anyway
                    logger.warning(
                        "Cleanup could not transition to destroying",
                        extra={
                            "shadow_id": str(shadow.id),
                            "status": shadow.status.value,
                        },
                    )

            try:
                destroyed = await provider.destroy(
                    cluster_id=shadow.cluster_id,
                    cluster_name=shadow.cluster_name,
                )
            except Exception:
                if runtime.observability is not None:
                    await runtime.observability.record_cleanup_failed(
                        run_id=str(run_id)
                    )
                raise

            try:
                await shadow_service.transition(
                    shadow.id,
                    ShadowClusterStatus.DESTROYED,
                )
                final_status = ShadowClusterStatus.DESTROYED.value
            except Exception:  # noqa: BLE001
                try:
                    await shadow_service.transition(
                        shadow.id,
                        ShadowClusterStatus.FAILED,
                    )
                    final_status = ShadowClusterStatus.FAILED.value
                except Exception:  # noqa: BLE001
                    final_status = shadow.status.value
                if runtime.observability is not None:
                    await runtime.observability.record_cleanup_failed(
                        run_id=str(run_id)
                    )

            await _delete_secret(runtime, run_id)
            return {
                "run_id": str(run_id),
                "shadow_id": str(shadow.id),
                "destroyed": bool(destroyed),
                "status": final_status,
                "idempotent": False,
            }

        try:
            result = await with_session(runtime, _run)
        except Exception as exc:
            if runtime.observability is not None:
                try:
                    await runtime.observability.record_cleanup_failed(
                        run_id=str(run_id)
                    )
                except Exception:  # noqa: BLE001
                    pass
            raise LambdaHandlerError(f"Cleanup failed for run_id={run_id}") from exc
    finally:
        await provider.aclose()

    logger.info(
        "Cleanup completed",
        extra={
            "destroyed": result.get("destroyed"),
            "status": result.get("status"),
        },
    )
    return result


async def _delete_secret(runtime, run_id) -> None:
    secret_id = shadow_secret_name(run_id)
    try:
        await runtime.secrets.delete(secret_id)
    except Exception:  # noqa: BLE001 - cleanup must continue
        logger.warning(
            "Cleanup could not delete shadow secret",
            extra={"secret_id": secret_id},
        )
