"""run_kind_and_shadow_history

UI audit follow-up (docs/ai_audit.md):
- migration_runs.run_kind: distinguishes standard / chaos / debug runs so the
  Overview "Recent" list and future queries can filter deliberate failure
  tests out of what a judge sees, instead of showing every run unfiltered.
- shadow_clusters.event_log: append-only array of every observed
  status + stage_timings snapshot, so a finished run can be replayed step by
  step (previously last-write-wins with no history).
- shadow_clusters.schema_snapshot_before / schema_snapshot_after: structural
  DatabaseMetadata captured immediately before and after the migration runs
  on the shadow cluster, so the live view can render a real before/after diff
  instead of only a storage-byte delta.
- grades.storage_unverifiable (+ storage_within_band now nullable): storage
  deltas below the measurement floor are graded unverifiable instead of a
  trivial "within band" pass, mirroring how a timed-out duration is already
  handled.

Revision ID: k6f2c9d5e374
Revises: j5e1b8c4d263
Create Date: 2026-07-28 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "k6f2c9d5e374"
down_revision: Union[str, Sequence[str], None] = "j5e1b8c4d263"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "migration_runs",
        sa.Column(
            "run_kind",
            sa.String(length=32),
            nullable=False,
            server_default="standard",
        ),
    )
    op.create_index(
        "ix_migration_runs_run_kind",
        "migration_runs",
        ["run_kind"],
        unique=False,
    )

    op.add_column(
        "shadow_clusters",
        sa.Column("event_log", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "shadow_clusters",
        sa.Column(
            "schema_snapshot_before",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "shadow_clusters",
        sa.Column(
            "schema_snapshot_after",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    op.alter_column(
        "grades",
        "storage_within_band",
        existing_type=sa.Boolean(),
        nullable=True,
    )
    op.add_column(
        "grades",
        sa.Column(
            "storage_unverifiable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("grades", "storage_unverifiable")
    op.alter_column(
        "grades",
        "storage_within_band",
        existing_type=sa.Boolean(),
        nullable=False,
    )

    op.drop_column("shadow_clusters", "schema_snapshot_after")
    op.drop_column("shadow_clusters", "schema_snapshot_before")
    op.drop_column("shadow_clusters", "event_log")

    op.drop_index("ix_migration_runs_run_kind", table_name="migration_runs")
    op.drop_column("migration_runs", "run_kind")
