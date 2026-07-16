from __future__ import annotations

import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, Index, Text
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


class MigrationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "migration_runs"
    __table_args__ = (
        Index("ix_migration_runs_status", "status"),
        Index("ix_migration_runs_created_at", "created_at"),
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
