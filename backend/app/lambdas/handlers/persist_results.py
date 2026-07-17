"""PersistResults Lambda — write ExecutionResult via ExecutionService."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.lambdas.errors import LambdaHandlerError, LambdaValidationError
from app.lambdas.helpers import parse_run_id
from app.lambdas.runtime import (
    get_runtime,
    handler_correlation,
    run_async,
    with_session,
)
from app.repositories.execution_result_repository import ExecutionResultRepository
from app.services.execution_service import ExecutionService

logger = get_logger(__name__)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    with handler_correlation(event, context, function_name="persist-results"):
        return run_async(_handle(event))


def _extract_metrics(event: dict[str, Any]) -> dict[str, Any]:
    step_results = event.get("step_results")
    if isinstance(step_results, dict):
        collect = step_results.get("collect_metrics")
        if isinstance(collect, dict) and "success" in collect:
            return collect
        execute = step_results.get("execute_migration")
        if isinstance(execute, dict) and "success" in execute:
            return execute

    collect = event.get("collect_metrics")
    if isinstance(collect, dict) and "success" in collect:
        return collect
    execute = event.get("execute_migration")
    if isinstance(execute, dict) and "success" in execute:
        return execute
    raise LambdaValidationError("collect_metrics or execute_migration metrics required")


async def _handle(event: dict[str, Any]) -> dict[str, Any]:
    run_id = parse_run_id(event)
    metrics = _extract_metrics(event)
    runtime = get_runtime()

    logger.info("PersistResults started")

    async def _run(session):
        service = ExecutionService(
            repository=ExecutionResultRepository(session),
            session=session,
        )
        result = await service.record_execution(
            run_id,
            success=bool(metrics.get("success")),
            duration_seconds=float(metrics.get("duration_seconds") or 0.0),
            storage_mb=float(metrics.get("storage_growth_mb") or 0.0),
            rollback_required=bool(metrics.get("rollback_required")),
            error_message=metrics.get("error_message"),
        )
        report = {
            "run_id": str(run_id),
            "execution_result_id": str(result.id),
            "success": result.success,
            "duration_seconds": result.actual_duration_seconds,
            "storage_mb": result.actual_storage_mb,
            "rollback_required": result.rollback_required,
            "error_message": result.error_message,
        }
        artifact = None
        if runtime.artifacts is not None:
            artifact = await runtime.artifacts.put_execution_report(
                str(run_id),
                report,
            )
        return {
            **report,
            "execution_report_uri": artifact.get("uri") if artifact else None,
        }

    try:
        payload = await with_session(runtime, _run)
    except Exception as exc:
        raise LambdaHandlerError(f"PersistResults failed for run_id={run_id}") from exc

    logger.info(
        "PersistResults completed",
        extra={
            "success": payload.get("success"),
            "execution_result_id": payload.get("execution_result_id"),
        },
    )
    return payload
