from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, TYPE_CHECKING

import uuid

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.approval import Approval
    from app.database.models.execution_result import ExecutionResult
    from app.database.models.github_pull_request_link import GithubPullRequestLink
    from app.database.models.grade import Grade
    from app.database.models.learned_outcome import LearnedOutcome
    from app.database.models.migration_memory import MigrationMemory
    from app.database.models.prediction import Prediction
    from app.database.models.shadow_cluster import ShadowCluster
    from app.database.models.workspace import Workspace


class MigrationRunStatus(str, enum.Enum):
    PENDING = "pending"
    PREDICTING = "predicting"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SchemaDiscoveryStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"


class WorkflowStatus(str, enum.Enum):
    """Durable Step Functions execution status mirrored in CockroachDB."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ABORTED = "aborted"


class CompatibilityRisk(str, enum.Enum):
    """Whether the change breaks application code that has not been deployed yet."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PolicyDecision(str, enum.Enum):
    """Deterministic policy outcome. Authoritative over the model."""

    ALLOW = "allow"
    ALLOW_WITH_WARNING = "allow_with_warning"
    BLOCK = "block"


class MigrationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "migration_runs"
    __table_args__ = (
        Index("ix_migration_runs_status", "status"),
        Index("ix_migration_runs_created_at", "created_at"),
        Index("ix_migration_runs_schema_discovery_status", "schema_discovery_status"),
        Index("ix_migration_runs_workflow_status", "workflow_status"),
        Index("ix_migration_runs_policy_decision", "policy_decision"),
        Index(
            "ix_migration_runs_sfn_execution_arn",
            "sfn_execution_arn",
            unique=True,
        ),
        Index("ix_migration_runs_owner_identity", "owner_identity"),
        Index("ix_migration_runs_revises_run_id", "revises_run_id"),
        Index("ix_migration_runs_run_kind", "run_kind"),
        Index("ix_migration_runs_workspace_id", "workspace_id"),
    )

    migration_sql: Mapped[str] = mapped_column(Text, nullable=False)
    # Soft identity (mirrors Approval.approver_identity).
    owner_identity: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
        default="anonymous",
        server_default="anonymous",
    )
    # Optional: which workspace's target database this run belongs to.
    # Nullable — see docs/FUTURE_WORKSPACES_PLAN.md's migration path;
    # existing runs are backfilled to an implicit default workspace, but the
    # column itself stays nullable so a one-off run without a workspace is
    # still possible. SET NULL (not CASCADE) on workspace deletion: deleting
    # a workspace must never delete migration history.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    # "standard" | "chaos" | "debug". Lets the UI (and accuracy queries) tell a
    # real user migration apart from a deliberate chaos/failure test or a
    # developer debug-tools run, without guessing from SQL text or naming.
    run_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="standard",
        server_default="standard",
    )
    # Optional link: this run revises an earlier recommendation-driven change.
    revises_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("migration_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[MigrationRunStatus] = mapped_column(
        Enum(
            MigrationRunStatus,
            name="migration_run_status",
            native_enum=False,
            length=32,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=MigrationRunStatus.PENDING,
        server_default=MigrationRunStatus.PENDING.value,
    )

    # Schema discovery snapshot (customer DB metadata). Credentials are never stored.
    schema_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    schema_discovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    schema_discovery_duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    schema_database_engine: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_database_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_discovery_status: Mapped[SchemaDiscoveryStatus | None] = mapped_column(
        Enum(
            SchemaDiscoveryStatus,
            name="schema_discovery_status",
            native_enum=False,
            length=32,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=True,
    )

    # Phase 8B: durable Step Functions orchestration metadata (no credentials).
    sfn_execution_arn: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Secrets Manager ARN (or local secret name) for the customer DB connection.
    # Pointer only — never the password. Required to start the verify workflow.
    connection_secret_arn: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
    )
    workflow_status: Mapped[WorkflowStatus] = mapped_column(
        Enum(
            WorkflowStatus,
            name="workflow_status",
            native_enum=False,
            length=32,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=WorkflowStatus.NOT_STARTED,
        server_default=WorkflowStatus.NOT_STARTED.value,
    )
    workflow_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    workflow_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Phase 9: deterministic policy layer outputs (persisted with the run).
    risk_flags: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    compatibility_risk: Mapped[CompatibilityRisk | None] = mapped_column(
        Enum(
            CompatibilityRisk,
            name="compatibility_risk",
            native_enum=False,
            length=16,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=True,
    )
    requires_expand_contract: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    requires_manual_review: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    policy_decision: Mapped[PolicyDecision | None] = mapped_column(
        Enum(
            PolicyDecision,
            name="policy_decision",
            native_enum=False,
            length=32,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=True,
    )
    parsed_statement_types: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # Phase 9: recommendation + explainability (1:1 with the run).
    recommendation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    explainability: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Scale tier the prediction targeted (shadow context).
    prediction_scale_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Phase 10: recommendation learning outcome (linked revised runs only).
    recommendation_outcome: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    prediction: Mapped[Prediction | None] = relationship(
        "Prediction",
        back_populates="migration_run",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    execution_result: Mapped[ExecutionResult | None] = relationship(
        "ExecutionResult",
        back_populates="migration_run",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    learned_outcome: Mapped[LearnedOutcome | None] = relationship(
        "LearnedOutcome",
        back_populates="migration_run",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    shadow_cluster: Mapped[ShadowCluster | None] = relationship(
        "ShadowCluster",
        back_populates="migration_run",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    approval: Mapped[Approval | None] = relationship(
        "Approval",
        back_populates="migration_run",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    grade: Mapped[Grade | None] = relationship(
        "Grade",
        back_populates="migration_run",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    memory: Mapped[MigrationMemory | None] = relationship(
        "MigrationMemory",
        back_populates="migration_run",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    # No cascade, no back_populates: this run points AT a workspace, it is
    # not owned by it — deleting a workspace must never delete run history
    # (see workspace_id's ondelete="SET NULL" above).
    workspace: Mapped[Workspace | None] = relationship("Workspace", uselist=False)
    github_pr_link: Mapped[GithubPullRequestLink | None] = relationship(
        "GithubPullRequestLink",
        back_populates="migration_run",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"MigrationRun(id={self.id!s}, status={self.status.value!r})"
