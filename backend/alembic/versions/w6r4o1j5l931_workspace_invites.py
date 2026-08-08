"""workspace invites and members

Roster-only membership: a workspace_members row grants visibility of the
workspace (GET /workspaces, GET /workspaces/{id}) but deliberately does
NOT grant access to that workspace's migration_runs — every run-scoped
route still checks MigrationRun.owner_identity exactly, unchanged. See
app/database/models/workspace_member.py's module docstring.

Data backfill: every existing workspace gets an implicit
workspace_members row (role='owner') for its own owner_identity, so the
member list is populated from day one instead of starting empty for
every workspace that predates this feature.

Revision ID: w6r4o1j5l931
Revises: v5q3n0i4k820
Create Date: 2026-08-07 12:00:00.000000

CockroachDB commits DDL per statement, so each statement below stands alone
and is guarded by an existence check — a killed or partial run can be
re-run safely.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "w6r4o1j5l931"
down_revision: Union[str, Sequence[str], None] = "v5q3n0i4k820"
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


def _constraint_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_schema = current_schema() "
            "AND table_name = :t AND constraint_name = :n"
        ),
        {"t": table, "n": name},
    ).first()
    return row is not None


def upgrade() -> None:
    if not _table_exists("workspace_members"):
        op.create_table(
            "workspace_members",
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
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_identity", sa.String(length=256), nullable=False),
            sa.Column(
                "role",
                sa.String(length=16),
                nullable=False,
                server_default="member",
            ),
        )

    if not _constraint_exists("workspace_members", "fk_workspace_members_workspace_id"):
        op.create_foreign_key(
            "fk_workspace_members_workspace_id",
            "workspace_members",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )

    if not _index_exists("uq_workspace_members_workspace_user"):
        op.create_index(
            "uq_workspace_members_workspace_user",
            "workspace_members",
            ["workspace_id", "user_identity"],
            unique=True,
        )

    if not _table_exists("workspace_invites"):
        op.create_table(
            "workspace_invites",
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
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("inviter_identity", sa.String(length=256), nullable=False),
            sa.Column("method", sa.String(length=16), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("github_username", sa.String(length=256), nullable=True),
            sa.Column("token", sa.String(length=64), nullable=False),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
            sa.Column("accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column("accepted_by", sa.String(length=256), nullable=True),
        )

    if not _constraint_exists("workspace_invites", "fk_workspace_invites_workspace_id"):
        op.create_foreign_key(
            "fk_workspace_invites_workspace_id",
            "workspace_invites",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )

    if not _index_exists("uq_workspace_invites_token"):
        op.create_index(
            "uq_workspace_invites_token",
            "workspace_invites",
            ["token"],
            unique=True,
        )

    if not _index_exists("ix_workspace_invites_workspace_id"):
        op.create_index(
            "ix_workspace_invites_workspace_id",
            "workspace_invites",
            ["workspace_id"],
            unique=False,
        )

    # --- Data backfill: every existing workspace's owner becomes its
    # implicit 'owner' member, idempotent via NOT EXISTS ---
    op.execute(
        """
        INSERT INTO workspace_members (id, workspace_id, user_identity, role, created_at, updated_at)
        SELECT gen_random_uuid(), w.id, w.owner_identity, 'owner', now(), now()
        FROM workspaces w
        WHERE NOT EXISTS (
            SELECT 1 FROM workspace_members m
            WHERE m.workspace_id = w.id AND m.user_identity = w.owner_identity
        )
        """
    )


def downgrade() -> None:
    if _table_exists("workspace_invites"):
        op.execute("DROP TABLE IF EXISTS workspace_invites CASCADE")
    if _table_exists("workspace_members"):
        op.execute("DROP TABLE IF EXISTS workspace_members CASCADE")
