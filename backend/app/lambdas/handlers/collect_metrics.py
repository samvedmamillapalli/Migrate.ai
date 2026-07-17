"""CollectMetrics Lambda — normalize execution metrics from the migrate step."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.lambdas.errors import LambdaValidationError
from app.lambdas.helpers import parse_run_id
from app.lambdas.runtime import run_async

logger = get_logger(__name__)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    from app.lambdas.runtime import handler_correlation

    with handler_correlation(event, context, function_name="collect-metrics"):
        return run_async(_handle(event))


async def _handle(event: dict[str, Any]) -> dict[str, Any]:
    run_id = parse_run_id(event)
    execute = event.get("execute_migration") or event.get("metrics") or {}
    if not isinstance(execute, dict) or "success" not in execute:
        raise LambdaValidationError(
            "execute_migration result with success/duration/storage is required"
        )

    metrics = {
        "run_id": str(run_id),
        "success": bool(execute.get("success")),
        "duration_seconds": float(execute.get("duration_seconds") or 0.0),
        "storage_growth_mb": float(execute.get("storage_growth_mb") or 0.0),
        "rollback_required": bool(execute.get("rollback_required")),
        "error_message": execute.get("error_message"),
    }
    logger.info(
        "CollectMetrics completed",
        extra={
            "run_id": str(run_id),
            "success": metrics["success"],
            "duration_seconds": metrics["duration_seconds"],
        },
    )
    return metrics
