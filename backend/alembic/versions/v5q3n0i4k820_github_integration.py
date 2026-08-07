"""github integration

docs/FUTURE_GITHUB_INTEGRATION_PLAN.md — a GitHub App receives `pull_request`
webhooks and resolves them to a workspace via `Workspace.github_repo_full_name`
(one repo maps to at most one workspace, per the plan's Open Questions
recommendation; enforced by a partial unique index so the common case of "no
repo linked" doesn't collide on NULL). `Workspace.github_migration_glob`
holds the per-repo migration-file detection heuristic (default: this
project's own Alembic versions convention).

`github_pull_request_links` records which PR (repo/PR-number/installation/
head-sha) created a given `MigrationRun`, so the prediction and terminal
notification hooks know whether — and where — to post a result back to
GitHub. One row per run (owned by the run: `ON DELETE CASCADE`), mirroring
the existing `approvals` table's relationship to `migration_runs`.

Revision ID: v5q3n0i4k820
Revises: t3o1l8g2i608
Create Date: 2026-08-05 12:00:00.000000

CockroachDB commits DDL per statement, so each statement below stands alone
and is guarded by an existence check — a killed or partial run can be
re-run safely.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "v5q3n0i4k820"
down_revision: Union[str, Sequence[str], None] = "t3o1l8g2i608"
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
    if not _column_exists("workspaces", "github_repo_full_name"):
        op.add_column(
            "workspaces",
            sa.Column("github_repo_full_name", sa.String(length=256), nullable=True),
        )

    if not _column_exists("workspaces", "github_migration_glob"):
        op.add_column(
            "workspaces",
            sa.Column(
                "github_migration_glob",
                sa.String(length=512),
                nullable=False,
                server_default="backend/alembic/versions/*.py",
            ),
        )

    if not _index_exists("uq_workspaces_github_repo_full_name"):
        op.execute(
            "CREATE UNIQUE INDEX uq_workspaces_github_repo_full_name "
            "ON workspaces (github_repo_full_name) "
            "WHERE github_repo_full_name IS NOT NULL"
        )

    if not _table_exists("github_pull_request_links"):
        op.create_table(
            "github_pull_request_links",
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
            sa.Column(
                "migration_run_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column("repo_full_name", sa.String(length=256), nullable=False),
            sa.Column("pr_number", sa.Integer(), nullable=False),
            sa.Column("installation_id", sa.BigInteger(), nullable=False),
            sa.Column("head_sha", sa.String(length=64), nullable=False),
            sa.Column("pr_author_login", sa.String(length=256), nullable=True),
            sa.Column("check_run_id", sa.BigInteger(), nullable=True),
            sa.Column("initial_comment_id", sa.BigInteger(), nullable=True),
            sa.Column(
                "terminal_comment_posted_at",
                sa.TIMESTAMP(timezone=True),
                nullable=True,
            ),
        )

    if not _constraint_exists(
        "github_pull_request_links", "fk_github_pr_links_migration_run_id"
    ):
        op.create_foreign_key(
            "fk_github_pr_links_migration_run_id",
            "github_pull_request_links",
            "migration_runs",
            ["migration_run_id"],
            ["id"],
            ondelete="CASCADE",
        )

    if not _index_exists("uq_github_pr_links_migration_run_id"):
        op.create_index(
            "uq_github_pr_links_migration_run_id",
            "github_pull_request_links",
            ["migration_run_id"],
            unique=True,
        )


def downgrade() -> None:
    if _table_exists("github_pull_request_links"):
        op.execute("DROP TABLE IF EXISTS github_pull_request_links CASCADE")
    if _index_exists("uq_workspaces_github_repo_full_name"):
        op.execute("DROP INDEX IF EXISTS uq_workspaces_github_repo_full_name")
    if _column_exists("workspaces", "github_migration_glob"):
        op.drop_column("workspaces", "github_migration_glob")
    if _column_exists("workspaces", "github_repo_full_name"):
        op.drop_column("workspaces", "github_repo_full_name")
