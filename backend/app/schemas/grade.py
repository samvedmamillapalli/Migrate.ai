"""Grade and memory API response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GradeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    migration_run_id: uuid.UUID
    scale_tier: str
    timed_out: bool
    duration_abs_error_seconds: float | None = None
    duration_pct_error: float | None = None
    duration_within_band: bool | None = None
    duration_unverifiable: bool
    storage_abs_error_mb: float
    storage_pct_error: float | None = None
    storage_within_band: bool
    rollback_predicted: str
    rollback_actual_class: str
    rollback_consistent: bool
    rollback_within_band: bool
    outcome_class: str
    high_risk_flags_present: bool
    adjusted_confidence: float
    scalar_accuracy_score: float
    dimension_details: dict[str, Any]
    surprise_notes: str | None = None
    lessons_learned: str
    prose_status: str
    prose_error: str | None = None
    created_at: datetime
    updated_at: datetime


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    migration_run_id: uuid.UUID
    owner_identity: str
    scale_tier: str
    migration_type: str
    migration_summary: str
    schema_summary: str
    lessons_learned: str
    surprise_notes: str | None = None
    embed_text: str
    embedding_status: str
    embedding_error: str | None = None
    embedding_model_id: str | None = None
    scalar_accuracy_score: float | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_memory(cls, memory: Any) -> MemoryResponse:
        grade = memory.grade_summary or {}
        return cls(
            id=memory.id,
            migration_run_id=memory.migration_run_id,
            owner_identity=memory.owner_identity,
            scale_tier=memory.scale_tier,
            migration_type=memory.migration_type,
            migration_summary=memory.migration_summary,
            schema_summary=memory.schema_summary,
            lessons_learned=memory.lessons_learned,
            surprise_notes=memory.surprise_notes,
            embed_text=memory.embed_text,
            embedding_status=memory.embedding_status,
            embedding_error=memory.embedding_error,
            embedding_model_id=memory.embedding_model_id,
            scalar_accuracy_score=grade.get("scalar_accuracy_score"),
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )


class RepairEmbeddingsRequest(BaseModel):
    memory_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    limit: int = Field(default=20, ge=1, le=100)
