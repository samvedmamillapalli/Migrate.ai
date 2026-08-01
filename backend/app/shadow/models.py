from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.shadow.schema_loader import SchemaLoadReport


class ScaleTier(str, enum.Enum):
    """Synthetic-data sizing tier, chosen from the Phase 6 snapshot row counts.

    Row volumes are hard-capped per tier so a shadow run stays comfortably
    inside CockroachDB Basic free usage. See ``select_scale_tier``.
    """

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


# Per-table synthetic row caps. These are deliberately modest: the point is to
# measure how a schema change behaves (backfill duration, storage growth,
# resource saturation, rollback safety) at a representative scale, not to mirror
# production volume.
TIER_ROW_CAPS: dict[ScaleTier, int] = {
    ScaleTier.SMALL: 1_000,
    ScaleTier.MEDIUM: 10_000,
    ScaleTier.LARGE: 50_000,
}


def select_scale_tier(total_estimated_rows: int | None) -> ScaleTier:
    """Map the customer's total estimated row count onto a capped tier."""
    if total_estimated_rows is None or total_estimated_rows <= 1_000:
        return ScaleTier.SMALL
    if total_estimated_rows <= 100_000:
        return ScaleTier.MEDIUM
    return ScaleTier.LARGE


@dataclass(frozen=True)
class ProvisionSpec:
    """Everything a provider needs to create a tagged shadow cluster."""

    run_id: uuid.UUID
    cluster_name: str
    app_tag: str
    cloud: str
    region: str


class ProvisionedCluster:
    """A live shadow cluster handle.

    ``connection_url`` contains a password and must never be logged or
    persisted. It lives in memory for the duration of one lifecycle run.
    """

    __slots__ = ("_connection_url", "cluster_id", "cluster_name", "region")

    def __init__(
        self,
        *,
        cluster_id: str,
        cluster_name: str,
        region: str,
        connection_url: str,
    ) -> None:
        self.cluster_id = cluster_id
        self.cluster_name = cluster_name
        self.region = region
        self._connection_url = connection_url

    @property
    def connection_url(self) -> str:
        return self._connection_url

    def attach_connection_url(self, url: str) -> None:
        """Populate the connection URL once SQL access has been provisioned.

        Some providers (e.g. the REST API) only know the connection string after
        the cluster is ready and a SQL user exists.
        """
        self._connection_url = url

    def __repr__(self) -> str:
        # Never expose the connection string (it carries a password).
        return (
            "ProvisionedCluster("
            f"cluster_id={self.cluster_id!r}, "
            f"cluster_name={self.cluster_name!r}, region={self.region!r}, "
            "connection_url=***)"
        )


@dataclass(frozen=True)
class RemoteCluster:
    """A cluster as seen by the provider's list command (used by the sweeper)."""

    cluster_id: str
    cluster_name: str
    created_at: datetime | None = None


@dataclass
class StageTimings:
    """Measured wall-clock duration (ms) for each lifecycle stage.

    Provisioning latency is the single biggest unknown in this phase, so every
    stage is measured for real rather than assumed.
    """

    provision_ms: float | None = None
    ready_ms: float | None = None
    seed_ms: float | None = None
    migrate_ms: float | None = None
    teardown_ms: float | None = None

    def as_dict(self) -> dict[str, float | None]:
        return {
            "provision_ms": self.provision_ms,
            "ready_ms": self.ready_ms,
            "seed_ms": self.seed_ms,
            "migrate_ms": self.migrate_ms,
            "teardown_ms": self.teardown_ms,
        }


@dataclass
class SeedReport:
    """Outcome of recreating the schema shape and loading synthetic rows.

    Retained for the optional offline ``ShadowSeeder`` path only. The default
    real-cluster lifecycle uses ``app.shadow.schema_loader.SchemaLoadReport``
    instead (see ``LifecycleReport.seed``).
    """

    scale_tier: ScaleTier
    tables_created: int = 0
    indexes_created: int = 0
    rows_inserted: int = 0
    per_table_rows: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class LifecycleReport:
    """Full result of a create -> seed -> migrate -> destroy run.

    ``seed`` holds a ``SchemaLoadReport`` (real schema/FK/constraint
    recreation, no synthetic rows) on the default ``ccloud_api`` path, or a
    legacy ``SeedReport`` if the optional offline mock provider/seeder was used
    instead.
    """

    run_id: uuid.UUID
    cluster_id: str | None
    cluster_name: str
    scale_tier: ScaleTier | None
    succeeded: bool
    torn_down: bool
    timings: StageTimings
    seed: "SchemaLoadReport | SeedReport | None" = None
    migration_duration_seconds: float | None = None
    storage_growth_mb: float | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": str(self.run_id),
            "cluster_id": self.cluster_id,
            "cluster_name": self.cluster_name,
            "scale_tier": self.scale_tier.value if self.scale_tier else None,
            "succeeded": self.succeeded,
            "torn_down": self.torn_down,
            "timings": self.timings.as_dict(),
            "seed": self._seed_as_dict(),
            "migration_duration_seconds": self.migration_duration_seconds,
            "storage_growth_mb": self.storage_growth_mb,
            "error": self.error,
        }

    def _seed_as_dict(self) -> dict[str, object] | None:
        if self.seed is None:
            return None
        if isinstance(self.seed, SeedReport):
            return {
                "kind": "synthetic_seed",
                "scale_tier": self.seed.scale_tier.value,
                "tables_created": self.seed.tables_created,
                "indexes_created": self.seed.indexes_created,
                "rows_inserted": self.seed.rows_inserted,
                "per_table_rows": self.seed.per_table_rows,
            }
        return {
            "kind": "schema_load",
            "schemas_created": self.seed.schemas_created,
            "tables_created": self.seed.tables_created,
            "columns_created": self.seed.columns_created,
            "primary_keys_created": self.seed.primary_keys_created,
            "indexes_created": self.seed.indexes_created,
            "foreign_keys_created": self.seed.foreign_keys_created,
            "constraints_created": self.seed.constraints_created,
            "warnings": self.seed.warnings,
        }
