"""workspaces

docs/FUTURE_WORKSPACES_PLAN.md — a workspace scopes migration runs to one
target database (a name + an owning ``owner_identity`` + a pointer-only
``connection_secret_arn``, same convention as
``MigrationRun.connection_secret_arn``). ``owner_identity`` is a plain
string, matching every other identity column in this codebase — not a
foreign key to ``app_users``, which is confirmed dead code (only referenced
by the disabled-by-default legacy custom-auth register/login flow).

``migration_runs.workspace_id`` is nullable and ``ON DELETE SET NULL``:
deleting a workspace must never delete run history, and a one-off run
without any workspace stays possible.

Data backfill (not just DDL): every distinct ``owner_identity`` already
present in ``migration_runs`` gets an implicit "Default" workspace (no
stored connection — there's no way to recover what connection URL each
historical run actually used), and every existing run with
``workspace_id IS NULL`` is pointed at its owner's default workspace. This
is the human-approved migration path from docs/FUTURE_WORKSPACES_PLAN.md's
"Migration Path for Existing Runs" section, option (1).

Revision ID: t3o1l8g2i608
Revises: s2n0k7f1j9e0
Create Date: 2026-08-05 09:00:00.000000

CockroachDB commits DDL per statement, so each statement below stands alone
and is guarded by an existence check — a killed or partial run can be
re-run safely.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "t3o1l8g2i608"
down_revision: Union[str, Sequence[str], None] = "s2n0k7f1j9e0"
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
            "WHERE table_schema = current_schema() "
            "AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
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
    if not _table_exists("workspaces"):
        op.create_table(
            "workspaces",
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
            sa.Column("name", sa.String(length=256), nullable=False),
            sa.Column("connection_secret_arn", sa.String(length=512), nullable=True),
            sa.Column("connection_label", sa.String(length=256), nullable=True),
            sa.Column(
                "is_default",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    if not _index_exists("ix_workspaces_owner_identity"):
        op.create_index(
            "ix_workspaces_owner_identity",
            "workspaces",
            ["owner_identity"],
            unique=False,
        )

    if not _index_exists("uq_workspaces_owner_identity_name"):
        op.create_index(
            "uq_workspaces_owner_identity_name",
            "workspaces",
            ["owner_identity", "name"],
            unique=True,
        )

    if not _column_exists("migration_runs", "workspace_id"):
        op.add_column(
            "migration_runs",
            sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        )

    if not _constraint_exists("migration_runs", "fk_migration_runs_workspace_id"):
        op.create_foreign_key(
            "fk_migration_runs_workspace_id",
            "migration_runs",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if not _index_exists("ix_migration_runs_workspace_id"):
        op.create_index(
            "ix_migration_runs_workspace_id",
            "migration_runs",
            ["workspace_id"],
            unique=False,
        )

    # --- Data backfill: implicit default workspace per existing owner ---
    # Idempotent via NOT EXISTS (not ON CONFLICT) to match this codebase's
    # existing explicit-existence-check convention rather than relying on
    # the unique index's conflict-resolution semantics for a re-run.
    op.execute(
        """
        INSERT INTO workspaces (id, owner_identity, name, is_default, created_at, updated_at)
        SELECT gen_random_uuid(), mr.owner_identity, 'Default', true, now(), now()
        FROM (SELECT DISTINCT owner_identity FROM migration_runs) mr
        WHERE NOT EXISTS (
            SELECT 1 FROM workspaces w
            WHERE w.owner_identity = mr.owner_identity AND w.name = 'Default'
        )
        """
    )
    op.execute(
        """
        UPDATE migration_runs
        SET workspace_id = w.id
        FROM workspaces w
        WHERE w.owner_identity = migration_runs.owner_identity
          AND w.name = 'Default'
          AND migration_runs.workspace_id IS NULL
        """
    )


def downgrade() -> None:
    if _index_exists("ix_migration_runs_workspace_id"):
        op.drop_index("ix_migration_runs_workspace_id", table_name="migration_runs")
    if _constraint_exists("migration_runs", "fk_migration_runs_workspace_id"):
        op.drop_constraint(
            "fk_migration_runs_workspace_id",
            "migration_runs",
            type_="foreignkey",
        )
    if _column_exists("migration_runs", "workspace_id"):
        op.drop_column("migration_runs", "workspace_id")
    if _table_exists("workspaces"):
        op.execute("DROP TABLE IF EXISTS workspaces CASCADE")
