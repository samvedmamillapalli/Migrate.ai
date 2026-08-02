"""slack_installations

Slack OAuth v2 integration: one row per application user (owner_identity),
updated (upserted) on re-install. Stores the Slack team/bot identity and the
bot access token, encrypted at rest when SLACK_TOKEN_ENCRYPTION_KEY is set.

Revision ID: p1k7h4c8d598
Revises: o0j6g3b9h7c8
Create Date: 2026-08-12 10:00:00.000000

CockroachDB commits DDL per statement, so each statement below stands alone
and is guarded by an existence check — a killed or partial run can be re-run
safely.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p1k7h4c8d598"
down_revision: Union[str, Sequence[str], None] = "o0j6g3b9h7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = :t"
        ),
        {"t": name},
    ).first()
    return row is not None


def _index_exists(index: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = current_schema() AND indexname = :i"
        ),
        {"i": index},
    ).first()
    return row is not None


def upgrade() -> None:
    if not _table_exists("slack_installations"):
        op.create_table(
            "slack_installations",
            sa.Column(
                "id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "created_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column("owner_identity", sa.String(length=256), nullable=False),
            sa.Column("team_id", sa.String(length=64), nullable=False),
            sa.Column("team_name", sa.String(length=256), nullable=True),
            sa.Column("bot_user_id", sa.String(length=64), nullable=False),
            sa.Column("bot_access_token", sa.Text(), nullable=False),
            sa.Column("scope", sa.String(length=1024), nullable=False),
            sa.Column(
                "installed_at",
                sa.TIMESTAMP(timezone=True),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "owner_identity",
                name="uq_slack_installations_owner_identity",
            ),
        )

    if not _index_exists("ix_slack_installations_owner_identity"):
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_slack_installations_owner_identity "
            "ON slack_installations (owner_identity)"
        )


def downgrade() -> None:
    if _table_exists("slack_installations"):
        op.execute("DROP TABLE IF EXISTS slack_installations CASCADE")
