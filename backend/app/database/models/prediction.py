from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, Float, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.migration_run import MigrationRun


class RollbackRisk(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Prediction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """AI prediction captured before shadow execution."""

    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint(
            "migration_run_id",
            name="uq_predictions_migration_run_id",
        ),
        Index("ix_predictions_rollback_risk", "rollback_risk"),
        Index("ix_predictions_created_at", "created_at"),
    )

    migration_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("migration_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    estimated_duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_storage_mb: Mapped[float] = mapped_column(Float, nullable=False)
    rollback_risk: Mapped[RollbackRisk] = mapped_column(
        Enum(
            RollbackRisk,
            name="rollback_risk",
            native_enum=False,
            length=16,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)

    migration_run: Mapped[MigrationRun] = relationship(
        "MigrationRun",
        back_populates="prediction",
    )

    def __repr__(self) -> str:
        return (
            f"Prediction(id={self.id!s}, migration_run_id={self.migration_run_id!s})"
        )
