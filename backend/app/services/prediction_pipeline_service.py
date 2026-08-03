"""Phase 9 prediction pipeline: policy → memory → predict → recommend → gate."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
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
from app.prediction.skills import SkillsRetrieval, SkillsRetrievalResult, StubSkillsRetrieval
from app.repositories.migration_run_repository import MigrationRunRepository
from app.repositories.prediction_repository import PredictionRepository
from app.schema_analysis.models import DatabaseMetadata
from app.services.migration_run_service import MigrationRunService
from app.services.pipeline_progress import set_progress
from app.services.slack_helpers import derive_migration_name
from app.services.slack_notification_service import SlackNotificationService
# clear_progress available for TTL cleanup if needed later.
from app.shadow.models import ScaleTier, select_scale_tier
from app.memory.retrieval import HybridMemoryRetrieval
logger = get_logger(__name__)


def _prog(run_id: uuid.UUID, stage: str, message: str, percent: int, detail: str | None = None) -> None:
    set_progress(run_id, stage=stage, message=message, percent=percent, detail=detail)


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
        skills_retrieval: SkillsRetrieval | None = None,
        policy_engine: PolicyEngine | None = None,
        slack_notifications: SlackNotificationService | None = None,
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
        self._skills = skills_retrieval or StubSkillsRetrieval()
        self._policy_engine = policy_engine or PolicyEngine()
        self._slack_notifications = slack_notifications

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
            _prog(run_id, "start", "Moving run to predicting…", 5)
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

        _prog(run_id, "schema", "Loading schema snapshot from the run…", 10)
        snapshot = self._load_snapshot(run)
        tier = self._resolve_scale_tier(scale_tier, snapshot)
        _prog(
            run_id,
            "schema",
            f"Schema ready · scale tier={tier.value if isinstance(tier, ScaleTier) else tier}",
            15,
            detail=("synthetic" if (run.schema_snapshot or {}).get("debug_synthetic") else "stored"),
        )

        try:
            _prog(run_id, "policy", "Running policy engine (sqlglot + rules)…", 20)
            policy = self._policy_engine.analyze(run.migration_sql, snapshot)
            _prog(
                run_id,
                "policy",
                f"Policy done · decision={policy.policy_decision.value} · "
                f"flags={len(policy.risk_flags)} · types={list(policy.parsed_statement_types)}",
                28,
            )

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

            _prog(
                run_id,
                "memory",
                "Retrieving similar past migrations (vector index)…",
                35,
            )
            memories = await memory.retrieve(
                migration_sql=run.migration_sql,
                statement_types=policy.parsed_statement_types,
                scale_tier=tier.value if isinstance(tier, ScaleTier) else str(tier),
            )
            _prog(
                run_id,
                "memory",
                f"Memory retrieval done · count={len(memories.memories)}",
                42,
            )

            predictor = PredictionEngine(
                self._bedrock,
                model_id=self._prediction_model_id,
            )
            _prog(
                run_id,
                "bedrock_predict",
                f"Calling AWS Bedrock for prediction ({self._prediction_model_id})…",
                48,
                detail="This is usually the slowest step (often 15–60s).",
            )
            prediction = await asyncio.to_thread(
                predictor.predict,
                migration_sql=run.migration_sql,
                snapshot=snapshot,
                policy=policy,
                memories=memories,
                scale_tier=tier,
            )
            _prog(
                run_id,
                "bedrock_predict",
                f"Prediction received · duration≈{prediction.estimated_duration_seconds}s · "
                f"risk={prediction.rollback_risk.value} · confidence={prediction.confidence_score}",
                68,
            )

            _prog(run_id, "confidence", "Applying confidence adjustments…", 72)
            if prediction.confidence_adjustments:
                for adj in prediction.confidence_adjustments:
                    code = getattr(adj, "reason_code", None) or getattr(adj, "reason", "")
                    _prog(
                        run_id,
                        "confidence",
                        f"Confidence adjust: {code}",
                        74,
                    )

            recommendation: RecommendationOutput | None = None
            recommender: RecommendationEngine | None = None
            skills: SkillsRetrievalResult = SkillsRetrievalResult(
                skills=[],
                query_summary="not attempted (run blocked before recommendation)",
                retrieval_attempted=False,
                retrieval_mode="skipped",
            )
            if not (
                policy.policy_decision.value == "block"
                and run.status == MigrationRunStatus.FAILED
            ):
                _prog(
                    run_id,
                    "skills",
                    "Consulting CockroachDB Agent Skills (vector index)…",
                    76,
                )
                skills = await self._skills.retrieve(
                    migration_sql=run.migration_sql,
                    risk_narrative=prediction.risk_explanation or "",
                    limit=3,
                )
                _prog(
                    run_id,
                    "skills",
                    f"Skills consulted · count={len(skills.skills)}",
                    77,
                )

                recommender = RecommendationEngine(
                    self._bedrock,
                    model_id=self._recommendation_model_id,
                )
                _prog(
                    run_id,
                    "bedrock_recommend",
                    f"Calling AWS Bedrock for recommendation ({self._recommendation_model_id})…",
                    78,
                    detail="Second Bedrock call — often another 20–60s.",
                )
                recommendation = await asyncio.to_thread(
                    recommender.recommend,
                    migration_sql=run.migration_sql,
                    snapshot=snapshot,
                    policy=policy,
                    memories=memories,
                    prediction=prediction,
                    scale_tier=tier,
                    skills=skills,
                )
                _prog(
                    run_id,
                    "bedrock_recommend",
                    f"Recommendation received · strategy={recommendation.recommended_strategy}",
                    92,
                )
            else:
                _prog(run_id, "bedrock_recommend", "Skipping recommendation (blocked run)", 90)

            _prog(run_id, "persist", "Saving prediction + explainability…", 96)
            explainability = self._build_explainability(
                policy=policy,
                prediction=prediction,
                recommendation=recommendation,
                memories=memories,
                skills=skills,
                scale_tier=tier,
                prediction_trace=predictor.last_trace,
                recommendation_trace=(
                    recommender.last_trace if recommender is not None else None
                ),
            )

            persisted = await self._persist_success(
                run_id=run_id,
                policy=policy,
                prediction=prediction,
                recommendation=recommendation,
                explainability=explainability,
                scale_tier=tier,
            )
            await self._notify_prediction_ready(persisted)
            _prog(run_id, "done", "Prediction pipeline complete — awaiting approval", 100)
            return persisted

        except (PredictionValidationError, RecommendationValidationError) as exc:
            _prog(run_id, "failed", f"Validation failed: {exc}", 100)
            await self._fail_run(run_id, str(exc))
            raise
        except Exception as exc:
            _prog(run_id, "failed", f"Pipeline failed: {exc}", 100)
            await self._fail_run(run_id, f"Prediction pipeline failed: {exc}")
            raise
        finally:
            # Keep last progress readable for a bit; UI polls until done.
            pass

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

    async def _notify_prediction_ready(self, run: MigrationRun) -> None:
        """Best-effort Slack notification after the prediction commits.

        Fires only after ``_persist_success`` has committed the prediction and
        the run is AWAITING_APPROVAL. Any Slack lookup, token-decryption,
        network, or API failure is logged and swallowed so notification
        issues never affect the pipeline caller.
        """
        if self._slack_notifications is None:
            return
        try:
            await self._slack_notifications.send_prediction_ready(
                owner_identity=run.owner_identity or "",
                # None lets SlackNotificationService resolve the channel
                # itself — the OAuth installer's DM first, falling back to
                # slack_default_channel only for pre-authed_user_id rows.
                channel=None,
                run_id=run.id,
                migration_name=derive_migration_name(run.migration_sql),
                status=MigrationRunStatus.AWAITING_APPROVAL.value,
                timestamp=datetime.now(UTC),
                description=(
                    "AI prediction and recommendation are ready for human "
                    "review. Approve to start the shadow migration."
                ),
            )
        except Exception:
            logger.warning(
                "Slack prediction_ready notification failed",
                extra={"run_id": str(run.id)},
                exc_info=True,
            )

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
        skills: SkillsRetrievalResult,
        scale_tier: ScaleTier | str,
        prediction_trace: dict[str, Any] | None = None,
        recommendation_trace: dict[str, Any] | None = None,
    ) -> ExplainabilityBundle:
        tier = scale_tier.value if isinstance(scale_tier, ScaleTier) else str(scale_tier)
        traces: dict[str, Any] = {}
        if prediction_trace:
            traces["prediction"] = prediction_trace
        if recommendation_trace:
            traces["recommendation"] = recommendation_trace
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
            cockroachdb_skills=skills.to_explainability(),
            confidence={
                "raw_confidence_score": prediction.raw_confidence_score,
                "confidence_score": prediction.confidence_score,
                "adjustments": [
                    a.model_dump(mode="json")
                    for a in prediction.confidence_adjustments
                ],
            },
            bedrock_traces=traces or None,
        )
