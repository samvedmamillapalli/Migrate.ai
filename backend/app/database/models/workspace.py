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

from sqlalchemy import Boolean, Index, String, UniqueConstraint
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

    def __repr__(self) -> str:
        return f"Workspace(id={self.id!s}, owner_identity={self.owner_identity!r}, name={self.name!r})"
