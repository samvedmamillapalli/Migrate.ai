"""A workspace scopes migration runs to one target database — docs/FUTURE_WORKSPACES_PLAN.md.

``owner_identity`` matches the plain-string convention used everywhere else
in this codebase (``MigrationRun.owner_identity``, ``Approval.approver_identity``)
rather than a foreign key to ``app_users`` — that table is confirmed dead
code (only referenced by the disabled-by-default legacy custom-auth
register/login flow), not the live identity source.

``connection_secret_arn`` is a pointer only, matching
``MigrationRun.connection_secret_arn`` — never the password, never the raw
connection string, at rest.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Workspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        Index("ix_workspaces_owner_identity", "owner_identity"),
        UniqueConstraint(
            "owner_identity", "name", name="uq_workspaces_owner_identity_name"
        ),
        # One repo maps to at most one workspace, globally — docs/
        # FUTURE_GITHUB_INTEGRATION_PLAN.md's Open Questions recommend
        # one-repo-to-one-workspace for now (richer monorepo mapping is
        # explicitly deferred). A partial unique index (not a plain unique
        # column) so most workspaces, which have no linked repo, can all
        # share NULL.
        Index(
            "uq_workspaces_github_repo_full_name",
            "github_repo_full_name",
            unique=True,
            postgresql_where=text("github_repo_full_name IS NOT NULL"),
        ),
    )

    owner_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    connection_secret_arn: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    # Denormalized display-only hint (e.g. a redacted host or db name) so the
    # workspace switcher can render a label without a live Secrets Manager
    # round-trip. Never the full connection string or credentials.
    connection_label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # docs/FUTURE_GITHUB_INTEGRATION_PLAN.md: "owner/repo" this workspace is
    # linked to. A GitHub App installed on this repo will resolve incoming
    # `pull_request` webhooks to this workspace's stored connection. NULL
    # means "no repo linked" (the common case).
    github_repo_full_name: Mapped[str | None] = mapped_column(
        String(256), nullable=True
    )
    # Glob pattern (fnmatch-style, matched against each changed file's repo-
    # relative path) used to detect a migration file in a PR's diff. Kept
    # per-workspace/per-repo rather than hardcoded, since different repos use
    # different migration tooling (Alembic, Django, Rails, raw SQL, ...) —
    # see the plan's "Proposed Detection Heuristic" section. Defaults to this
    # project's own Alembic convention, the only heuristic this plan commits to.
    github_migration_glob: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        default="backend/alembic/versions/*.py",
        server_default="backend/alembic/versions/*.py",
    )

    def __repr__(self) -> str:
        return f"Workspace(id={self.id!s}, owner_identity={self.owner_identity!r}, name={self.name!r})"
