"""phase10b_closed_loop_and_ops

Store connection_secret_arn on runs for approve→workflow; mark LearnedOutcome
deprecated in comments only (table kept for compatibility).

Revision ID: i4d0a7b3c152
Revises: h3c9f6a2b041
Create Date: 2026-07-18 22:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "i4d0a7b3c152"
down_revision: Union[str, Sequence[str], None] = "h3c9f6a2b041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "migration_runs",
        sa.Column("connection_secret_arn", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("migration_runs", "connection_secret_arn")
