"""One linked GitHub identity per owner — "who is this GitHub identity" for
workspace-invite matching (a display name/avatar), distinct from the
GitHub App used for PR-integration webhooks in
app/database/models/github_pull_request_link.py. Different credential
shape entirely: this is a standard OAuth user-to-server access token,
scoped read:user only, never used to act on repos.

``access_token`` is stored encrypted at rest (Fernet) whenever
``GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY`` is configured, same convention as
``SlackInstallation.bot_access_token``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class GithubIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "github_identities"
    __table_args__ = (
        UniqueConstraint("owner_identity", name="uq_github_identities_owner_identity"),
    )

    owner_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    github_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    github_login: Mapped[str] = mapped_column(String(256), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Stored encrypted when GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY is set;
    # otherwise a dev-only derived key, same as SlackInstallation.
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(256), nullable=False)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"GithubIdentity(id={self.id!s}, owner_identity={self.owner_identity!r}, "
            f"github_login={self.github_login!r})"
        )
