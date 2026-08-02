"""Schemas for memory browser, shadow cluster, execution result, model traces."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

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


class MemorySearchRequest(BaseModel):
    """Free-text semantic search over graded memories."""

    query: str = Field(min_length=1, max_length=2000)
    scope: Literal["mine", "corpus", "all"] = "all"
    migration_type: str | None = None
    scale_tier: str | None = None
    min_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=10, ge=1, le=50)


class MemorySearchHit(BaseModel):
    """One ranked memory. Carries the same integrity markers as the browse and
    retrieval paths so a seeded open-source corpus entry can never be mistaken
    for a real graded run."""

    memory_id: uuid.UUID
    migration_run_id: uuid.UUID
    similarity_score: float
    owner_identity: str
    migration_type: str
    scale_tier: str
    migration_summary: str
    lessons_learned: str
    surprise_notes: str | None = None
    outcome_class: str | None = None
    execution_success: bool | None = None
    predicted_duration_seconds: float | None = None
    actual_duration_seconds: float | None = None
    predicted_storage_mb: float | None = None
    actual_storage_mb: float | None = None
    scalar_accuracy_score: float | None = None
    memory_origin: str | None = None
    not_a_graded_run: bool = False
    source_url: str | None = None
    ui_label: str | None = None
    created_at: datetime

    @classmethod
    def from_orm_memory(cls, memory: Any, similarity: float) -> MemorySearchHit:
        integrity = integrity_fields(memory.grade_summary)
        pred = memory.prediction_summary or {}
        exe = memory.execution_summary or {}
        grade = memory.grade_summary if isinstance(memory.grade_summary, dict) else {}
        return cls(
            memory_id=memory.id,
            migration_run_id=memory.migration_run_id,
            similarity_score=round(float(similarity), 6),
            owner_identity=memory.owner_identity,
            migration_type=memory.migration_type,
            scale_tier=memory.scale_tier,
            migration_summary=memory.migration_summary,
            lessons_learned=memory.lessons_learned,
            surprise_notes=memory.surprise_notes,
            outcome_class=grade.get("outcome_class"),
            execution_success=exe.get("success"),
            predicted_duration_seconds=pred.get("estimated_duration_seconds"),
            actual_duration_seconds=exe.get("actual_duration_seconds"),
            predicted_storage_mb=pred.get("estimated_storage_mb"),
            actual_storage_mb=exe.get("actual_storage_mb"),
            scalar_accuracy_score=integrity["scalar_accuracy_score"],
            memory_origin=integrity["integrity_kind"],
            not_a_graded_run=integrity["not_a_graded_run"],
            source_url=integrity["source_url"],
            ui_label=integrity["ui_label"],
            created_at=memory.created_at,
        )


class MemorySearchResponse(BaseModel):
    query: str
    scope: str
    embedding_model_id: str | None = None
    # Which CockroachDB vector index served this search, and how long it took.
    # Surfaced deliberately: it makes the distributed vector index visible in
    # the product rather than only claimed in a README. None means no query
    # ran at all (e.g. scope="mine" with no authenticated owner) — never a
    # name attached to a query that didn't execute.
    index_used: str | None
    took_ms: float
    total: int
    results: list[MemorySearchHit]


class CCloudAuditEventItem(BaseModel):
    """One CockroachDB Cloud audit-log entry fetched via the ccloud CLI —
    independent corroboration of the shadow cluster's lifecycle, sourced from
    the Cloud control plane's own audit log rather than anything the
    migration or the MCP investigation touches. See
    docs/cockroach_hookup.md §4 "Feature 1"."""

    model_config = ConfigDict(from_attributes=True)

    event_type: str
    actor: str | None = None
    occurred_at: datetime | None = None
    raw_payload: dict[str, Any]


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
    # ccloud CLI Feature 1 (docs/cockroach_hookup.md §4). Empty until the
    # workflow reaches a terminal state and the audit-trail fetch runs; stays
    # empty if ccloud isn't logged in on the backend host — never fails the
    # run either way.
    ccloud_audit_trail: list[CCloudAuditEventItem] = []

    @classmethod
    def from_orm(
        cls,
        row: Any,
        *,
        ccloud_audit_trail: list[Any] | None = None,
    ) -> ShadowClusterResponse:
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
            ccloud_audit_trail=[
                CCloudAuditEventItem.model_validate(e) for e in (ccloud_audit_trail or [])
            ],
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
    # Populated only for tool-use traces (kind="blast_radius_investigation"):
    # the real MCP tool calls made during this turn — {name, arguments,
    # result_text, is_error} — so a claim in the trace can be checked against
    # what the tool actually returned, not just the model's prose.
    tool_calls: list[dict[str, Any]] | None = None


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

