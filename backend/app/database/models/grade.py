"""Deterministic prediction grade for a completed shadow run."""

from __future__ import annotations

import uuid
from typing import Any, TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.migration_run import MigrationRun


class Grade(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Code-computed grade of a Prediction against ExecutionResult actuals."""

    __tablename__ = "grades"
    __table_args__ = (
        UniqueConstraint(
            "migration_run_id",
            name="uq_grades_migration_run_id",
        ),
        Index("ix_grades_scale_tier", "scale_tier"),
        Index("ix_grades_scalar_accuracy_score", "scalar_accuracy_score"),
        Index("ix_grades_created_at", "created_at"),
    )

    migration_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("migration_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    scale_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    timed_out: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    duration_abs_error_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_pct_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_within_band: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    duration_unverifiable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    storage_abs_error_mb: Mapped[float] = mapped_column(Float, nullable=False)
    storage_pct_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    storage_within_band: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    storage_unverifiable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    rollback_predicted: Mapped[str] = mapped_column(String(16), nullable=False)
    rollback_actual_class: Mapped[str] = mapped_column(String(16), nullable=False)
    rollback_consistent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rollback_within_band: Mapped[bool] = mapped_column(Boolean, nullable=False)

    outcome_class: Mapped[str] = mapped_column(String(32), nullable=False)
    high_risk_flags_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    adjusted_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    scalar_accuracy_score: Mapped[float] = mapped_column(Float, nullable=False)
    dimension_details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    surprise_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    lessons_learned: Mapped[str] = mapped_column(Text, nullable=False)
    prose_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ok",
        server_default="ok",
    )
    prose_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    migration_run: Mapped[MigrationRun] = relationship(
        "MigrationRun",
        back_populates="grade",
    )

    def __repr__(self) -> str:
        return f"Grade(id={self.id!s}, migration_run_id={self.migration_run_id!s})"
