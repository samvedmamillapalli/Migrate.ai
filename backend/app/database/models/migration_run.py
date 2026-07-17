from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import DateTime, Enum, Float, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.execution_result import ExecutionResult
    from app.database.models.learned_outcome import LearnedOutcome
    from app.database.models.prediction import Prediction
    from app.database.models.shadow_cluster import ShadowCluster


class MigrationRunStatus(str, enum.Enum):
    PENDING = "pending"
    PREDICTING = "predicting"
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


class MigrationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "migration_runs"
    __table_args__ = (
        Index("ix_migration_runs_status", "status"),
        Index("ix_migration_runs_created_at", "created_at"),
        Index("ix_migration_runs_schema_discovery_status", "schema_discovery_status"),
        Index("ix_migration_runs_workflow_status", "workflow_status"),
        Index(
            "ix_migration_runs_sfn_execution_arn",
            "sfn_execution_arn",
            unique=True,
        ),
    )

    migration_sql: Mapped[str] = mapped_column(Text, nullable=False)
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

    def __repr__(self) -> str:
        return f"MigrationRun(id={self.id!s}, status={self.status.value!r})"
