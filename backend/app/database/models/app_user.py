"""Application users for JWT session auth (Wave 2)."""

from __future__ import annotations

from sqlalchemy import Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AppUser(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Registered console operator. ``owner_identity`` matches run ownership."""

    __tablename__ = "app_users"
    __table_args__ = (
        UniqueConstraint("owner_identity", name="uq_app_users_owner_identity"),
        Index("ix_app_users_owner_identity", "owner_identity"),
    )

    owner_identity: Mapped[str] = mapped_column(String(256), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    def __repr__(self) -> str:
        return f"AppUser(id={self.id!s}, owner_identity={self.owner_identity!r})"
