"""Bedrock prediction path with strict validation and one repair retry."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.policy.models import PolicyAnalysisResult
from app.prediction.bedrock_client import BedrockClient, extract_json_object
from app.prediction.confidence import adjust_confidence
from app.prediction.memory import MemoryRetrievalResult
from app.prediction.models import AdjustedPrediction, ModelPredictionOutput
from app.prediction.prompts import PREDICTION_PROMPT_VERSION, load_prompt
from app.prediction.trace import build_trace, timed_generate
from app.schema_analysis.models import DatabaseMetadata
from app.shadow.models import ScaleTier

logger = get_logger(__name__)

# In-process counter so prompt drift / repair rate is visible without CloudWatch.
_REPAIR_RETRY_COUNT = 0


class PredictionValidationError(AppError):
    """Raised when model output fails validation after the bounded repair retry."""


def get_repair_retry_count() -> int:
    return _REPAIR_RETRY_COUNT


def reset_repair_retry_count() -> None:
    global _REPAIR_RETRY_COUNT
    _REPAIR_RETRY_COUNT = 0


class PredictionEngine:
    """One Bedrock call (+ optional single repair) → validated AdjustedPrediction."""

    def __init__(
        self,
        client: BedrockClient,
        *,
        model_id: str,
        prompt_version: str = PREDICTION_PROMPT_VERSION,
    ) -> None:
        self._client = client
        self._model_id = model_id
        self._prompt_version = prompt_version
        self._system_prompt = load_prompt(prompt_version)
        self.last_trace: dict[str, Any] | None = None

    @property
    def model_version_label(self) -> str:
        return f"bedrock:{self._model_id}|prompt:{self._prompt_version}"

    def predict(
        self,
        *,
        migration_sql: str,
        snapshot: DatabaseMetadata | None,
        policy: PolicyAnalysisResult,
        memories: MemoryRetrievalResult,
        scale_tier: ScaleTier | str,
    ) -> AdjustedPrediction:
        user_prompt = self._build_user_prompt(
            migration_sql=migration_sql,
            snapshot=snapshot,
            policy=policy,
            memories=memories,
            scale_tier=scale_tier,
        )

        raw_text, latency_ms, inp, out = timed_generate(
            self._client,
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            model_id=self._model_id,
        )
        attempts: list[dict[str, Any]] = [
            {
                "raw_response": raw_text,
                "parsed": None,
                "validation_error": None,
                "latency_ms": latency_ms,
                "input_tokens": inp,
                "output_tokens": out,
            }
        ]
        parsed, repair_retried = self._parse_with_optional_repair(
            raw_text=raw_text,
            user_prompt=user_prompt,
            attempts=attempts,
        )
        attempts[0]["parsed"] = parsed.model_dump(mode="json")

        snapshot_rows = _total_estimated_rows(snapshot)
        adjusted_score, adjustments = adjust_confidence(
            parsed.confidence_score,
            policy=policy,
            memories=memories,
            scale_tier=scale_tier,
            snapshot_total_rows=snapshot_rows,
            migration_sql=migration_sql,
        )

        uncertainty = list(parsed.uncertainty_notes)
        if memories.is_empty:
            note = (
                "No historical memories were retrieved; confidence was reduced "
                "for weak retrieval support."
            )
            if note not in uncertainty:
                uncertainty.append(note)

        result = AdjustedPrediction(
            estimated_duration_seconds=parsed.estimated_duration_seconds,
            estimated_storage_mb=parsed.estimated_storage_mb,
            rollback_risk=parsed.rollback_risk,
            raw_confidence_score=parsed.confidence_score,
            confidence_score=adjusted_score,
            confidence_adjustments=adjustments,
            risk_explanation=parsed.risk_explanation,
            key_assumptions=parsed.key_assumptions,
            uncertainty_notes=uncertainty,
            model_version=self.model_version_label,
            prompt_template_version=self._prompt_version,
            repair_retried=repair_retried,
        )
        self.last_trace = build_trace(
            kind="prediction",
            model_id=self._model_id,
            prompt_template_version=self._prompt_version,
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            attempts=attempts,
            repair_retried=repair_retried,
            final_parsed=parsed.model_dump(mode="json"),
        )
        return result

    def _parse_with_optional_repair(
        self,
        *,
        raw_text: str,
        user_prompt: str,
        attempts: list[dict[str, Any]],
    ) -> tuple[ModelPredictionOutput, bool]:
        global _REPAIR_RETRY_COUNT
        try:
            return self._validate_text(raw_text), False
        except (ValueError, ValidationError) as first_error:
            attempts[0]["validation_error"] = str(first_error)
            logger.warning(
                "Prediction output failed validation; attempting one repair retry",
                extra={"error": str(first_error)},
            )
            _REPAIR_RETRY_COUNT += 1
            logger.info(
                "prediction_repair_retry",
                extra={
                    "metric": "prediction_repair_retry",
                    "count": _REPAIR_RETRY_COUNT,
                },
            )
            repair_prompt = (
                f"{user_prompt}\n\n"
                f"Your previous response failed validation:\n{first_error}\n\n"
                "Return ONLY a corrected JSON object matching the required schema."
            )
            repaired_text, latency_ms, inp, out = timed_generate(
                self._client,
                system_prompt=self._system_prompt,
                user_prompt=repair_prompt,
                model_id=self._model_id,
            )
            repair_attempt: dict[str, Any] = {
                "raw_response": repaired_text,
                "parsed": None,
                "validation_error": None,
                "latency_ms": latency_ms,
                "input_tokens": inp,
                "output_tokens": out,
                "repair": True,
            }
            attempts.append(repair_attempt)
            try:
                parsed = self._validate_text(repaired_text)
                repair_attempt["parsed"] = parsed.model_dump(mode="json")
                return parsed, True
            except (ValueError, ValidationError) as second_error:
                repair_attempt["validation_error"] = str(second_error)
                raise PredictionValidationError(
                    "Prediction model output failed validation twice. "
                    f"First error: {first_error}. Second error: {second_error}. "
                    "No partial prediction will be persisted."
                ) from second_error

    @staticmethod
    def _validate_text(text: str) -> ModelPredictionOutput:
        data = extract_json_object(text)
        return ModelPredictionOutput.model_validate(data)

    def _build_user_prompt(
        self,
        *,
        migration_sql: str,
        snapshot: DatabaseMetadata | None,
        policy: PolicyAnalysisResult,
        memories: MemoryRetrievalResult,
        scale_tier: ScaleTier | str,
    ) -> str:
        tier = scale_tier.value if isinstance(scale_tier, ScaleTier) else scale_tier
        snapshot_payload: dict[str, Any] | None = None
        if snapshot is not None:
            snapshot_payload = snapshot.model_dump(mode="json", by_alias=True)

        payload = {
            "shadow_scale_tier": tier,
            "prediction_target": "shadow_run_only",
            "migration_sql": migration_sql,
            "schema_snapshot": snapshot_payload,
            "policy_analysis": policy.to_persistable(),
            "retrieved_memories": memories.to_prompt_context(),
            "memory_retrieval_empty": memories.is_empty,
        }
        return (
            "Produce a shadow-run prediction JSON object for this input:\n"
            f"{json.dumps(payload, indent=2, default=str)}"
        )


def _total_estimated_rows(snapshot: DatabaseMetadata | None) -> int | None:
    if snapshot is None:
        return None
    total = 0
    any_known = False
    for schema in snapshot.schemas:
        for table in schema.tables:
            if table.estimated_row_count is not None:
                total += table.estimated_row_count
                any_known = True
    return total if any_known else None
