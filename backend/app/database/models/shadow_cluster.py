from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.migration_run import MigrationRun


class ShadowClusterStatus(str, enum.Enum):
    """Lifecycle state of a disposable shadow cluster.

    The orchestration walks these states in order:
    PROVISIONING -> READY -> SEEDING -> MIGRATING -> DESTROYING -> DESTROYED.
    Any stage may transition to FAILED, after which teardown still runs and the
    row lands in DESTROYED (or FAILED if teardown itself could not complete).
    """

    PROVISIONING = "provisioning"
    READY = "ready"
    SEEDING = "seeding"
    MIGRATING = "migrating"
    DESTROYING = "destroying"
    DESTROYED = "destroyed"
    FAILED = "failed"


# States in which a shadow cluster may still be holding real cloud resources.
# Used for the concurrency cap and the orphan sweeper.
ACTIVE_SHADOW_STATUSES: frozenset[ShadowClusterStatus] = frozenset(
    {
        ShadowClusterStatus.PROVISIONING,
        ShadowClusterStatus.READY,
        ShadowClusterStatus.SEEDING,
        ShadowClusterStatus.MIGRATING,
        ShadowClusterStatus.DESTROYING,
    }
)

TERMINAL_SHADOW_STATUSES: frozenset[ShadowClusterStatus] = frozenset(
    {
        ShadowClusterStatus.DESTROYED,
        ShadowClusterStatus.FAILED,
    }
)


class ShadowCluster(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Metadata for the temporary CockroachDB cluster used during verification.

    Credentials for the shadow cluster are never persisted here; only the
    non-secret identity (provider cluster id, human-readable name, region) and
    lifecycle bookkeeping are stored. The connection string lives in memory for
    the duration of a single lifecycle run.
    """

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
        Index("ix_shadow_clusters_expires_at", "expires_at"),
    )

    migration_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("migration_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Nullable because the row is created (PROVISIONING) before the provider
    # returns a cluster id, so the sweeper/concurrency accounting can already
    # see the in-flight cluster. A UNIQUE constraint still allows many NULLs.
    cluster_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Human-readable, app-tagged name we assign at creation (e.g.
    # "mo-shadow-<run-short>"). This is what the sweeper matches on to find
    # orphans belonging to this application.
    cluster_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
    # Synthetic-data sizing tier chosen from the Phase 6 snapshot row counts.
    scale_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Max-lifetime deadline (created_at + configured lifetime). The sweeper
    # reaps any active app-tagged cluster past this, catching processes that
    # died before teardown.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Per-stage wall-clock timings (provision/ready/seed/migrate/teardown), in
    # milliseconds. Provisioning latency is a real unknown, so we always record
    # measured numbers rather than assume them.
    stage_timings: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    destroyed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # Append-only observation log: one entry per status transition or timing
    # merge, each `{"at": iso timestamp, "status": ..., "stage_timings": {...}}`.
    # Lets a finished run be replayed step by step instead of only showing the
    # final overwritten state (status/stage_timings above remain last-write-wins
    # for cheap reads; this is the durable history behind them).
    event_log: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # Structural DatabaseMetadata (see app.schema_analysis.models) captured on
    # the shadow cluster immediately before and after the migration runs, for
    # the before/after schema diff. Never captured on the customer's database.
    schema_snapshot_before: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    schema_snapshot_after: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    # Small real row sample (columns + up to 20 rows + total count) for the
    # tables the migration references, captured in the same connection as the
    # schema snapshot above. Shadow-tier synthetic data, never the customer's
    # real rows. `after` re-fetches the same primary keys as `before` where
    # possible so the panel compares the same conceptual rows, not an
    # arbitrary new sample. None when capture wasn't attempted or failed
    # outright; per-table `error` inside the JSON when only one table failed.
    row_sample_before: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    row_sample_after: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
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
