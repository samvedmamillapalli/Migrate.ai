from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database.models import ApprovalDecision


class ApprovalCreateRequest(BaseModel):
    decision: ApprovalDecision
    approver_identity: str = Field(min_length=1, max_length=256)
    override_rationale: str | None = None
    # Optional: Secrets Manager ARN / local secret name for customer DB.
    # Required for auto-start of verify workflow on proceed when not already
    # stored on the run from POST /discover.
    connection_secret_arn: str | None = None
    start_workflow: bool | None = Field(
        default=None,
        description="Override auto-start of SFN on proceed (default: server auto)",
    )

    @field_validator("approver_identity")
    @classmethod
    def strip_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("approver_identity must not be empty")
        return normalized

    @field_validator("override_rationale")
    @classmethod
    def strip_rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("connection_secret_arn")
    @classmethod
    def strip_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    migration_run_id: uuid.UUID
    approver_identity: str
    decision: ApprovalDecision
    override_rationale: str | None
    created_at: datetime
    updated_at: datetime


class PredictionSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    estimated_duration_seconds: float
    estimated_storage_mb: float
    rollback_risk: str
    confidence_score: float
    raw_confidence_score: float
    confidence_adjustments: list[dict[str, Any]]
    reasoning: str
    key_assumptions: list[str]
    uncertainty_notes: list[str]
    model_version: str
    prompt_template_version: str
