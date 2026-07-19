"""Grade a completed shadow run, write memory, update recommendation learning."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.database.models import Grade, MigrationRun, MigrationRunStatus
from app.database.retry import with_txn_retry
from app.grading.engine import compute_numeric_grade
from app.grading.prose import generate_surprise_and_lessons
from app.memory.writer import MemoryWriteService
from app.prediction.bedrock_client import BedrockClient
from app.repositories.grade_repository import GradeRepository
from app.repositories.migration_run_repository import MigrationRunRepository

logger = get_logger(__name__)


def _has_high_risk_flags(run: MigrationRun) -> bool:
    for flag in run.risk_flags or []:
        if isinstance(flag, dict) and str(flag.get("severity", "")).lower() == "high":
            return True
    return False


def _compute_recommendation_success(
    *,
    original: MigrationRun,
    revised: MigrationRun,
    revised_grade: Grade,
) -> dict[str, Any]:
    """Deterministic linked-run recommendation success.

    Success only when linked evidence shows measurable improvement:
    revised executed successfully with better/equal scalar accuracy and
    non-worse outcome class than a failure/timeout.
    """
    original_decision = None
    if original.approval is not None:
        original_decision = (
            original.approval.decision.value
            if hasattr(original.approval.decision, "value")
            else str(original.approval.decision)
        )

    revised_ok = (
        revised.execution_result is not None
        and revised.execution_result.success
        and not revised.execution_result.timed_out
    )
    improved = revised_ok and revised_grade.scalar_accuracy_score >= 0.66
    # Prefer revised outcome not bad/timeout
    if revised_grade.outcome_class in {"bad", "timeout"}:
        improved = False

    return {
        "status": "success" if improved else "no_improvement",
        "linked_revised_run_id": str(revised.id),
        "original_approval_decision": original_decision,
        "revised_scalar_accuracy_score": revised_grade.scalar_accuracy_score,
        "revised_outcome_class": revised_grade.outcome_class,
        "evidence": (
            "Linked revised run completed successfully with acceptable accuracy"
            if improved
            else "Linked revised run did not show measurable improvement"
        ),
    }


class GradingPipelineService:
    """Orchestrates grade → memory write after execution results exist."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        migration_run_repository: MigrationRunRepository,
        grade_repository: GradeRepository,
        memory_write_service: MemoryWriteService,
        bedrock_client: BedrockClient | None = None,
        prose_model_id: str | None = None,
    ) -> None:
        self._session = session
        self._runs = migration_run_repository
        self._grades = grade_repository
        self._memory = memory_write_service
        self._bedrock = bedrock_client
        self._prose_model_id = prose_model_id or "mock-model"

    async def grade_run(self, run_id: uuid.UUID) -> MigrationRun:
        """Grade prediction vs actuals, write memory, update linked recommendation."""
        run = await self._runs.get_by_id_or_raise(run_id, load_children=True)

        if run.prediction is None:
            raise ValidationError(
                f"MigrationRun {run_id} has no prediction to grade against"
            )
        if run.execution_result is None:
            raise ValidationError(
                f"MigrationRun {run_id} has no execution result; persist results first"
            )
        if run.status not in {
            MigrationRunStatus.COMPLETED,
            MigrationRunStatus.FAILED,
            MigrationRunStatus.RUNNING,
        }:
            # Allow grading once execution exists even if status still running
            # (persist_results may grade before status flip). Prefer completed/failed.
            pass

        existing = await self._grades.get_by_migration_run_id(run_id)
        # Idempotent: re-grade updates the existing grade + memory (persist retries).
        _ = existing

        scale_tier = run.prediction_scale_tier or "medium"
        if run.shadow_cluster is not None and getattr(
            run.shadow_cluster, "scale_tier", None
        ):
            scale_tier = run.shadow_cluster.scale_tier

        numeric = compute_numeric_grade(
            prediction=run.prediction,
            execution=run.execution_result,
            scale_tier=str(scale_tier),
            high_risk_flags_present=_has_high_risk_flags(run),
        )
        prose = generate_surprise_and_lessons(
            self._bedrock,
            model_id=self._prose_model_id,
            numeric=numeric,
            migration_sql=run.migration_sql,
            risk_explanation=run.prediction.reasoning,
        )

        async def _commit_grade() -> Grade:
            current = await self._runs.get_by_id_or_raise(run_id, load_children=True)
            grade_entity = await self._grades.get_by_migration_run_id(run_id)
            fields = dict(
                scale_tier=numeric.scale_tier,
                timed_out=numeric.timed_out,
                duration_abs_error_seconds=numeric.duration_abs_error_seconds,
                duration_pct_error=numeric.duration_pct_error,
                duration_within_band=numeric.duration_within_band,
                duration_unverifiable=numeric.duration_unverifiable,
                storage_abs_error_mb=numeric.storage_abs_error_mb,
                storage_pct_error=numeric.storage_pct_error,
                storage_within_band=numeric.storage_within_band,
                rollback_predicted=numeric.rollback_predicted,
                rollback_actual_class=numeric.rollback_actual_class,
                rollback_consistent=numeric.rollback_consistent,
                rollback_within_band=numeric.rollback_within_band,
                outcome_class=numeric.outcome_class,
                high_risk_flags_present=numeric.high_risk_flags_present,
                adjusted_confidence=numeric.adjusted_confidence,
                scalar_accuracy_score=numeric.scalar_accuracy_score,
                dimension_details=numeric.dimension_details,
                surprise_notes=prose.surprise_notes,
                lessons_learned=prose.lessons_learned,
                prose_status=prose.prose_status,
                prose_error=prose.prose_error,
            )
            if grade_entity is None:
                grade_entity = Grade(migration_run_id=current.id, **fields)
                grade_entity = await self._grades.create(grade_entity)
            else:
                for key, value in fields.items():
                    setattr(grade_entity, key, value)
                grade_entity = await self._grades.update(grade_entity)
            await self._session.commit()
            await self._session.refresh(grade_entity)
            return grade_entity

        grade = await with_txn_retry(_commit_grade, on_retry=self._session.rollback)

        # Reload for memory write with relationships.
        run = await self._runs.get_by_id_or_raise(run_id, load_children=True)
        assert run.prediction is not None
        assert run.execution_result is not None
        await self._memory.write_memory(
            run=run,
            prediction=run.prediction,
            execution=run.execution_result,
            grade=grade,
        )

        await self._update_linked_recommendation(run, grade)

        # Dual vantage: SQL metrics API + CloudWatch custom metrics.
        try:
            from app.memory.metrics import (
                fetch_accuracy_metrics,
                publish_metrics_to_cloudwatch,
            )

            metrics = await fetch_accuracy_metrics(self._session)
            observability = None
            try:
                from app.aws import AwsClientFactory, get_aws_settings
                from app.aws.observability import CloudWatchObservability

                aws = get_aws_settings()
                if aws.aws_enabled:
                    factory = AwsClientFactory(aws)
                    observability = CloudWatchObservability(factory, aws)
            except Exception:  # noqa: BLE001
                observability = None
            await publish_metrics_to_cloudwatch(metrics, observability)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Accuracy metrics publish skipped",
                extra={"run_id": str(run_id)},
                exc_info=True,
            )

        logger.info(
            "Graded migration run",
            extra={
                "run_id": str(run_id),
                "scalar_accuracy_score": grade.scalar_accuracy_score,
                "timed_out": grade.timed_out,
                "prose_status": grade.prose_status,
            },
        )
        return await self._runs.get_by_id_or_raise(run_id, load_children=True)

    async def _update_linked_recommendation(
        self,
        revised: MigrationRun,
        revised_grade: Grade,
    ) -> None:
        if revised.revises_run_id is None:
            return
        try:
            original = await self._runs.get_by_id_or_raise(
                revised.revises_run_id,
                load_children=True,
            )
        except NotFoundError:
            logger.warning(
                "revises_run_id not found; skipping recommendation learning",
                extra={
                    "run_id": str(revised.id),
                    "revises_run_id": str(revised.revises_run_id),
                },
            )
            return

        decision = None
        if original.approval is not None:
            decision = (
                original.approval.decision.value
                if hasattr(original.approval.decision, "value")
                else str(original.approval.decision)
            )

        outcome = {
            "acceptance": decision or "unknown",
            "linked_evidence": _compute_recommendation_success(
                original=original,
                revised=revised,
                revised_grade=revised_grade,
            ),
        }
        # Only claim success from linked evidence (never from acceptance alone).
        if decision == "accept_recommended" and "linked_evidence" not in outcome:
            outcome["success_claim"] = "accepted_outcome_unknown"

        async def _commit() -> None:
            orig = await self._runs.get_by_id_or_raise(original.id)
            orig.recommendation_outcome = outcome
            await self._runs.update(orig)
            await self._session.commit()

        await with_txn_retry(_commit, on_retry=self._session.rollback)
        logger.info(
            "Updated recommendation outcome from linked revised run",
            extra={
                "original_run_id": str(original.id),
                "revised_run_id": str(revised.id),
                "status": outcome["linked_evidence"]["status"],
            },
        )
