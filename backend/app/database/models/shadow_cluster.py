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
    from app.database.models.migration_run import MigrationRun


class ShadowClusterStatus(str, enum.Enum):
    PROVISIONING = "provisioning"
    READY = "ready"
    RUNNING = "running"
    DESTROYING = "destroying"
    DESTROYED = "destroyed"
    FAILED = "failed"


class ShadowCluster(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Metadata for the temporary CockroachDB cluster used during verification."""

    __tablename__ = "shadow_clusters"
    __table_args__ = (
        UniqueConstraint(
            "migration_run_id",
            name="uq_shadow_clusters_migration_run_id",
        ),
        UniqueConstraint(
            "cluster_id",
            name="uq_shadow_clusters_cluster_id",
        ),
        Index("ix_shadow_clusters_status", "status"),
        Index("ix_shadow_clusters_created_at", "created_at"),
    )

    migration_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("migration_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    cluster_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="cockroachdb_cloud",
        server_default="cockroachdb_cloud",
    )
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ShadowClusterStatus] = mapped_column(
        Enum(
            ShadowClusterStatus,
            name="shadow_cluster_status",
            native_enum=False,
            length=32,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=ShadowClusterStatus.PROVISIONING,
        server_default=ShadowClusterStatus.PROVISIONING.value,
    )
    destroyed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    migration_run: Mapped[MigrationRun] = relationship(
        "MigrationRun",
        back_populates="shadow_cluster",
    )

    def __repr__(self) -> str:
        return (
            f"ShadowCluster(id={self.id!s}, cluster_id={self.cluster_id!r}, "
            f"status={self.status.value!r})"
        )
