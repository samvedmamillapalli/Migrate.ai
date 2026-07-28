"""shadow_row_samples

Real before/after row samples (up to 20 rows + real column list + total row
count) for the tables a migration references, captured alongside the
existing structural schema snapshot. Shadow-tier synthetic data, never the
customer's production rows. See docs/ai_audit.md task: "row sample panel".

Revision ID: l7g3d0e6f485
Revises: k6f2c9d5e374
Create Date: 2026-07-29 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "l7g3d0e6f485"
down_revision: Union[str, Sequence[str], None] = "k6f2c9d5e374"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shadow_clusters",
        sa.Column(
            "row_sample_before", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "shadow_clusters",
        sa.Column(
            "row_sample_after", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("shadow_clusters", "row_sample_after")
    op.drop_column("shadow_clusters", "row_sample_before")
