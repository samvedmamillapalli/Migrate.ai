"""A pending (or resolved) invitation to join a workspace.

The token is the credential — anyone who has it can view the preview and,
once authenticated, accept it. Stored as plain text (not hashed) by
design: the invite-management UI needs to read it back (e.g. the "link"
tab re-displays an existing pending link invite instead of minting a new
one every time the dialog opens), which a one-way hash can't support. This
is the same shape as any other capability-URL invite link (Slack, Notion,
Linear); it is not a password, it's protected by TLS in transit, database
access controls at rest, expiry, and revocability.

``status`` only ever stores ``pending`` / ``accepted`` / ``revoked`` at
write time — "expired" is computed at read time by comparing
``expires_at`` to now (see ``WorkspaceInviteService._effective_status``),
not a fourth stored value that would need a background job to set.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.workspace import Workspace


class WorkspaceInviteMethod(str, enum.Enum):
    EMAIL = "email"
    GITHUB = "github"
    LINK = "link"


class WorkspaceInviteStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"


class WorkspaceInvite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_invites"
    __table_args__ = (
        UniqueConstraint("token", name="uq_workspace_invites_token"),
        Index("ix_workspace_invites_workspace_id", "workspace_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    inviter_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    method: Mapped[WorkspaceInviteMethod] = mapped_column(
        Enum(
            WorkspaceInviteMethod,
            name="workspace_invite_method",
            native_enum=False,
            length=16,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    github_username: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # URL-safe random token, the invite's actual credential.
    token: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[WorkspaceInviteStatus] = mapped_column(
        Enum(
            WorkspaceInviteStatus,
            name="workspace_invite_status",
            native_enum=False,
            length=16,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=WorkspaceInviteStatus.PENDING,
        server_default=WorkspaceInviteStatus.PENDING.value,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_by: Mapped[str | None] = mapped_column(String(256), nullable=True)

    workspace: Mapped[Workspace] = relationship("Workspace")

    def __repr__(self) -> str:
        return (
            f"WorkspaceInvite(id={self.id!s}, workspace_id={self.workspace_id!s}, "
            f"method={self.method.value!r}, status={self.status.value!r})"
        )
