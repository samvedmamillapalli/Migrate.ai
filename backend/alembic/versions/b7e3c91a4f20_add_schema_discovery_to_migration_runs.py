"""add_schema_discovery_to_migration_runs

Revision ID: b7e3c91a4f20
Revises: a4f91c2e8b70
Create Date: 2026-07-17 06:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7e3c91a4f20"
down_revision: Union[str, Sequence[str], None] = "a4f91c2e8b70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "migration_runs",
        sa.Column("schema_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "migration_runs",
        sa.Column("schema_discovered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "migration_runs",
        sa.Column("schema_discovery_duration_ms", sa.Float(), nullable=True),
    )
    op.add_column(
        "migration_runs",
        sa.Column("schema_database_engine", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "migration_runs",
        sa.Column("schema_database_version", sa.Text(), nullable=True),
    )
    op.add_column(
        "migration_runs",
        sa.Column("schema_discovery_status", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_migration_runs_schema_discovery_status",
        "migration_runs",
        ["schema_discovery_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_migration_runs_schema_discovery_status",
        table_name="migration_runs",
    )
    op.drop_column("migration_runs", "schema_discovery_status")
    op.drop_column("migration_runs", "schema_database_version")
    op.drop_column("migration_runs", "schema_database_engine")
    op.drop_column("migration_runs", "schema_discovery_duration_ms")
    op.drop_column("migration_runs", "schema_discovered_at")
    op.drop_column("migration_runs", "schema_snapshot")
