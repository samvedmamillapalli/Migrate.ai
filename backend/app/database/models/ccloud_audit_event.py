"""CockroachDB Cloud audit-log entries fetched via the ccloud CLI.

Independent corroboration of a shadow run's cluster lifecycle — sourced from
the Cloud control plane's own audit log (``ccloud audit list``), not from
anything the migration or the MCP investigation touches. See
docs/cockroach_hookup.md §4 "Feature 1".

Deliberately no relationship back-populated onto MigrationRun and no vector
column: this is many-per-run structured audit data with no semantic-search
use case, queried directly by migration_run_id.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class CCloudAuditEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ccloud_audit_events"
    __table_args__ = (
        Index("ix_ccloud_audit_events_migration_run_id", "migration_run_id"),
        Index("ix_ccloud_audit_events_occurred_at", "occurred_at"),
    )

    migration_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("migration_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(nullable=False)
    actor: Mapped[str | None] = mapped_column(nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)

    def __repr__(self) -> str:
        return (
            "CCloudAuditEvent("
            f"id={self.id!s}, migration_run_id={self.migration_run_id!s}, "
            f"event_type={self.event_type!r})"
        )
