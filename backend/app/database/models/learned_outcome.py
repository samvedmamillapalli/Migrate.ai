from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.migration_run import MigrationRun


class LearnedOutcome(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """DEPRECATED — superseded by Phase 10 ``Grade`` + ``MigrationMemory``.

    Retained only so existing Alembic history / tables do not break. There is
    **no write path**. New learning artifacts go to ``migration_memories``.
    Do not surface this model in product docs or demos.
    """

    __tablename__ = "learned_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "migration_run_id",
            name="uq_learned_outcomes_migration_run_id",
        ),
        Index("ix_learned_outcomes_created_at", "created_at"),
        Index("ix_learned_outcomes_embedding_id", "embedding_id"),
    )

    migration_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("migration_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    lessons_learned: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    migration_run: Mapped[MigrationRun] = relationship(
        "MigrationRun",
        back_populates="learned_outcome",
    )

    def __repr__(self) -> str:
        return (
            "LearnedOutcome("
            f"id={self.id!s}, migration_run_id={self.migration_run_id!s})"
        )
