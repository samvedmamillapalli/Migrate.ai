"""Schemas for memory browser, shadow cluster, execution result, model traces."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.grade import integrity_fields
from app.shadow.schema_snapshot import build_schema_diff


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
    not_a_graded_run: bool = False
    source_url: str | None = None
    ui_label: str | None = None
    integrity_kind: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_memory(cls, memory: Any) -> MemoryListItem:
        integrity = integrity_fields(memory.grade_summary)
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
            scalar_accuracy_score=integrity["scalar_accuracy_score"],
            not_a_graded_run=integrity["not_a_graded_run"],
            source_url=integrity["source_url"],
            ui_label=integrity["ui_label"],
            integrity_kind=integrity["integrity_kind"],
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
    # Append-only replay log — see app.database.models.shadow_cluster.event_log.
    event_log: list[dict[str, Any]] | None = None
    schema_snapshot_before: dict[str, Any] | None = None
    schema_snapshot_after: dict[str, Any] | None = None
    # Computed from the two snapshots above, not stored — see
    # app.shadow.schema_snapshot.build_schema_diff.
    schema_diff: dict[str, Any] | None = None
    # Real row sample (columns + up to 20 rows + total count) for the tables
    # the migration references. Shadow-tier synthetic data, never the
    # customer's rows — see app.shadow.schema_snapshot._capture_row_samples.
    row_sample_before: dict[str, Any] | None = None
    row_sample_after: dict[str, Any] | None = None

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
            event_log=row.event_log,
            schema_snapshot_before=row.schema_snapshot_before,
            schema_snapshot_after=row.schema_snapshot_after,
            schema_diff=build_schema_diff(
                row.schema_snapshot_before, row.schema_snapshot_after
            ),
            row_sample_before=row.row_sample_before,
            row_sample_after=row.row_sample_after,
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

