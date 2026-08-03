"""Slack workspace installations for the Migration Oracle Slack integration."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SlackInstallation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One Slack workspace installation, owned by an application user.

    ``bot_access_token`` is stored encrypted at rest (Fernet) whenever
    ``SLACK_TOKEN_ENCRYPTION_KEY`` is configured. The Slack API never exposes
    this token back out of this system.
    """

    __tablename__ = "slack_installations"
    __table_args__ = (
        UniqueConstraint("owner_identity", name="uq_slack_installations_owner_identity"),
        Index("ix_slack_installations_owner_identity", "owner_identity"),
    )

    owner_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    team_id: Mapped[str] = mapped_column(String(64), nullable=False)
    team_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    bot_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Slack user ID of the person who completed the OAuth install
    # (``authed_user.id`` in the token-exchange response). Lifecycle
    # notifications DM this user directly rather than posting to a
    # hardcoded channel name — see SlackNotificationService.send_message.
    # Nullable so pre-existing rows (installed before this column existed)
    # degrade to the SLACK_DEFAULT_CHANNEL fallback instead of failing.
    authed_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Stored encrypted when SLACK_TOKEN_ENCRYPTION_KEY is set; otherwise
    # plaintext with a startup warning (may be acceptable in dev only).
    bot_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(1024), nullable=False)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"SlackInstallation(id={self.id!s}, "
            f"owner_identity={self.owner_identity!r}, team_id={self.team_id!r})"
        )
