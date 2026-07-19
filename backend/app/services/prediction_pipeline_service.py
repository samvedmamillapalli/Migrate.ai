"""Phase 9 prediction pipeline: policy → memory → predict → recommend → gate."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ValidationError
from app.core.logging import get_logger
from app.database.models import (
    CompatibilityRisk,
    MigrationRun,
    MigrationRunStatus,
    PolicyDecision,
    Prediction,
)
from app.database.retry import with_txn_retry
from app.policy.engine import PolicyEngine
from app.policy.models import PolicyAnalysisResult
from app.prediction.bedrock_client import BedrockClient
from app.prediction.memory import MemoryRetrieval, MemoryRetrievalResult, StubMemoryRetrieval
from app.prediction.models import AdjustedPrediction, ExplainabilityBundle, RecommendationOutput
from app.prediction.predictor import PredictionEngine, PredictionValidationError
from app.prediction.recommender import RecommendationEngine, RecommendationValidationError
from app.repositories.migration_run_repository import MigrationRunRepository
from app.repositories.prediction_repository import PredictionRepository
from app.schema_analysis.models import DatabaseMetadata
from app.services.migration_run_service import MigrationRunService
from app.shadow.models import ScaleTier, select_scale_tier
from app.memory.retrieval import HybridMemoryRetrieval
logger = get_logger(__name__)


class PredictionPipelineService:
    """Orchestrates Phase 9 analysis and stops at awaiting_approval.

    Durable verify starts after POST /approve with decision=proceed (or
    POST /closed-loop / start-workflow). WorkflowOrchestrationService refuses
    starts that skipped prediction + proceed approval.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        migration_run_repository: MigrationRunRepository,
        prediction_repository: PredictionRepository,
        migration_run_service: MigrationRunService,
        bedrock_client: BedrockClient,
        prediction_model_id: str,
        recommendation_model_id: str | None = None,
        memory_retrieval: MemoryRetrieval | None = None,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self._session = session
        self._runs = migration_run_repository
        self._predictions = prediction_repository
        self._run_service = migration_run_service
        self._bedrock = bedrock_client
        self._prediction_model_id = prediction_model_id
        self._recommendation_model_id = (
            recommendation_model_id or prediction_model_id
        )
        self._memory = memory_retrieval or StubMemoryRetrieval()
        self._policy_engine = policy_engine or PolicyEngine()

    async def run_prediction_pipeline(
        self,
        run_id: uuid.UUID,
        *,
        scale_tier: ScaleTier | str | None = None,
    ) -> MigrationRun:
        """Analyze a run and transition it to awaiting_approval.

        Valid starting statuses: pending (moves to predicting first) or
        predicting. Does not start shadow execution.
        """
        run = await self._runs.get_by_id_or_raise(run_id, load_children=True)

        if run.prediction is not None:
            raise ConflictError(
                f"MigrationRun {run_id} already has a prediction"
            )

        if run.status == MigrationRunStatus.PENDING:
            await self._run_service.update_status(
                run_id,
                MigrationRunStatus.PREDICTING,
            )
            run = await self._runs.get_by_id_or_raise(run_id, load_children=True)
        elif run.status != MigrationRunStatus.PREDICTING:
            raise ConflictError(
                f"Prediction pipeline requires status pending or predicting; "
                f"got '{run.status.value}'"
            )

        snapshot = self._load_snapshot(run)
        tier = self._resolve_scale_tier(scale_tier, snapshot)

        try:
            policy = self._policy_engine.analyze(run.migration_sql, snapshot)
            memory = self._memory
            query_index_count = None
            query_complexity = None
            if snapshot is not None:
                from app.memory.embed_text import summarize_schema

                _, query_index_count, query_complexity = summarize_schema(
                    snapshot.model_dump(mode="json")
                    if hasattr(snapshot, "model_dump")
                    else None
                )
            if isinstance(memory, HybridMemoryRetrieval):
                memory = memory.with_request_context(
                    owner_identity=run.owner_identity or "anonymous",
                    query_risk_flags=list(
                        f.model_dump(mode="json") for f in policy.risk_flags
                    ),
                    query_index_count=query_index_count,
                    query_table_complexity=query_complexity,
                )
            memories = await memory.retrieve(
                migration_sql=run.migration_sql,
                statement_types=policy.parsed_statement_types,
                scale_tier=tier.value if isinstance(tier, ScaleTier) else str(tier),
            )

            predictor = PredictionEngine(
                self._bedrock,
                model_id=self._prediction_model_id,
            )
            prediction = predictor.predict(
                migration_sql=run.migration_sql,
                snapshot=snapshot,
                policy=policy,
                memories=memories,
                scale_tier=tier,
            )

            recommendation: RecommendationOutput | None = None
            # Skip recommendation only when policy blocks AND user already cancelled.
            # In all other cases (including block awaiting decision), recommend.
            if not (
                policy.policy_decision.value == "block"
                and run.status == MigrationRunStatus.FAILED
            ):
                recommender = RecommendationEngine(
                    self._bedrock,
                    model_id=self._recommendation_model_id,
                )
                recommendation = recommender.recommend(
                    migration_sql=run.migration_sql,
                    snapshot=snapshot,
                    policy=policy,
                    memories=memories,
                    prediction=prediction,
                    scale_tier=tier,
                )

            explainability = self._build_explainability(
                policy=policy,
                prediction=prediction,
                recommendation=recommendation,
                memories=memories,
                scale_tier=tier,
            )

            persisted = await self._persist_success(
                run_id=run_id,
                policy=policy,
                prediction=prediction,
                recommendation=recommendation,
                explainability=explainability,
                scale_tier=tier,
            )
            return persisted

        except (PredictionValidationError, RecommendationValidationError) as exc:
            await self._fail_run(run_id, str(exc))
            raise
        except Exception as exc:
            await self._fail_run(run_id, f"Prediction pipeline failed: {exc}")
            raise

    async def _persist_success(
        self,
        *,
        run_id: uuid.UUID,
        policy: PolicyAnalysisResult,
        prediction: AdjustedPrediction,
        recommendation: RecommendationOutput | None,
        explainability: ExplainabilityBundle,
        scale_tier: ScaleTier | str,
    ) -> MigrationRun:
        tier_value = (
            scale_tier.value if isinstance(scale_tier, ScaleTier) else str(scale_tier)
        )

        async def _commit() -> MigrationRun:
            run = await self._runs.get_by_id_or_raise(run_id, load_children=True)
            self._run_service._validate_status_transition(  # noqa: SLF001
                run.status,
                MigrationRunStatus.AWAITING_APPROVAL,
            )

            run.risk_flags = [f.model_dump(mode="json") for f in policy.risk_flags]
            run.compatibility_risk = CompatibilityRisk(policy.compatibility_risk.value)
            run.requires_expand_contract = policy.requires_expand_contract
            run.requires_manual_review = policy.requires_manual_review
            run.policy_decision = PolicyDecision(policy.policy_decision.value)
            run.parsed_statement_types = list(policy.parsed_statement_types)
            run.recommendation = (
                recommendation.model_dump(mode="json") if recommendation else None
            )
            run.explainability = explainability.model_dump(mode="json")
            run.prediction_scale_tier = tier_value
            run.status = MigrationRunStatus.AWAITING_APPROVAL

            entity = Prediction(
                migration_run_id=run.id,
                estimated_duration_seconds=prediction.estimated_duration_seconds,
                estimated_storage_mb=prediction.estimated_storage_mb,
                rollback_risk=prediction.rollback_risk,
                confidence_score=prediction.confidence_score,
                raw_confidence_score=prediction.raw_confidence_score,
                confidence_adjustments=[
                    a.model_dump(mode="json")
                    for a in prediction.confidence_adjustments
                ],
                reasoning=prediction.risk_explanation,
                key_assumptions=list(prediction.key_assumptions),
                uncertainty_notes=list(prediction.uncertainty_notes),
                model_version=prediction.model_version,
                prompt_template_version=prediction.prompt_template_version,
            )
            await self._predictions.create(entity)
            await self._runs.update(run)
            await self._session.commit()
            return await self._runs.get_by_id_or_raise(run_id, load_children=True)

        updated = await with_txn_retry(_commit, on_retry=self._session.rollback)
        logger.info(
            "Prediction pipeline completed; awaiting approval",
            extra={
                "run_id": str(run_id),
                "policy_decision": policy.policy_decision.value,
                "confidence_score": prediction.confidence_score,
                "scale_tier": tier_value,
            },
        )
        return updated

    async def _fail_run(self, run_id: uuid.UUID, reason: str) -> None:
        logger.error(
            "Prediction pipeline failed",
            extra={"run_id": str(run_id), "reason": reason},
        )
        try:
            run = await self._runs.get_by_id_or_raise(run_id)
            if run.status == MigrationRunStatus.PREDICTING:
                await self._run_service.update_status(
                    run_id,
                    MigrationRunStatus.FAILED,
                )
        except Exception:
            logger.exception(
                "Failed to mark run failed after pipeline error",
                extra={"run_id": str(run_id)},
            )

    @staticmethod
    def _load_snapshot(run: MigrationRun) -> DatabaseMetadata | None:
        if not run.schema_snapshot:
            return None
        try:
            return DatabaseMetadata.model_validate(run.schema_snapshot)
        except Exception as exc:
            raise ValidationError(
                f"Stored schema_snapshot is invalid: {exc}"
            ) from exc

    @staticmethod
    def _resolve_scale_tier(
        explicit: ScaleTier | str | None,
        snapshot: DatabaseMetadata | None,
    ) -> ScaleTier:
        if explicit is not None:
            if isinstance(explicit, ScaleTier):
                return explicit
            return ScaleTier(explicit)
        total = 0
        any_known = False
        if snapshot is not None:
            for schema in snapshot.schemas:
                for table in schema.tables:
                    if table.estimated_row_count is not None:
                        total += table.estimated_row_count
                        any_known = True
        return select_scale_tier(total if any_known else None)

    @staticmethod
    def _build_explainability(
        *,
        policy: PolicyAnalysisResult,
        prediction: AdjustedPrediction,
        recommendation: RecommendationOutput | None,
        memories: MemoryRetrievalResult,
        scale_tier: ScaleTier | str,
    ) -> ExplainabilityBundle:
        tier = scale_tier.value if isinstance(scale_tier, ScaleTier) else str(scale_tier)
        return ExplainabilityBundle(
            policy={
                **policy.to_persistable(),
                "driving_findings": [
                    {
                        "rule_id": f.rule_id,
                        "objects": f.objects,
                        "severity": f.severity.value,
                        "policy_decision": f.policy_decision.value,
                        "explanation": f.explanation,
                    }
                    for f in policy.risk_flags
                ],
            },
            prediction={
                "estimated_duration_seconds": prediction.estimated_duration_seconds,
                "estimated_storage_mb": prediction.estimated_storage_mb,
                "rollback_risk": prediction.rollback_risk.value,
                "risk_explanation": prediction.risk_explanation,
                "key_assumptions": prediction.key_assumptions,
                "uncertainty_notes": prediction.uncertainty_notes,
                "model_version": prediction.model_version,
                "prompt_template_version": prediction.prompt_template_version,
                "shadow_scale_tier": tier,
                "prediction_target": "shadow_run_only",
                "repair_retried": prediction.repair_retried,
            },
            recommendation=(
                recommendation.model_dump(mode="json") if recommendation else None
            ),
            memory=memories.to_explainability(),
            confidence={
                "raw_confidence_score": prediction.raw_confidence_score,
                "confidence_score": prediction.confidence_score,
                "adjustments": [
                    a.model_dump(mode="json")
                    for a in prediction.confidence_adjustments
                ],
            },
        )
