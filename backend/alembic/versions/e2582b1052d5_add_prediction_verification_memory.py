"""add_prediction_verification_memory

Revision ID: e2582b1052d5
Revises: d10e5265ac17
Create Date: 2026-07-17 01:23:32.023157

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from alembic_helpers import Vector

revision: str = "e2582b1052d5"
down_revision: Union[str, Sequence[str], None] = "d10e5265ac17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "predictions",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("migration_run_id", sa.Uuid(), nullable=False),
        sa.Column("estimated_duration_sec", sa.Float(), nullable=False),
        sa.Column("estimated_storage_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "rollback_risk",
            sa.Enum(
                "low",
                "medium",
                "high",
                name="rollback_risk",
                native_enum=False,
                create_constraint=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
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
            name="fk_predictions_migration_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_predictions"),
        sa.UniqueConstraint(
            "migration_run_id",
            name="uq_predictions_migration_run_id",
        ),
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


def downgrade() -> None:
    op.drop_index("ix_memories_grading_score", table_name="memories")
    op.drop_table("memories")
    op.drop_table("verifications")
    op.drop_table("predictions")
