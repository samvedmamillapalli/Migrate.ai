"""Agentic memory record with Titan embedding and VECTOR(1024) storage."""

from __future__ import annotations

import uuid
from typing import Any, TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.database.types import Vector

if TYPE_CHECKING:
    from app.database.models.migration_run import MigrationRun


class MigrationMemory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One graded run remembered for hybrid retrieval.

    ``embedding`` is a CockroachDB VECTOR(1024) column indexed by Distributed
    Vector Indexing. Retrieval skips rows where ``embedding_status`` is not
    ``ready``.
    """

    __tablename__ = "migration_memories"
    __table_args__ = (
        UniqueConstraint(
            "migration_run_id",
            name="uq_migration_memories_migration_run_id",
        ),
        Index("ix_migration_memories_owner_identity", "owner_identity"),
        Index("ix_migration_memories_scale_tier", "scale_tier"),
        Index("ix_migration_memories_migration_type", "migration_type"),
        Index("ix_migration_memories_embedding_status", "embedding_status"),
        Index("ix_migration_memories_created_at", "created_at"),
    )

    migration_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("migration_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    scale_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    migration_type: Mapped[str] = mapped_column(String(64), nullable=False)

    migration_summary: Mapped[str] = mapped_column(Text, nullable=False)
    schema_summary: Mapped[str] = mapped_column(Text, nullable=False)
    risk_flags: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    prediction_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recommendation_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    approval_summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    execution_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    grade_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    lessons_learned: Mapped[str] = mapped_column(Text, nullable=False)
    surprise_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    embed_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[str | None] = mapped_column(Vector(1024), nullable=True)
    embedding_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    embedding_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    index_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    table_complexity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

    migration_run: Mapped[MigrationRun] = relationship(
        "MigrationRun",
        back_populates="memory",
    )

    def __repr__(self) -> str:
        return (
            "MigrationMemory("
            f"id={self.id!s}, migration_run_id={self.migration_run_id!s})"
        )
