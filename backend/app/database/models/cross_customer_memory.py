"""Anonymized, opt-in, cross-tenant memory pool — docs/cross_customer.md.

Deliberately carries no ``owner_identity``, no org id, and no hashed or
pseudonymous identity of any kind. Every text/JSONB column here is populated
only from output that has already been through
``app.memory.cross_customer_anonymizer`` before a row is ever written — see
docs/cross_customer.md §1 and §3. A row cannot leak which account
contributed it, because that was never stored anywhere on this model, not
even encrypted — that absence is the actual privacy guarantee, not a policy
promise layered on top of identifying data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.database.types import Vector


class CrossCustomerMemory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One anonymized migration-shape pattern, possibly contributed by many
    accounts (see ``contributor_count`` and docs/cross_customer.md §7).

    ``shape_hash`` is UNIQUE (migration s2n0k7f1j9e0, added after an
    adversarial review found the original plain index let two concurrent
    promotions of the same shape both insert — see that migration's
    docstring). ``CrossCustomerMemoryRepository.upsert_by_shape_hash``
    depends on this constraint to detect the race and fall back to the
    increment path instead of leaving duplicate rows.
    """

    __tablename__ = "cross_customer_memories"
    __table_args__ = (
        UniqueConstraint(
            "shape_hash", name="uq_cross_customer_memories_shape_hash"
        ),
        Index("ix_cross_customer_memories_embedding_status", "embedding_status"),
    )

    shape_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    migration_type: Mapped[str] = mapped_column(String(64), nullable=False)
    scale_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    parsed_statement_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False)

    generalized_summary: Mapped[str] = mapped_column(Text, nullable=False)
    generalized_risk_narrative: Mapped[str] = mapped_column(Text, nullable=False)
    generalized_lessons_learned: Mapped[str] = mapped_column(Text, nullable=False)
    generalized_surprise_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sql_shape_template: Mapped[str] = mapped_column(Text, nullable=False)

    risk_flags: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    outcome_class: Mapped[str] = mapped_column(String(32), nullable=False)
    scalar_accuracy_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    embedding: Mapped[str | None] = mapped_column(Vector(1024), nullable=True)
    embedding_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    embedding_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    contributor_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    first_contributed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_contributed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            "CrossCustomerMemory("
            f"id={self.id!s}, shape_hash={self.shape_hash!r}, "
            f"contributor_count={self.contributor_count})"
        )
