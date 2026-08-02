"""Structured outputs for prediction, recommendation, confidence, explainability."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database.models import RollbackRisk


class ConfidenceAdjustment(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason_code: str
    reason: str
    amount: float = Field(gt=0.0, le=1.0)
    """Absolute reduction applied (always positive; confidence only decreases)."""


class ModelPredictionOutput(BaseModel):
    """Strict schema for Bedrock prediction JSON (before confidence adjustment)."""

    model_config = ConfigDict(extra="forbid")

    estimated_duration_seconds: float = Field(ge=0.0)
    estimated_storage_mb: float = Field(ge=0.0)
    rollback_risk: RollbackRisk
    confidence_score: float = Field(ge=0.0, le=1.0)
    risk_explanation: str = Field(min_length=1)
    key_assumptions: list[str] = Field(min_length=1)
    uncertainty_notes: list[str] = Field(min_length=1)

    @field_validator("key_assumptions", "uncertainty_notes", mode="before")
    @classmethod
    def coerce_string_lists(cls, value: object) -> object:
        # Smaller models (e.g. Haiku) sometimes emit a single string instead of
        # a JSON array; coerce so the pipeline still accepts valid content.
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        return value

    @field_validator("key_assumptions", "uncertainty_notes")
    @classmethod
    def non_empty_strings(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("list must contain at least one non-empty string")
        return cleaned

    @field_validator("risk_explanation")
    @classmethod
    def strip_explanation(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("risk_explanation must not be empty")
        return normalized


class AdjustedPrediction(BaseModel):
    """Validated model output plus hybrid confidence."""

    model_config = ConfigDict(frozen=True)

    estimated_duration_seconds: float
    estimated_storage_mb: float
    rollback_risk: RollbackRisk
    raw_confidence_score: float
    confidence_score: float
    confidence_adjustments: list[ConfidenceAdjustment]
    risk_explanation: str
    key_assumptions: list[str]
    uncertainty_notes: list[str]
    model_version: str
    prompt_template_version: str
    repair_retried: bool = False


class RecommendationOutput(BaseModel):
    """Strict schema for Bedrock recommendation JSON."""

    model_config = ConfigDict(extra="forbid")

    recommended_strategy: str = Field(min_length=1)
    rollout_steps: list[str] = Field(min_length=1)
    suggested_deployment_window: str = Field(min_length=1)
    rollback_guidance: str = Field(min_length=1)
    monitoring_checklist: list[str] = Field(min_length=1)
    safer_alternative_plan: str | None = None
    rationale: str = Field(min_length=1)
    prompt_template_version: str | None = None
    model_version: str | None = None

    @field_validator(
        "recommended_strategy",
        "suggested_deployment_window",
        "rollback_guidance",
        "rationale",
    )
    @classmethod
    def strip_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("rollout_steps", "monitoring_checklist", mode="before")
    @classmethod
    def coerce_string_lists(cls, value: object) -> object:
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        return value

    @field_validator("rollout_steps", "monitoring_checklist")
    @classmethod
    def non_empty_lists(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("list must contain at least one non-empty string")
        return cleaned


class ExplainabilityBundle(BaseModel):
    """Persisted explainability surface — no second model call required to render."""

    model_config = ConfigDict(frozen=True)

    policy: dict[str, Any]
    prediction: dict[str, Any]
    recommendation: dict[str, Any] | None
    memory: dict[str, Any]
    # CockroachDB Agent Skills consulted for the recommendation (RAG-style,
    # via the same Distributed Vector Index used for `memory`). Optional with
    # a default so older persisted runs deserialize without this key.
    cockroachdb_skills: dict[str, Any] | None = None
    confidence: dict[str, Any]
    # Phase 11: durable Bedrock I/O traces (prompt, raw, parsed, latency, tokens).
    bedrock_traces: dict[str, Any] | None = None
    framing_note: Literal[
        "Blast radius means backfill duration, storage growth, "
        "resource saturation, and rollback safety."
    ] = (
        "Blast radius means backfill duration, storage growth, "
        "resource saturation, and rollback safety."
    )
