"""CockroachDB Agent Skills Repo content, embedded for retrieval.

Skills are vendored from ``cockroachlabs/cockroachdb-skills`` (Apache-2.0,
``npx skills add cockroachlabs/cockroachdb-skills``) and embedded with the
same Titan pipeline as ``MigrationMemory``, so the prediction/recommendation
and blast-radius agents can retrieve Cockroach Labs' own documented
operational expertise via CockroachDB's Distributed Vector Index — not just
the model's parametric knowledge.
"""

from __future__ import annotations

from sqlalchemy import Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.database.types import Vector


class CockroachDBSkillDoc(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One SKILL.md from the CockroachDB Agent Skills Repo."""

    __tablename__ = "cockroachdb_skill_docs"
    __table_args__ = (
        UniqueConstraint("skill_slug", name="uq_cockroachdb_skill_docs_skill_slug"),
        Index("ix_cockroachdb_skill_docs_category", "category"),
        Index("ix_cockroachdb_skill_docs_embedding_status", "embedding_status"),
    )

    skill_slug: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)

    embedding: Mapped[str | None] = mapped_column(Vector(1024), nullable=True)
    embedding_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    embedding_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    def __repr__(self) -> str:
        return f"CockroachDBSkillDoc(id={self.id!s}, skill_slug={self.skill_slug!r})"
