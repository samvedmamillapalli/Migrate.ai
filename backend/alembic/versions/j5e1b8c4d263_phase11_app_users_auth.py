"""phase11_app_users_auth

Revision ID: j5e1b8c4d263
Revises: i4d0a7b3c152
Create Date: 2026-07-25 16:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j5e1b8c4d263"
down_revision: Union[str, Sequence[str], None] = "i4d0a7b3c152"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("owner_identity", sa.String(length=256), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_identity", name="uq_app_users_owner_identity"),
    )
    op.create_index("ix_app_users_owner_identity", "app_users", ["owner_identity"])


def downgrade() -> None:
    op.drop_index("ix_app_users_owner_identity", table_name="app_users")
    op.drop_table("app_users")
