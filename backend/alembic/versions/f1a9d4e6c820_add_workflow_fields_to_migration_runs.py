"""add_workflow_fields_to_migration_runs

Phase 8B: persist Step Functions execution ARN and durable workflow status
on migration_runs.

Revision ID: f1a9d4e6c820
Revises: c3f8a72b1e40
Create Date: 2026-07-17 14:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a9d4e6c820"
down_revision: Union[str, Sequence[str], None] = "c3f8a72b1e40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "migration_runs",
        sa.Column("sfn_execution_arn", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "migration_runs",
        sa.Column(
            "workflow_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_started",
        ),
    )
    op.add_column(
        "migration_runs",
        sa.Column("workflow_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "migration_runs",
        sa.Column("workflow_finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_migration_runs_workflow_status",
        "migration_runs",
        ["workflow_status"],
        unique=False,
    )
    op.create_index(
        "ix_migration_runs_sfn_execution_arn",
        "migration_runs",
        ["sfn_execution_arn"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_migration_runs_sfn_execution_arn",
        table_name="migration_runs",
    )
    op.drop_index(
        "ix_migration_runs_workflow_status",
        table_name="migration_runs",
    )
    op.drop_column("migration_runs", "workflow_finished_at")
    op.drop_column("migration_runs", "workflow_started_at")
    op.drop_column("migration_runs", "workflow_status")
    op.drop_column("migration_runs", "sfn_execution_arn")
