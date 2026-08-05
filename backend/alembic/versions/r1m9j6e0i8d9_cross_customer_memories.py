"""cross_customer_memories

Phase 1 of docs/cross_customer.md — the anonymized, opt-in, cross-tenant
memory pool and its consent table.

Two tables:

* ``cross_customer_memories`` — deliberately carries no ``owner_identity``,
  no org id, no hashed/pseudonymous identity of any kind. Every text column
  is populated only from output that has already been through the
  anonymization pipeline (``app.memory.cross_customer_anonymizer``) before
  a row is ever written — see docs/cross_customer.md §1 and §3. This is the
  privacy guarantee: a row can't leak which account contributed it, because
  that was never stored anywhere, not even encrypted.
* ``memory_sharing_preferences`` — one row per ``owner_identity``, default
  OFF (docs/cross_customer.md §2, Hard Constraint 1). Not a column on
  ``app_users``, because that table is legacy custom-auth and doesn't have
  a row for every Clerk-authenticated user; ``owner_identity`` is the one
  scoping key that's universal across both auth paths.

Revision ID: r1m9j6e0i8d9
Revises: q2l8i5d9e6a7
Create Date: 2026-08-03 12:00:00.000000

CockroachDB commits DDL per statement, so each statement below stands alone
and is guarded by an existence check — a killed or partial run can be re-run
safely.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from alembic_helpers import Vector

revision: str = "r1m9j6e0i8d9"
down_revision: Union[str, Sequence[str], None] = "q2l8i5d9e6a7"
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
    if not _table_exists("cross_customer_memories"):
        op.create_table(
            "cross_customer_memories",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
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
            sa.Column("shape_hash", sa.String(length=64), nullable=False),
            sa.Column("migration_type", sa.String(length=64), nullable=False),
            sa.Column("scale_tier", sa.String(length=32), nullable=False),
            sa.Column("parsed_statement_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("generalized_summary", sa.Text(), nullable=False),
            sa.Column("generalized_risk_narrative", sa.Text(), nullable=False),
            sa.Column("generalized_lessons_learned", sa.Text(), nullable=False),
            sa.Column("generalized_surprise_notes", sa.Text(), nullable=True),
            sa.Column("sql_shape_template", sa.Text(), nullable=False),
            sa.Column("risk_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("outcome_class", sa.String(length=32), nullable=False),
            sa.Column("scalar_accuracy_score", sa.Float(), nullable=True),
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
                "contributor_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            ),
            sa.Column(
                "first_contributed_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "last_contributed_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )

    if not _index_exists("ix_cross_customer_memories_shape_hash"):
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cross_customer_memories_shape_hash "
            "ON cross_customer_memories (shape_hash)"
        )

    if not _index_exists("ix_cross_customer_memories_embedding_status"):
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_cross_customer_memories_embedding_status "
            "ON cross_customer_memories (embedding_status)"
        )

    # Single vector index: no owner/tenant prefix column exists on this
    # table by design (see module docstring), so there is only one query
    # shape — corpus-wide-style search, readiness-filtered. Same partial-
    # index pattern as ix_migration_memories_embedding_ready
    # (m8h4e1f7a596) so this index stays reachable rather than silently
    # degrading to a full scan — see that migration's docstring for why
    # the partial predicate is what makes a CockroachDB vector index
    # actually usable by this app's queries.
    if not _index_exists("ix_cross_customer_memories_embedding_ready"):
        op.execute(
            """
            CREATE VECTOR INDEX IF NOT EXISTS ix_cross_customer_memories_embedding_ready
            ON cross_customer_memories (embedding vector_cosine_ops)
            WHERE embedding_status = 'ready'
            """
        )

    if not _table_exists("memory_sharing_preferences"):
        op.create_table(
            "memory_sharing_preferences",
            sa.Column("owner_identity", sa.String(length=256), primary_key=True),
            sa.Column(
                "cross_customer_sharing_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("enabled_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("disabled_at", sa.TIMESTAMP(timezone=True), nullable=True),
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
        )


def downgrade() -> None:
    if _table_exists("memory_sharing_preferences"):
        op.execute("DROP TABLE IF EXISTS memory_sharing_preferences CASCADE")
    if _index_exists("ix_cross_customer_memories_embedding_ready"):
        op.execute(
            "DROP INDEX IF EXISTS ix_cross_customer_memories_embedding_ready CASCADE"
        )
    if _table_exists("cross_customer_memories"):
        op.execute("DROP TABLE IF EXISTS cross_customer_memories CASCADE")
