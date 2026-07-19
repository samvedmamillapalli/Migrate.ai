"""Bedrock recommendation path — separate call from prediction."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.policy.models import PolicyAnalysisResult
from app.prediction.bedrock_client import BedrockClient, extract_json_object
from app.prediction.memory import MemoryRetrievalResult
from app.prediction.models import AdjustedPrediction, RecommendationOutput
from app.prediction.prompts import RECOMMENDATION_PROMPT_VERSION, load_prompt
from app.schema_analysis.models import DatabaseMetadata
from app.shadow.models import ScaleTier

logger = get_logger(__name__)

_REPAIR_RETRY_COUNT = 0


class RecommendationValidationError(AppError):
    """Raised when recommendation output fails validation after one repair retry."""


def get_recommendation_repair_retry_count() -> int:
    return _REPAIR_RETRY_COUNT


class RecommendationEngine:
    """Separate Bedrock call with its own versioned prompt template."""

    def __init__(
        self,
        client: BedrockClient,
        *,
        model_id: str,
        prompt_version: str = RECOMMENDATION_PROMPT_VERSION,
    ) -> None:
        self._client = client
        self._model_id = model_id
        self._prompt_version = prompt_version
        self._system_prompt = load_prompt(prompt_version)

    @property
    def model_version_label(self) -> str:
        return f"bedrock:{self._model_id}|prompt:{self._prompt_version}"

    def recommend(
        self,
        *,
        migration_sql: str,
        snapshot: DatabaseMetadata | None,
        policy: PolicyAnalysisResult,
        memories: MemoryRetrievalResult,
        prediction: AdjustedPrediction,
        scale_tier: ScaleTier | str,
    ) -> RecommendationOutput:
        user_prompt = self._build_user_prompt(
            migration_sql=migration_sql,
            snapshot=snapshot,
            policy=policy,
            memories=memories,
            prediction=prediction,
            scale_tier=scale_tier,
        )
        raw_text = self._client.generate_json(
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            model_id=self._model_id,
        )
        parsed = self._parse_with_optional_repair(
            raw_text=raw_text,
            user_prompt=user_prompt,
        )
        return parsed.model_copy(
            update={
                "prompt_template_version": self._prompt_version,
                "model_version": self.model_version_label,
            }
        )

    def _parse_with_optional_repair(
        self,
        *,
        raw_text: str,
        user_prompt: str,
    ) -> RecommendationOutput:
        global _REPAIR_RETRY_COUNT
        try:
            return self._validate_text(raw_text)
        except (ValueError, ValidationError) as first_error:
            logger.warning(
                "Recommendation output failed validation; attempting one repair retry",
                extra={"error": str(first_error)},
            )
            _REPAIR_RETRY_COUNT += 1
            logger.info(
                "recommendation_repair_retry",
                extra={
                    "metric": "recommendation_repair_retry",
                    "count": _REPAIR_RETRY_COUNT,
                },
            )
            repair_prompt = (
                f"{user_prompt}\n\n"
                f"Your previous response failed validation:\n{first_error}\n\n"
                "Return ONLY a corrected JSON object matching the required schema."
            )
            repaired_text = self._client.generate_json(
                system_prompt=self._system_prompt,
                user_prompt=repair_prompt,
                model_id=self._model_id,
            )
            try:
                return self._validate_text(repaired_text)
            except (ValueError, ValidationError) as second_error:
                raise RecommendationValidationError(
                    "Recommendation model output failed validation twice. "
                    f"First error: {first_error}. Second error: {second_error}."
                ) from second_error

    @staticmethod
    def _validate_text(text: str) -> RecommendationOutput:
        data = extract_json_object(text)
        return RecommendationOutput.model_validate(data)

    def _build_user_prompt(
        self,
        *,
        migration_sql: str,
        snapshot: DatabaseMetadata | None,
        policy: PolicyAnalysisResult,
        memories: MemoryRetrievalResult,
        prediction: AdjustedPrediction,
        scale_tier: ScaleTier | str,
    ) -> str:
        tier = scale_tier.value if isinstance(scale_tier, ScaleTier) else scale_tier
        snapshot_payload: dict[str, Any] | None = None
        if snapshot is not None:
            snapshot_payload = snapshot.model_dump(mode="json", by_alias=True)

        payload = {
            "shadow_scale_tier": tier,
            "migration_sql": migration_sql,
            "schema_snapshot": snapshot_payload,
            "policy_analysis": policy.to_persistable(),
            "retrieved_memories": memories.to_prompt_context(),
            "validated_prediction": {
                "estimated_duration_seconds": prediction.estimated_duration_seconds,
                "estimated_storage_mb": prediction.estimated_storage_mb,
                "rollback_risk": prediction.rollback_risk.value,
                "confidence_score": prediction.confidence_score,
                "raw_confidence_score": prediction.raw_confidence_score,
                "risk_explanation": prediction.risk_explanation,
                "key_assumptions": prediction.key_assumptions,
                "uncertainty_notes": prediction.uncertainty_notes,
            },
        }
        return (
            "Produce a recommendation JSON object for this input:\n"
            f"{json.dumps(payload, indent=2, default=str)}"
        )
