from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.migration_run import MigrationRun


class ExecutionResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Actual shadow-cluster execution outcome for a migration run."""

    __tablename__ = "execution_results"
    __table_args__ = (
        UniqueConstraint(
            "migration_run_id",
            name="uq_execution_results_migration_run_id",
        ),
        Index("ix_execution_results_success", "success"),
        Index("ix_execution_results_created_at", "created_at"),
    )

    migration_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("migration_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    success: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    actual_duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    actual_storage_mb: Mapped[float] = mapped_column(Float, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    rollback_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    # Timeout is graded as signal (duration unverifiable), not discarded.
    timed_out: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    migration_run: Mapped[MigrationRun] = relationship(
        "MigrationRun",
        back_populates="execution_result",
    )

    def __repr__(self) -> str:
        return (
            "ExecutionResult("
            f"id={self.id!s}, migration_run_id={self.migration_run_id!s})"
        )
