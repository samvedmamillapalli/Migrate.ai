"""Pydantic schemas for grading.yaml and grade outputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DimensionBand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_abs_seconds: float | None = None
    max_abs_mb: float | None = None
    max_pct: float = Field(ge=0.0)


class TierBands(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration: DimensionBand
    storage: DimensionBand

    @field_validator("duration")
    @classmethod
    def duration_needs_abs(cls, value: DimensionBand) -> DimensionBand:
        if value.max_abs_seconds is None:
            raise ValueError("duration band requires max_abs_seconds")
        return value

    @field_validator("storage")
    @classmethod
    def storage_needs_abs(cls, value: DimensionBand) -> DimensionBand:
        if value.max_abs_mb is None:
            raise ValueError("storage band requires max_abs_mb")
        return value


class PctErrorMinActual(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_seconds: float = Field(gt=0.0)
    storage_mb: float = Field(gt=0.0)


class RollbackConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consistent_pairs: list[tuple[str, str]]


class RetrievalWeights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic_similarity: float = Field(ge=0.0)
    migration_type_match: float = Field(ge=0.0)
    scale_tier_proximity: float = Field(ge=0.0)
    schema_shape: float = Field(ge=0.0)
    risk_flag_overlap: float = Field(ge=0.0)


class SourceWeights(BaseModel):
    """Per-tier multiplier applied to final_score — docs/cross_customer.md §4."""

    model_config = ConfigDict(extra="forbid")

    owner: float = Field(ge=0.0, le=2.0)
    cross_customer: float = Field(ge=0.0, le=2.0)
    corpus: float = Field(ge=0.0, le=2.0)


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_pool_size: int = Field(ge=5, le=100)
    final_limit: int = Field(ge=1, le=20)
    weak_similarity_threshold: float = Field(ge=0.0, le=1.0)
    weights: RetrievalWeights
    adjacent_tiers: list[tuple[str, str]] = Field(default_factory=list)
    source_weights: SourceWeights


class GradingFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    pct_error_min_actual: PctErrorMinActual
    storage_unverifiable_floor_mb: float = Field(gt=0.0)
    error_bands: dict[str, TierBands]
    rollback: RollbackConfig
    retrieval: RetrievalConfig

    @field_validator("error_bands")
    @classmethod
    def require_known_tiers(cls, value: dict[str, TierBands]) -> dict[str, TierBands]:
        required = {"small", "medium", "large"}
        missing = required - set(value)
        if missing:
            raise ValueError(f"error_bands missing tiers: {sorted(missing)}")
        return value


class DimensionGrade(BaseModel):
    """Per-dimension grading detail stored on the grade row."""

    model_config = ConfigDict(frozen=True)

    name: str
    predicted: float | str | None = None
    actual: float | str | None = None
    abs_error: float | None = None
    pct_error: float | None = None
    within_band: bool | None = None
    unverifiable: bool = False
    notes: str | None = None


class NumericGradeResult(BaseModel):
    """Deterministic grade before prose generation."""

    model_config = ConfigDict(frozen=True)

    scale_tier: str
    timed_out: bool
    duration_abs_error_seconds: float | None
    duration_pct_error: float | None
    duration_within_band: bool | None
    duration_unverifiable: bool
    storage_abs_error_mb: float
    storage_pct_error: float | None
    storage_within_band: bool | None
    storage_unverifiable: bool
    rollback_predicted: str
    rollback_actual_class: str
    rollback_consistent: bool
    rollback_within_band: bool
    outcome_class: str
    high_risk_flags_present: bool
    adjusted_confidence: float
    scalar_accuracy_score: float
    dimension_details: dict[str, Any]
    any_miss: bool


class SurpriseLessonsOutput(BaseModel):
    """Strict schema for Bedrock surprise/lessons JSON."""

    model_config = ConfigDict(extra="forbid")

    surprise_notes: str | None = None
    lessons_learned: str = Field(min_length=1)


ProseStatus = Literal["ok", "skipped", "failed"]
