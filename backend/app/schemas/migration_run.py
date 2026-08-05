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
    workspace_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Optional workspace this run belongs to (docs/FUTURE_WORKSPACES_PLAN.md). "
            "Must belong to the same owner — discover then defaults its connection "
            "from the workspace's stored connection when the caller doesn't supply one."
        ),
    )
    run_kind: str = Field(
        default="standard",
        description=(
            "standard (default) | chaos (deliberate failure test) | "
            "debug (developer/demo tooling). Keeps chaos/debug runs out of "
            "the default Recent list and future accuracy queries."
        ),
    )

    @field_validator("run_kind")
    @classmethod
    def validate_run_kind(cls, value: str) -> str:
        normalized = (value or "standard").strip().lower() or "standard"
        if normalized not in {"standard", "chaos", "debug"}:
            raise ValueError("run_kind must be one of: standard, chaos, debug")
        return normalized

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
    run_kind: str = "standard"
    revises_run_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
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


def _confidence_score(explainability: Any) -> float | None:
    """Pull the adjusted confidence out of the explainability JSONB blob.

    Mirrors the frontend's ``map-run.ts:mapAssessment`` read path so the list
    and detail views never disagree about what "confidence" means.
    """
    if not isinstance(explainability, dict):
        return None
    confidence = explainability.get("confidence")
    if not isinstance(confidence, dict):
        return None
    raw = confidence.get("score")
    if raw is None:
        raw = confidence.get("confidence_score")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


class MigrationRunSummaryResponse(BaseModel):
    """List item without the large JSONB schema snapshot.

    Carries a flattened slice of the run's approval / grade / execution-result /
    shadow-cluster children so a history table can render risk, confidence,
    duration, approver, shadow outcome and graded state without N follow-up
    requests per row. Populated by :meth:`from_orm_run`; the children are
    batch-loaded via ``load_summary_children`` in the repository.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    migration_sql: str
    status: MigrationRunStatus
    created_at: datetime
    updated_at: datetime
    owner_identity: str = "anonymous"
    run_kind: str = "standard"
    revises_run_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
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

    # --- flattened child fields (None until the relevant stage has run) ---
    compatibility_risk: CompatibilityRisk | None = None
    confidence_score: float | None = None
    approval_decision: str | None = None
    approver_identity: str | None = None
    approved_at: datetime | None = None
    actual_duration_seconds: float | None = None
    actual_storage_mb: float | None = None
    execution_success: bool | None = None
    execution_timed_out: bool | None = None
    outcome_class: str | None = None
    scalar_accuracy_score: float | None = None
    is_graded: bool = False
    shadow_status: str | None = None
    shadow_provider: str | None = None

    @classmethod
    def from_orm_run(cls, run: Any) -> MigrationRunSummaryResponse:
        """Build a summary from a run whose summary children are loaded.

        Safe when the children were not eager-loaded *in an async session only
        if* the attributes are already populated — callers must pass
        ``load_summary_children=True``. Missing children simply leave the
        corresponding fields at ``None``.
        """
        approval = getattr(run, "approval", None)
        grade = getattr(run, "grade", None)
        execution = getattr(run, "execution_result", None)
        shadow = getattr(run, "shadow_cluster", None)

        def _enum_value(value: Any) -> Any:
            return value.value if hasattr(value, "value") else value

        return cls(
            id=run.id,
            migration_sql=run.migration_sql,
            status=run.status,
            created_at=run.created_at,
            updated_at=run.updated_at,
            owner_identity=run.owner_identity,
            run_kind=run.run_kind,
            revises_run_id=run.revises_run_id,
            workspace_id=run.workspace_id,
            schema_discovered_at=run.schema_discovered_at,
            schema_discovery_duration_ms=run.schema_discovery_duration_ms,
            schema_database_engine=run.schema_database_engine,
            schema_database_version=run.schema_database_version,
            schema_discovery_status=run.schema_discovery_status,
            sfn_execution_arn=run.sfn_execution_arn,
            workflow_status=run.workflow_status,
            workflow_started_at=run.workflow_started_at,
            workflow_finished_at=run.workflow_finished_at,
            policy_decision=run.policy_decision,
            requires_manual_review=run.requires_manual_review,
            prediction_scale_tier=run.prediction_scale_tier,
            compatibility_risk=run.compatibility_risk,
            confidence_score=_confidence_score(run.explainability),
            approval_decision=(
                _enum_value(approval.decision) if approval is not None else None
            ),
            approver_identity=(
                approval.approver_identity if approval is not None else None
            ),
            approved_at=approval.created_at if approval is not None else None,
            actual_duration_seconds=(
                execution.actual_duration_seconds if execution is not None else None
            ),
            actual_storage_mb=(
                execution.actual_storage_mb if execution is not None else None
            ),
            execution_success=execution.success if execution is not None else None,
            execution_timed_out=execution.timed_out if execution is not None else None,
            outcome_class=grade.outcome_class if grade is not None else None,
            scalar_accuracy_score=(
                grade.scalar_accuracy_score if grade is not None else None
            ),
            is_graded=grade is not None,
            shadow_status=(
                _enum_value(shadow.status) if shadow is not None else None
            ),
            shadow_provider=shadow.provider if shadow is not None else None,
        )

    @computed_field
    @property
    def has_schema_snapshot(self) -> bool:
        return self.schema_discovery_status == SchemaDiscoveryStatus.SUCCEEDED

    @computed_field
    @property
    def shadow_outcome(self) -> str | None:
        """pass | warn | fail — or None when no shadow execution happened.

        Derived only from measured facts: whether the shadow execution
        succeeded, whether it timed out, whether the cluster itself failed,
        and the grader's outcome_class. Never inferred from risk or confidence.
        """
        if (
            self.execution_success is None
            and self.shadow_status is None
            and self.outcome_class is None
        ):
            return None
        if (
            self.execution_success is False
            or self.execution_timed_out is True
            or self.shadow_status == "failed"
            or self.outcome_class in {"bad", "timeout"}
        ):
            return "fail"
        if self.outcome_class == "warned_ok":
            return "warn"
        if self.execution_success is True or self.outcome_class == "clean_ok":
            return "pass"
        return None

    @computed_field
    @property
    def is_terminal(self) -> bool:
        return self.status in {
            MigrationRunStatus.COMPLETED,
            MigrationRunStatus.FAILED,
        }

    @computed_field
    @property
    def sql_snippet(self) -> str:
        one = " ".join((self.migration_sql or "").split())
        return one if len(one) <= 96 else f"{one[:93]}..."


class MigrationRunListResponse(BaseModel):
    items: list[MigrationRunSummaryResponse]
    total: int
    limit: int
    offset: int
