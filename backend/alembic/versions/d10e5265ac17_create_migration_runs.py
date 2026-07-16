"""create_migration_runs

Revision ID: d10e5265ac17
Revises:
Create Date: 2026-07-17 01:13:27.300328

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d10e5265ac17"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "migration_runs",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("migration_sql", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "predicting",
                "running",
                "completed",
                "failed",
                name="migration_run_status",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default=sa.text("'pending'"),
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
        sa.PrimaryKeyConstraint("id", name="pk_migration_runs"),
    )
    op.create_index(
        "ix_migration_runs_status",
        "migration_runs",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_migration_runs_status", table_name="migration_runs")
    op.drop_table("migration_runs")
