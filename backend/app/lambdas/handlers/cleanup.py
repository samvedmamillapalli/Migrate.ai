"""Cleanup Lambda — hold the shadow cluster for inspection, then (later) tear
it down and delete temporary secrets.

Historically this destroyed the cluster immediately. It now starts a bounded
HOLD instead (see ShadowClusterStatus.HOLDING / settings.shadow_hold_minutes):
the cluster — and the before/after row-sample + schema-diff data already
captured during ExecuteMigration — stays inspectable for a few minutes rather
than vanishing the instant measurement finishes. Actual teardown then happens
one of two ways, both already-existing mechanisms with no new infra:
  1. The orphan sweeper (already scheduled, already generic over any active
     status past its expiry) reaps it once the hold window closes.
  2. A user ends the hold early via POST /runs/{id}/shadow-cluster/teardown-now.
"""

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
    settings = runtime.settings

    logger.info("Cleanup (hold) started")

    async def _run(session):
        shadow_service = ShadowClusterService(
            repository=ShadowClusterRepository(session),
            session=session,
        )
        shadow = await shadow_service.get_by_run(run_id)
        if shadow is None:
            logger.info("Cleanup: no shadow row; nothing to hold")
            return {
                "run_id": str(run_id),
                "destroyed": True,
                "status": "absent",
                "idempotent": True,
            }

        if shadow.status in (
            ShadowClusterStatus.DESTROYED,
            ShadowClusterStatus.DESTROYING,
            ShadowClusterStatus.HOLDING,
        ):
            # Already held, already being torn down, or already gone — a
            # user's "delete now" or the sweeper may have already won the
            # race. Idempotent no-op either way.
            return {
                "run_id": str(run_id),
                "shadow_id": str(shadow.id),
                "destroyed": shadow.status == ShadowClusterStatus.DESTROYED,
                "status": shadow.status.value,
                "idempotent": True,
            }

        updated = await shadow_service.start_hold(
            shadow.id, hold_minutes=settings.shadow_hold_minutes
        )
        return {
            "run_id": str(run_id),
            "shadow_id": str(shadow.id),
            "destroyed": False,
            "status": updated.status.value,
            "expires_at": updated.expires_at.isoformat() if updated.expires_at else None,
            "idempotent": False,
        }

    try:
        result = await with_session(runtime, _run)
    except Exception as exc:
        raise LambdaHandlerError(f"Cleanup (hold) failed for run_id={run_id}") from exc

    logger.info(
        "Cleanup (hold) completed",
        extra={"status": result.get("status"), "expires_at": result.get("expires_at")},
    )
    return result


async def delete_shadow_secret(runtime, run_id) -> None:
    """Shared with the teardown-now API route — called once the cluster is
    actually destroyed (hold-start no longer deletes the secret, since a
    live cluster held for inspection may still need it)."""
    secret_id = shadow_secret_name(run_id)
    try:
        await runtime.secrets.delete(secret_id)
    except Exception:  # noqa: BLE001 - cleanup must continue
        logger.warning(
            "Cleanup could not delete shadow secret",
            extra={"secret_id": secret_id},
        )
