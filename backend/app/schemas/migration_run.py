from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.database.models import MigrationRunStatus, SchemaDiscoveryStatus, WorkflowStatus


class MigrationRunCreateRequest(BaseModel):
    migration_sql: str = Field(min_length=1, description="SQL migration to analyze")

    @field_validator("migration_sql")
    @classmethod
    def validate_migration_sql(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("migration_sql must not be empty")
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
    schema_snapshot: dict[str, Any] | None = None
    schema_discovered_at: datetime | None = None
    schema_discovery_duration_ms: float | None = None
    schema_database_engine: str | None = None
    schema_database_version: str | None = None
    schema_discovery_status: SchemaDiscoveryStatus | None = None
    sfn_execution_arn: str | None = None
    workflow_status: WorkflowStatus = WorkflowStatus.NOT_STARTED
    workflow_started_at: datetime | None = None
    workflow_finished_at: datetime | None = None


class MigrationRunSummaryResponse(BaseModel):
    """List item without the large JSONB schema snapshot."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    migration_sql: str
    status: MigrationRunStatus
    created_at: datetime
    updated_at: datetime
    schema_discovered_at: datetime | None = None
    schema_discovery_duration_ms: float | None = None
    schema_database_engine: str | None = None
    schema_database_version: str | None = None
    schema_discovery_status: SchemaDiscoveryStatus | None = None
    sfn_execution_arn: str | None = None
    workflow_status: WorkflowStatus = WorkflowStatus.NOT_STARTED
    workflow_started_at: datetime | None = None
    workflow_finished_at: datetime | None = None

    @computed_field
    @property
    def has_schema_snapshot(self) -> bool:
        return self.schema_discovery_status == SchemaDiscoveryStatus.SUCCEEDED


class MigrationRunListResponse(BaseModel):
    items: list[MigrationRunSummaryResponse]
    total: int
    limit: int
    offset: int
