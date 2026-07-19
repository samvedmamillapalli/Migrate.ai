from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.database.models import (
    CompatibilityRisk,
    MigrationRunStatus,
    PolicyDecision,
    SchemaDiscoveryStatus,
    WorkflowStatus,
)


class MigrationRunCreateRequest(BaseModel):
    migration_sql: str = Field(min_length=1, description="SQL migration to analyze")
    owner_identity: str = Field(
        default="anonymous",
        min_length=1,
        max_length=256,
        description="Soft owner identity (no real auth yet); scopes memory retrieval",
    )
    revises_run_id: uuid.UUID | None = Field(
        default=None,
        description="Optional link to an earlier run this migration revises",
    )

    @field_validator("migration_sql")
    @classmethod
    def validate_migration_sql(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("migration_sql must not be empty")
        return normalized

    @field_validator("owner_identity")
    @classmethod
    def validate_owner_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("owner_identity must not be empty")
        return normalized


class MigrationRunStatusUpdateRequest(BaseModel):
    status: MigrationRunStatus


class MigrationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    migration_sql: str
    status: MigrationRunStatus
    created_at: datetime
    updated_at: datetime
    owner_identity: str = "anonymous"
    revises_run_id: uuid.UUID | None = None
    schema_snapshot: dict[str, Any] | None = None
    schema_discovered_at: datetime | None = None
    schema_discovery_duration_ms: float | None = None
    schema_database_engine: str | None = None
    schema_database_version: str | None = None
    schema_discovery_status: SchemaDiscoveryStatus | None = None
    sfn_execution_arn: str | None = None
    connection_secret_arn: str | None = None
    workflow_status: WorkflowStatus = WorkflowStatus.NOT_STARTED
    workflow_started_at: datetime | None = None
    workflow_finished_at: datetime | None = None
    # Phase 9
    risk_flags: list[dict[str, Any]] | None = None
    compatibility_risk: CompatibilityRisk | None = None
    requires_expand_contract: bool | None = None
    requires_manual_review: bool | None = None
    policy_decision: PolicyDecision | None = None
    parsed_statement_types: list[str] | None = None
    recommendation: dict[str, Any] | None = None
    explainability: dict[str, Any] | None = None
    prediction_scale_tier: str | None = None
    # Phase 10
    recommendation_outcome: dict[str, Any] | None = None


class MigrationRunSummaryResponse(BaseModel):
    """List item without the large JSONB schema snapshot."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    migration_sql: str
    status: MigrationRunStatus
    created_at: datetime
    updated_at: datetime
    owner_identity: str = "anonymous"
    revises_run_id: uuid.UUID | None = None
    schema_discovered_at: datetime | None = None
    schema_discovery_duration_ms: float | None = None
    schema_database_engine: str | None = None
    schema_database_version: str | None = None
    schema_discovery_status: SchemaDiscoveryStatus | None = None
    sfn_execution_arn: str | None = None
    workflow_status: WorkflowStatus = WorkflowStatus.NOT_STARTED
    workflow_started_at: datetime | None = None
    workflow_finished_at: datetime | None = None
    policy_decision: PolicyDecision | None = None
    requires_manual_review: bool | None = None
    prediction_scale_tier: str | None = None

    @computed_field
    @property
    def has_schema_snapshot(self) -> bool:
        return self.schema_discovery_status == SchemaDiscoveryStatus.SUCCEEDED


class MigrationRunListResponse(BaseModel):
    items: list[MigrationRunSummaryResponse]
    total: int
    limit: int
    offset: int
