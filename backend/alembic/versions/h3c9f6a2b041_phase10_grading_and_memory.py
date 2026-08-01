"""phase10_grading_and_memory

Phase 10: owner identity + linked runs, timed_out on execution results,
grades table, migration_memories with VECTOR(1024) + CockroachDB vector index,
recommendation outcome fields.

Revision ID: h3c9f6a2b041
Revises: g2b8e5f1a930
Create Date: 2026-07-18 20:00:00.000000

CockroachDB schema changes are asynchronous; this upgrade is written to be
idempotent so a killed/partial run can be resumed safely.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from alembic_helpers import Vector

revision: str = "h3c9f6a2b041"
down_revision: Union[str, Sequence[str], None] = "g2b8e5f1a930"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = current_schema() "
            "AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).first()
    return row is not None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :t"
        ),
        {"t": table},
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


def _constraint_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_schema = current_schema() "
            "AND table_name = :t AND constraint_name = :n"
        ),
        {"t": table, "n": name},
    ).first()
    return row is not None


def upgrade() -> None:
    # --- migration_runs: owner + linked revision ---
    if not _column_exists("migration_runs", "owner_identity"):
        op.add_column(
            "migration_runs",
            sa.Column(
                "owner_identity",
                sa.String(length=256),
                nullable=False,
                server_default="anonymous",
            ),
        )
    if not _column_exists("migration_runs", "revises_run_id"):
        op.add_column(
            "migration_runs",
            sa.Column("revises_run_id", sa.Uuid(), nullable=True),
        )
    if not _constraint_exists("migration_runs", "fk_migration_runs_revises_run_id"):
        op.create_foreign_key(
            "fk_migration_runs_revises_run_id",
            "migration_runs",
            "migration_runs",
            ["revises_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if not _index_exists("ix_migration_runs_owner_identity"):
        op.create_index(
            "ix_migration_runs_owner_identity",
            "migration_runs",
            ["owner_identity"],
            unique=False,
        )
    if not _index_exists("ix_migration_runs_revises_run_id"):
        op.create_index(
            "ix_migration_runs_revises_run_id",
            "migration_runs",
            ["revises_run_id"],
            unique=False,
        )
    if not _column_exists("migration_runs", "recommendation_outcome"):
        op.add_column(
            "migration_runs",
            sa.Column(
                "recommendation_outcome",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
        )

    # --- execution_results: timeout is signal ---
    if not _column_exists("execution_results", "timed_out"):
        op.add_column(
            "execution_results",
            sa.Column(
                "timed_out",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    # --- grades ---
    if not _table_exists("grades"):
        op.create_table(
            "grades",
            sa.Column(
                "id",
                sa.Uuid(),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("migration_run_id", sa.Uuid(), nullable=False),
            sa.Column("scale_tier", sa.String(length=32), nullable=False),
            sa.Column(
                "timed_out",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("duration_abs_error_seconds", sa.Float(), nullable=True),
            sa.Column("duration_pct_error", sa.Float(), nullable=True),
            sa.Column("duration_within_band", sa.Boolean(), nullable=True),
            sa.Column(
                "duration_unverifiable",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("storage_abs_error_mb", sa.Float(), nullable=False),
            sa.Column("storage_pct_error", sa.Float(), nullable=True),
            sa.Column("storage_within_band", sa.Boolean(), nullable=False),
            sa.Column("rollback_predicted", sa.String(length=16), nullable=False),
            sa.Column("rollback_actual_class", sa.String(length=16), nullable=False),
            sa.Column("rollback_consistent", sa.Boolean(), nullable=False),
            sa.Column("rollback_within_band", sa.Boolean(), nullable=False),
            sa.Column("outcome_class", sa.String(length=32), nullable=False),
            sa.Column("high_risk_flags_present", sa.Boolean(), nullable=False),
            sa.Column("adjusted_confidence", sa.Float(), nullable=False),
            sa.Column("scalar_accuracy_score", sa.Float(), nullable=False),
            sa.Column(
                "dimension_details",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column("surprise_notes", sa.Text(), nullable=True),
            sa.Column("lessons_learned", sa.Text(), nullable=False),
            sa.Column(
                "prose_status",
                sa.String(length=32),
                nullable=False,
                server_default="ok",
            ),
            sa.Column("prose_error", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["migration_run_id"],
                ["migration_runs.id"],
                name="fk_grades_migration_run_id",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_grades"),
            sa.UniqueConstraint(
                "migration_run_id",
                name="uq_grades_migration_run_id",
            ),
        )
    for idx, cols in (
        ("ix_grades_scale_tier", ["scale_tier"]),
        ("ix_grades_scalar_accuracy_score", ["scalar_accuracy_score"]),
        ("ix_grades_created_at", ["created_at"]),
    ):
        if not _index_exists(idx):
            op.create_index(idx, "grades", cols, unique=False)

    # --- migration_memories ---
    if not _table_exists("migration_memories"):
        op.create_table(
            "migration_memories",
            sa.Column(
                "id",
                sa.Uuid(),
                server_default=sa.text("gen_random_uuid()"),
                nullable=False,
            ),
            sa.Column("migration_run_id", sa.Uuid(), nullable=False),
            sa.Column("owner_identity", sa.String(length=256), nullable=False),
            sa.Column("scale_tier", sa.String(length=32), nullable=False),
            sa.Column("migration_type", sa.String(length=64), nullable=False),
            sa.Column("migration_summary", sa.Text(), nullable=False),
            sa.Column("schema_summary", sa.Text(), nullable=False),
            sa.Column(
                "risk_flags",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column(
                "prediction_summary",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column(
                "recommendation_summary",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
            sa.Column(
                "approval_summary",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
            sa.Column(
                "execution_summary",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column(
                "grade_summary",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
            ),
            sa.Column("lessons_learned", sa.Text(), nullable=False),
            sa.Column("surprise_notes", sa.Text(), nullable=True),
            sa.Column("embed_text", sa.Text(), nullable=False),
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
                "index_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "table_complexity",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["migration_run_id"],
                ["migration_runs.id"],
                name="fk_migration_memories_migration_run_id",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_migration_memories"),
            sa.UniqueConstraint(
                "migration_run_id",
                name="uq_migration_memories_migration_run_id",
            ),
        )
    for idx, cols in (
        ("ix_migration_memories_owner_identity", ["owner_identity"]),
        ("ix_migration_memories_scale_tier", ["scale_tier"]),
        ("ix_migration_memories_migration_type", ["migration_type"]),
        ("ix_migration_memories_embedding_status", ["embedding_status"]),
        ("ix_migration_memories_created_at", ["created_at"]),
    ):
        if not _index_exists(idx):
            op.create_index(idx, "migration_memories", cols, unique=False)

    # CockroachDB Distributed Vector Indexing (required hackathon tool).
    if not _index_exists("ix_migration_memories_embedding"):
        op.execute(
            """
            CREATE VECTOR INDEX IF NOT EXISTS ix_migration_memories_embedding
            ON migration_memories (embedding vector_cosine_ops)
            """
        )


def downgrade() -> None:
    if _index_exists("ix_migration_memories_embedding"):
        op.execute("DROP INDEX IF EXISTS ix_migration_memories_embedding CASCADE")
    if _table_exists("migration_memories"):
        op.drop_table("migration_memories")
    if _table_exists("grades"):
        op.drop_table("grades")
    if _column_exists("execution_results", "timed_out"):
        op.drop_column("execution_results", "timed_out")
    if _column_exists("migration_runs", "recommendation_outcome"):
        op.drop_column("migration_runs", "recommendation_outcome")
    if _index_exists("ix_migration_runs_revises_run_id"):
        op.drop_index("ix_migration_runs_revises_run_id", table_name="migration_runs")
    if _index_exists("ix_migration_runs_owner_identity"):
        op.drop_index("ix_migration_runs_owner_identity", table_name="migration_runs")
    if _constraint_exists("migration_runs", "fk_migration_runs_revises_run_id"):
        op.drop_constraint(
            "fk_migration_runs_revises_run_id",
            "migration_runs",
            type_="foreignkey",
        )
    if _column_exists("migration_runs", "revises_run_id"):
        op.drop_column("migration_runs", "revises_run_id")
    if _column_exists("migration_runs", "owner_identity"):
        op.drop_column("migration_runs", "owner_identity")
