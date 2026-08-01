from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.migration_run import MigrationRun


class ApprovalDecision(str, enum.Enum):
    """Human decision at the Phase 9 approval gate."""

    PROCEED = "proceed"
    ACCEPT_RECOMMENDED = "accept_recommended"
    CANCEL = "cancel"


class Approval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only audit record of a human approval decision.

    Approvals are never overwritten. A run should have at most one approval in
    normal flow; the unique constraint enforces that.
    """

    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint(
            "migration_run_id",
            name="uq_approvals_migration_run_id",
        ),
        Index("ix_approvals_decision", "decision"),
        Index("ix_approvals_created_at", "created_at"),
    )

    migration_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("migration_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    approver_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    decision: Mapped[ApprovalDecision] = mapped_column(
        Enum(
            ApprovalDecision,
            name="approval_decision",
            native_enum=False,
            length=32,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    override_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    migration_run: Mapped[MigrationRun] = relationship(
        "MigrationRun",
        back_populates="approval",
    )

    def __repr__(self) -> str:
        return (
            f"Approval(id={self.id!s}, migration_run_id={self.migration_run_id!s}, "
            f"decision={self.decision.value!r})"
        )
