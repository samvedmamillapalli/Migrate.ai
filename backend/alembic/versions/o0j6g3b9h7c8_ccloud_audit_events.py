"""ccloud_audit_events

ccloud CLI integration, Feature 1 (audit-trail corroboration). New table
storing CockroachDB Cloud audit-log entries (``ccloud audit list``) tied to a
migration run's shadow cluster lifecycle — a source of truth the REST-API
provisioning path never touches, giving judges two independently-sourced
records of the same shadow-cluster lifecycle. See docs/cockroach_hookup.md §4
"Feature 1".

No vector column, no CockroachDB Distributed Vector Index here — this is
structured audit data with no semantic-search use case, unlike
migration_memories or cockroachdb_skill_docs.

Revision ID: o0j6g3b9h7c8
Revises: n9i5f2a8g6b7
Create Date: 2026-08-02 03:00:00.000000

CockroachDB commits DDL per statement, so each statement below stands alone
and is guarded by an existence check — a killed or partial run can be re-run
safely.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o0j6g3b9h7c8"
down_revision: Union[str, Sequence[str], None] = "n9i5f2a8g6b7"
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
    if not _table_exists("ccloud_audit_events"):
        op.create_table(
            "ccloud_audit_events",
            sa.Column(
                "id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "migration_run_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                sa.ForeignKey("migration_runs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("event_type", sa.String(length=128), nullable=False),
            sa.Column("actor", sa.String(length=256), nullable=True),
            sa.Column("occurred_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("raw_payload", sa.dialects.postgresql.JSONB(), nullable=False),
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
        )

    # TimestampMixin requires updated_at; guarded separately in case this
    # migration is re-run against a table created by an earlier draft.
    if _table_exists("ccloud_audit_events") and not _column_exists(
        "ccloud_audit_events", "updated_at"
    ):
        op.execute(
            "ALTER TABLE ccloud_audit_events ADD COLUMN updated_at "
            "TIMESTAMPTZ NOT NULL DEFAULT now()"
        )

    if not _index_exists("ix_ccloud_audit_events_migration_run_id"):
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_ccloud_audit_events_migration_run_id "
            "ON ccloud_audit_events (migration_run_id)"
        )
    if not _index_exists("ix_ccloud_audit_events_occurred_at"):
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_ccloud_audit_events_occurred_at "
            "ON ccloud_audit_events (occurred_at)"
        )


def downgrade() -> None:
    if _table_exists("ccloud_audit_events"):
        op.execute("DROP TABLE IF EXISTS ccloud_audit_events CASCADE")
