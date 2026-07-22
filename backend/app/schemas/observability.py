"""Schemas for memory browser, shadow cluster, execution result, model traces."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MemoryListItem(BaseModel):
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
    has_embedding: bool = False
    scalar_accuracy_score: float | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_memory(cls, memory: Any) -> MemoryListItem:
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
            has_embedding=memory.embedding is not None
            and memory.embedding_status == "ready",
            scalar_accuracy_score=grade.get("scalar_accuracy_score"),
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )


class MemoryListResponse(BaseModel):
    items: list[MemoryListItem]
    total: int
    limit: int
    offset: int
    health: dict[str, Any]


class ShadowClusterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    migration_run_id: uuid.UUID
    cluster_id: str | None = None
    cluster_name: str | None = None
    provider: str
    region: str
    status: str
    scale_tier: str | None = None
    expires_at: datetime | None = None
    stage_timings: dict[str, Any] | None = None
    error_message: str | None = None
    destroyed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm(cls, row: Any) -> ShadowClusterResponse:
        status = row.status.value if hasattr(row.status, "value") else str(row.status)
        return cls(
            id=row.id,
            migration_run_id=row.migration_run_id,
            cluster_id=row.cluster_id,
            cluster_name=row.cluster_name,
            provider=row.provider,
            region=row.region,
            status=status,
            scale_tier=row.scale_tier,
            expires_at=row.expires_at,
            stage_timings=row.stage_timings,
            error_message=row.error_message,
            destroyed_at=row.destroyed_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class ExecutionResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    migration_run_id: uuid.UUID
    success: bool
    actual_duration_seconds: float
    actual_storage_mb: float
    error_message: str | None = None
    rollback_required: bool
    timed_out: bool
    created_at: datetime
    updated_at: datetime


class ModelTraceAttempt(BaseModel):
    raw_response: str
    parsed: dict[str, Any] | None = None
    validation_error: str | None = None
    latency_ms: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class ModelTrace(BaseModel):
    kind: str = Field(description="prediction | recommendation | grade_prose")
    model_id: str
    prompt_template_version: str
    system_prompt: str
    user_prompt: str
    attempts: list[ModelTraceAttempt]
    repair_retried: bool = False
    final_parsed: dict[str, Any] | None = None
    latency_ms_total: float | None = None
