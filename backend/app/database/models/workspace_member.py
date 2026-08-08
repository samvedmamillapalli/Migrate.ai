"""A user's membership in a workspace — roster only.

Deliberately scoped: a member appears in the workspace's people list and
can be removed, but membership does **not** grant access to that
workspace's migration runs — every run-scoped route still checks
``MigrationRun.owner_identity`` exactly, unchanged. Widening that is a real
security-boundary decision (a different, larger change than this one),
tracked as a possible follow-up, not something to do silently as a side
effect of adding an invite feature.

What membership *does* grant: the workspace shows up in the member's
``GET /workspaces`` list and ``GET /workspaces/{id}`` resolves for them
(read-only) — otherwise "accept an invite" would be a dead end with nothing
to show for it.
"""

from __future__ import annotations

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.workspace import Workspace


class WorkspaceMemberRole(str, enum.Enum):
    OWNER = "owner"
    MEMBER = "member"


class WorkspaceMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "user_identity", name="uq_workspace_members_workspace_user"
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Plain string, matching owner_identity everywhere else in this codebase
    # — not a foreign key to app_users, which is confirmed dead code.
    user_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[WorkspaceMemberRole] = mapped_column(
        Enum(
            WorkspaceMemberRole,
            name="workspace_member_role",
            native_enum=False,
            length=16,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=WorkspaceMemberRole.MEMBER,
        server_default=WorkspaceMemberRole.MEMBER.value,
    )

    workspace: Mapped[Workspace] = relationship("Workspace")

    def __repr__(self) -> str:
        return (
            f"WorkspaceMember(id={self.id!s}, workspace_id={self.workspace_id!s}, "
            f"user_identity={self.user_identity!r}, role={self.role.value!r})"
        )
