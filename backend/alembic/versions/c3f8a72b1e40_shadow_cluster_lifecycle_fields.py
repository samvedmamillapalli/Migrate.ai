"""shadow_cluster_lifecycle_fields

Phase 7: extend shadow_clusters with lifecycle bookkeeping used by the
orchestration (create -> ready -> seed -> migrate -> destroy), the concurrency
cap, and the orphan sweeper.

Revision ID: c3f8a72b1e40
Revises: b7e3c91a4f20
Create Date: 2026-07-17 07:20:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3f8a72b1e40"
down_revision: Union[str, Sequence[str], None] = "b7e3c91a4f20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # cluster_id is now nullable: the PROVISIONING row is inserted before the
    # provider returns a cluster id, so the sweeper and concurrency accounting
    # can already see the in-flight cluster.
    op.alter_column(
        "shadow_clusters",
        "cluster_id",
        existing_type=sa.String(length=255),
        nullable=True,
    )
    op.add_column(
        "shadow_clusters",
        sa.Column("cluster_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "shadow_clusters",
        sa.Column("scale_tier", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "shadow_clusters",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "shadow_clusters",
        sa.Column(
            "stage_timings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "shadow_clusters",
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_shadow_clusters_expires_at",
        "shadow_clusters",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shadow_clusters_expires_at",
        table_name="shadow_clusters",
    )
    op.drop_column("shadow_clusters", "error_message")
    op.drop_column("shadow_clusters", "stage_timings")
    op.drop_column("shadow_clusters", "expires_at")
    op.drop_column("shadow_clusters", "scale_tier")
    op.drop_column("shadow_clusters", "cluster_name")
    op.alter_column(
        "shadow_clusters",
        "cluster_id",
        existing_type=sa.String(length=255),
        nullable=False,
    )
