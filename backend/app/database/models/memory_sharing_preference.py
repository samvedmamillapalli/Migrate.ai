"""Per-account opt-in for cross-customer memory sharing — docs/cross_customer.md §2.

One row per ``owner_identity``. Default OFF (Hard Constraint 1): a row's
absence, or ``cross_customer_sharing_enabled=False``, both mean "do not
share" — the promotion pipeline treats "no row" and "row says false"
identically, never as an implicit opt-in.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.mixins import TimestampMixin


class MemorySharingPreference(TimestampMixin, Base):
    """Consent record for contributing anonymized outcomes to the shared pool."""

    __tablename__ = "memory_sharing_preferences"

    owner_identity: Mapped[str] = mapped_column(
        String(256), primary_key=True
    )
    cross_customer_sharing_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    enabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            "MemorySharingPreference("
            f"owner_identity={self.owner_identity!r}, "
            f"enabled={self.cross_customer_sharing_enabled})"
        )
