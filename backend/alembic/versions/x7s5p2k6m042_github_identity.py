"""github identity

"Who is this GitHub identity" for workspace-invite matching — distinct
from the GitHub App used for PR-integration webhooks (github_pull_request_links,
migration v5q3n0i4k820). This is a standard OAuth user-to-server access
token, scoped read:user only, stored encrypted the same way
slack_installations.bot_access_token is.

Revision ID: x7s5p2k6m042
Revises: w6r4o1j5l931
Create Date: 2026-08-08 09:00:00.000000

CockroachDB commits DDL per statement, so each statement below stands alone
and is guarded by an existence check — a killed or partial run can be
re-run safely.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "x7s5p2k6m042"
down_revision: Union[str, Sequence[str], None] = "w6r4o1j5l931"
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
    if not _table_exists("github_identities"):
        op.create_table(
            "github_identities",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
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
            sa.Column("github_user_id", sa.BigInteger(), nullable=False),
            sa.Column("github_login", sa.String(length=256), nullable=False),
            sa.Column("avatar_url", sa.String(length=1024), nullable=True),
            sa.Column("access_token", sa.Text(), nullable=False),
            sa.Column("scope", sa.String(length=256), nullable=False),
            sa.Column("connected_at", sa.TIMESTAMP(timezone=True), nullable=False),
        )

    if not _index_exists("uq_github_identities_owner_identity"):
        op.create_index(
            "uq_github_identities_owner_identity",
            "github_identities",
            ["owner_identity"],
            unique=True,
        )


def downgrade() -> None:
    if _table_exists("github_identities"):
        op.execute("DROP TABLE IF EXISTS github_identities CASCADE")
