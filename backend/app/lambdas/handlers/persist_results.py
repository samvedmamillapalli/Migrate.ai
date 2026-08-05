"""PersistResults Lambda — write ExecutionResult, then grade + remember."""

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
from app.memory.embedding_client import AwsTitanEmbeddingClient, MockEmbeddingClient
from app.memory.writer import MemoryWriteService
from app.prediction.bedrock_client import AwsBedrockClient, MockBedrockClient
from app.repositories.cross_customer_memory_repository import (
    CrossCustomerMemoryRepository,
)
from app.repositories.execution_result_repository import ExecutionResultRepository
from app.repositories.grade_repository import GradeRepository
from app.repositories.memory_sharing_preference_repository import (
    MemorySharingPreferenceRepository,
)
from app.repositories.migration_memory_repository import MigrationMemoryRepository
from app.repositories.migration_run_repository import MigrationRunRepository
from app.services.cross_customer_promotion_service import CrossCustomerPromotionService
from app.services.execution_service import ExecutionService
from app.services.grading_pipeline_service import GradingPipelineService

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


def _build_grading_pipeline(session, runtime) -> GradingPipelineService:
    aws = runtime.aws_settings
    from app.config import get_settings

    env = get_settings().environment.strip().lower()
    allow_mock = env in {"development", "dev", "local", "test"}
    local_mode = __import__(
        "app.lambdas.runtime", fromlist=["is_local_mode"]
    ).is_local_mode()

    bedrock: Any
    embedding: Any
    try:
        if aws.bedrock_prediction_model_id:
            bedrock = AwsBedrockClient(settings=aws)
        elif allow_mock or local_mode:
            bedrock = MockBedrockClient()
        else:
            raise RuntimeError(
                "BEDROCK_PREDICTION_MODEL_ID is required for grading prose "
                f"in environment={env}"
            )
    except Exception as exc:  # noqa: BLE001
        if aws.bedrock_prediction_model_id and not allow_mock and not local_mode:
            raise RuntimeError(
                "Failed to construct AwsBedrockClient for grading; "
                "refusing MockBedrockClient outside local/dev"
            ) from exc
        if not allow_mock and not local_mode:
            raise
        bedrock = MockBedrockClient()

    try:
        if aws.aws_enabled and not local_mode:
            embedding = AwsTitanEmbeddingClient(settings=aws)
        elif allow_mock or local_mode:
            embedding = MockEmbeddingClient()
        else:
            raise RuntimeError(
                f"Live Titan embeddings required in environment={env}"
            )
    except Exception as exc:  # noqa: BLE001
        if not allow_mock and not local_mode:
            raise RuntimeError(
                "Failed to construct AwsTitanEmbeddingClient; "
                "refusing MockEmbeddingClient outside local/dev"
            ) from exc
        embedding = MockEmbeddingClient()

    # Automatic cross-customer promotion (docs/cross_customer.md §5) — same
    # service the control-plane's get_memory_write_service wires in
    # (app/dependencies.py), reused here so a real shadow-verified run
    # graded through Step Functions gets the same treatment as one graded
    # through the API. Reuses the bedrock/embedding clients already
    # resolved above rather than constructing a third set.
    cross_customer_promotion = CrossCustomerPromotionService(
        session=session,
        cross_customer_repository=CrossCustomerMemoryRepository(session),
        sharing_preference_repository=MemorySharingPreferenceRepository(session),
        bedrock_client=bedrock,
        bedrock_model_id=(
            aws.bedrock_recommendation_model_id
            or aws.bedrock_prediction_model_id
            or "mock-model"
        ),
        embedding_client=embedding,
        embedding_model_id=aws.bedrock_embedding_model_id,
    )

    return GradingPipelineService(
        session=session,
        migration_run_repository=MigrationRunRepository(session),
        grade_repository=GradeRepository(session),
        memory_write_service=MemoryWriteService(
            session=session,
            repository=MigrationMemoryRepository(session),
            embedding_client=embedding,
            embedding_model_id=aws.bedrock_embedding_model_id,
            cross_customer_promotion=cross_customer_promotion,
        ),
        bedrock_client=bedrock,
        prose_model_id=aws.bedrock_prediction_model_id or "mock-model",
    )


async def _handle(event: dict[str, Any]) -> dict[str, Any]:
    run_id = parse_run_id(event)
    metrics = _extract_metrics(event)
    runtime = get_runtime()

    logger.info("PersistResults started")

    async def _run(session):
        grading = _build_grading_pipeline(session, runtime)
        service = ExecutionService(
            repository=ExecutionResultRepository(session),
            session=session,
            grading_pipeline=grading,
        )
        result = await service.record_execution(
            run_id,
            success=bool(metrics.get("success")),
            duration_seconds=float(metrics.get("duration_seconds") or 0.0),
            storage_mb=float(metrics.get("storage_growth_mb") or 0.0),
            rollback_required=bool(metrics.get("rollback_required")),
            error_message=metrics.get("error_message"),
            timed_out=bool(metrics.get("timed_out")),
            grade=True,
        )
        report = {
            "run_id": str(run_id),
            "execution_result_id": str(result.id),
            "success": result.success,
            "duration_seconds": result.actual_duration_seconds,
            "storage_mb": result.actual_storage_mb,
            "rollback_required": result.rollback_required,
            "timed_out": result.timed_out,
            "error_message": result.error_message,
            "graded": True,
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
            "timed_out": payload.get("timed_out"),
        },
    )
    return payload
