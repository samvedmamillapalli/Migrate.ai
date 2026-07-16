"""refactor_domain_models

Revision ID: a4f91c2e8b70
Revises: 2c86655424d9
Create Date: 2026-07-17 01:32:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from alembic_helpers import Vector

revision: str = "a4f91c2e8b70"
down_revision: Union[str, Sequence[str], None] = "2c86655424d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop obsolete child tables (indexes go with the tables)
    op.drop_index("ix_verifications_timed_out", table_name="verifications")
    op.drop_index("ix_verifications_created_at", table_name="verifications")
    op.drop_table("verifications")

    op.drop_index("ix_memories_created_at", table_name="memories")
    op.drop_index("ix_memories_grading_score", table_name="memories")
    op.drop_table("memories")

    # CockroachDB-safe deterministic renames
    op.execute(
        "ALTER TABLE predictions RENAME COLUMN "
        "estimated_duration_sec TO estimated_duration_seconds"
    )
    op.execute(
        "ALTER TABLE predictions RENAME COLUMN confidence TO confidence_score"
    )
    op.execute(
        "ALTER TABLE predictions RENAME COLUMN explanation TO reasoning"
    )

    op.drop_column("predictions", "estimated_storage_bytes")
    op.add_column(
        "predictions",
        sa.Column(
            "estimated_storage_mb",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.alter_column(
        "predictions",
        "estimated_storage_mb",
        server_default=None,
        existing_type=sa.Float(),
        existing_nullable=False,
    )

    op.create_table(
        "execution_results",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("migration_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "success",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("actual_duration_seconds", sa.Float(), nullable=False),
        sa.Column("actual_storage_mb", sa.Float(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "rollback_required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
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
            name="fk_execution_results_migration_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_execution_results"),
        sa.UniqueConstraint(
            "migration_run_id",
            name="uq_execution_results_migration_run_id",
        ),
    )
    op.create_index(
        "ix_execution_results_success",
        "execution_results",
        ["success"],
        unique=False,
    )
    op.create_index(
        "ix_execution_results_created_at",
        "execution_results",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "learned_outcomes",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("migration_run_id", sa.Uuid(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("lessons_learned", sa.Text(), nullable=False),
        sa.Column("embedding_id", sa.String(length=255), nullable=True),
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
            name="fk_learned_outcomes_migration_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_learned_outcomes"),
        sa.UniqueConstraint(
            "migration_run_id",
            name="uq_learned_outcomes_migration_run_id",
        ),
    )
    op.create_index(
        "ix_learned_outcomes_created_at",
        "learned_outcomes",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_learned_outcomes_embedding_id",
        "learned_outcomes",
        ["embedding_id"],
        unique=False,
    )

    op.create_table(
        "shadow_clusters",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("migration_run_id", sa.Uuid(), nullable=False),
        sa.Column("cluster_id", sa.String(length=255), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=64),
            server_default=sa.text("'cockroachdb_cloud'"),
            nullable=False,
        ),
        sa.Column("region", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "provisioning",
                "ready",
                "running",
                "destroying",
                "destroyed",
                "failed",
                name="shadow_cluster_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default=sa.text("'provisioning'"),
            nullable=False,
        ),
        sa.Column("destroyed_at", sa.DateTime(timezone=True), nullable=True),
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
            name="fk_shadow_clusters_migration_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shadow_clusters"),
        sa.UniqueConstraint(
            "migration_run_id",
            name="uq_shadow_clusters_migration_run_id",
        ),
        sa.UniqueConstraint(
            "cluster_id",
            name="uq_shadow_clusters_cluster_id",
        ),
    )
    op.create_index(
        "ix_shadow_clusters_status",
        "shadow_clusters",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_shadow_clusters_created_at",
        "shadow_clusters",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_shadow_clusters_created_at", table_name="shadow_clusters")
    op.drop_index("ix_shadow_clusters_status", table_name="shadow_clusters")
    op.drop_table("shadow_clusters")

    op.drop_index(
        "ix_learned_outcomes_embedding_id",
        table_name="learned_outcomes",
    )
    op.drop_index(
        "ix_learned_outcomes_created_at",
        table_name="learned_outcomes",
    )
    op.drop_table("learned_outcomes")

    op.drop_index(
        "ix_execution_results_created_at",
        table_name="execution_results",
    )
    op.drop_index("ix_execution_results_success", table_name="execution_results")
    op.drop_table("execution_results")

    op.drop_column("predictions", "estimated_storage_mb")
    op.add_column(
        "predictions",
        sa.Column(
            "estimated_storage_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.alter_column(
        "predictions",
        "estimated_storage_bytes",
        server_default=None,
        existing_type=sa.BigInteger(),
        existing_nullable=False,
    )
    op.execute(
        "ALTER TABLE predictions RENAME COLUMN reasoning TO explanation"
    )
    op.execute(
        "ALTER TABLE predictions RENAME COLUMN confidence_score TO confidence"
    )
    op.execute(
        "ALTER TABLE predictions RENAME COLUMN "
        "estimated_duration_seconds TO estimated_duration_sec"
    )

    op.create_table(
        "verifications",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("migration_run_id", sa.Uuid(), nullable=False),
        sa.Column("actual_duration_sec", sa.Float(), nullable=False),
        sa.Column("actual_storage_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "rollback_success",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "timed_out",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
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
            name="fk_verifications_migration_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_verifications"),
        sa.UniqueConstraint(
            "migration_run_id",
            name="uq_verifications_migration_run_id",
        ),
    )
    op.create_index(
        "ix_verifications_timed_out",
        "verifications",
        ["timed_out"],
        unique=False,
    )
    op.create_index(
        "ix_verifications_created_at",
        "verifications",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "memories",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("migration_run_id", sa.Uuid(), nullable=False),
        sa.Column("grading_score", sa.Float(), nullable=False),
        sa.Column("surprise_notes", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
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
            name="fk_memories_migration_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memories"),
        sa.UniqueConstraint(
            "migration_run_id",
            name="uq_memories_migration_run_id",
        ),
    )
    op.create_index(
        "ix_memories_grading_score",
        "memories",
        ["grading_score"],
        unique=False,
    )
    op.create_index(
        "ix_memories_created_at",
        "memories",
        ["created_at"],
        unique=False,
    )
