"""slack_installation_authed_user

Adds ``authed_user_id`` to ``slack_installations`` — the Slack user ID of
the person who completed the OAuth install (``authed_user.id`` from the
``oauth.v2.access`` response). ``SlackOAuthService.exchange_code`` already
extracts this value; it was previously discarded.

Lifecycle notifications DM this user directly (``chat.postMessage`` with a
user ID as the channel) instead of posting to a hardcoded channel name,
which requires only the ``chat:write`` scope already requested and cannot
fail with ``not_in_channel`` the way an un-joined named channel can.

Revision ID: q2l8i5d9e6a7
Revises: p1k7h4c8d598
Create Date: 2026-08-03 00:00:00.000000

CockroachDB commits DDL per statement, so each statement below stands alone
and is guarded by an existence check — a killed or partial run can be re-run
safely.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "q2l8i5d9e6a7"
down_revision: Union[str, Sequence[str], None] = "p1k7h4c8d598"
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


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :t "
            "AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).first()
    return row is not None


def upgrade() -> None:
    if _table_exists("slack_installations") and not _column_exists(
        "slack_installations", "authed_user_id"
    ):
        op.execute(
            "ALTER TABLE slack_installations ADD COLUMN authed_user_id "
            "STRING(64)"
        )


def downgrade() -> None:
    if _table_exists("slack_installations") and _column_exists(
        "slack_installations", "authed_user_id"
    ):
        op.execute(
            "ALTER TABLE slack_installations DROP COLUMN authed_user_id"
        )
