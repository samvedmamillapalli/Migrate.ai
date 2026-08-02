"""cockroachdb_skill_docs

CockroachDB Agent Skills Repo integration. New table storing SKILL.md content
vendored from ``cockroachlabs/cockroachdb-skills`` (Apache-2.0), embedded via
the same Titan pipeline as ``migration_memories``, retrieved via CockroachDB's
Distributed Vector Index by both the prediction/recommendation prompts and the
blast-radius investigation agent — see docs/cockroach_hookup.md §5.

Same partial-index-with-predicate lesson as m8h4e1f7a596: the vector index
carries ``WHERE embedding_status = 'ready'`` as its predicate from the start,
not bolted on after discovering the query is ineligible.

Revision ID: n9i5f2a8g6b7
Revises: m8h4e1f7a596
Create Date: 2026-08-02 02:00:00.000000

CockroachDB commits DDL per statement, so each statement below stands alone
and is guarded by an existence check — a killed or partial run can be re-run
safely.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from alembic_helpers import Vector

revision: str = "n9i5f2a8g6b7"
down_revision: Union[str, Sequence[str], None] = "m8h4e1f7a596"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :t"
        ),
        {"t": name},
    ).first()
    return row is not None


def _index_exists(index: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = current_schema() AND indexname = :i"
        ),
        {"i": index},
    ).first()
    return row is not None


def upgrade() -> None:
    if not _table_exists("cockroachdb_skill_docs"):
        op.create_table(
            "cockroachdb_skill_docs",
            sa.Column(
                "id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("skill_slug", sa.String(length=128), nullable=False),
            sa.Column("category", sa.String(length=128), nullable=False),
            sa.Column("title", sa.String(length=256), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("source_url", sa.String(length=512), nullable=False),
            sa.Column("embedding", Vector(1024), nullable=True),
            sa.Column(
                "embedding_status",
                sa.String(length=32),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("embedding_error", sa.Text(), nullable=True),
            sa.Column("embedding_model_id", sa.String(length=256), nullable=True),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.UniqueConstraint(
                "skill_slug", name="uq_cockroachdb_skill_docs_skill_slug"
            ),
        )

    if not _index_exists("ix_cockroachdb_skill_docs_category"):
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cockroachdb_skill_docs_category "
            "ON cockroachdb_skill_docs (category)"
        )
    if not _index_exists("ix_cockroachdb_skill_docs_embedding_status"):
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cockroachdb_skill_docs_embedding_status "
            "ON cockroachdb_skill_docs (embedding_status)"
        )

    # Distributed Vector Index, partial from the start — no owner/tenant
    # prefix column needed, this table has no tenancy dimension.
    if not _index_exists("ix_skill_docs_embedding_ready"):
        op.execute(
            """
            CREATE VECTOR INDEX IF NOT EXISTS ix_skill_docs_embedding_ready
            ON cockroachdb_skill_docs (embedding vector_cosine_ops)
            WHERE embedding_status = 'ready'
            """
        )


def downgrade() -> None:
    if _table_exists("cockroachdb_skill_docs"):
        op.execute("DROP TABLE IF EXISTS cockroachdb_skill_docs CASCADE")
