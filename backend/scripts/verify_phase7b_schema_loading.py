"""Phase 7B verification: load a schema snapshot onto a real shadow cluster and
prove the recreated database matches the snapshot.

Flow: provision a real Basic cluster -> create SQL user -> recreate the schema
(schemas, tables, columns, PKs, FKs, indexes, UNIQUE/CHECK constraints) from a
Phase 6 DatabaseMetadata snapshot -> re-inspect the shadow -> compare against
the snapshot element by element -> destroy the cluster (always).

Prints PASS/FAIL for every comparison category. Exits non-zero on any mismatch.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import get_settings
from app.schema_analysis.analyzer import SchemaAnalyzer
from app.schema_analysis.models import (
    ColumnMetadata,
    ConstraintMetadata,
    DatabaseMetadata,
    ForeignKeyMetadata,
    IndexMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.shadow.ccloud_api_provider import CCloudApiShadowProvider
from app.shadow.models import ProvisionSpec
from app.shadow.schema_compare import compare_snapshots
from app.shadow.schema_loader import ShadowSchemaLoader


def _snapshot() -> DatabaseMetadata:
    """A representative customer snapshot with PK, FK, UNIQUE, CHECK, indexes."""
    customers = TableMetadata(
        name="customers", schema_name="public", column_count=4,
        columns=[
            ColumnMetadata(name="id", data_type="uuid", udt_name="uuid",
                           is_nullable=False, ordinal_position=1, is_primary_key=True),
            ColumnMetadata(name="email", data_type="character varying", udt_name="varchar",
                           is_nullable=False, ordinal_position=2, character_maximum_length=255),
            ColumnMetadata(name="status", data_type="character varying", udt_name="varchar",
                           is_nullable=False, ordinal_position=3, character_maximum_length=20),
            ColumnMetadata(name="created_at", data_type="timestamp with time zone",
                           udt_name="timestamptz", is_nullable=False, ordinal_position=4),
        ],
        primary_key=["id"], foreign_keys=[],
        indexes=[
            IndexMetadata(name="customers_pkey", columns=["id"], is_unique=True, is_primary=True),
            IndexMetadata(name="customers_created_idx", columns=["created_at"], is_unique=False),
        ],
        constraints=[
            ConstraintMetadata(name="customers_email_key", constraint_type="UNIQUE",
                               columns=["email"]),
            ConstraintMetadata(name="customers_status_check", constraint_type="CHECK",
                               columns=["status"],
                               definition="status IN ('active','inactive')"),
        ],
        estimated_row_count=0,
    )
    orders = TableMetadata(
        name="orders", schema_name="public", column_count=4,
        columns=[
            ColumnMetadata(name="id", data_type="uuid", udt_name="uuid",
                           is_nullable=False, ordinal_position=1, is_primary_key=True),
            ColumnMetadata(name="customer_id", data_type="uuid", udt_name="uuid",
                           is_nullable=False, ordinal_position=2),
            ColumnMetadata(name="amount", data_type="numeric", udt_name="numeric",
                           is_nullable=False, ordinal_position=3),
            ColumnMetadata(name="placed_at", data_type="timestamp with time zone",
                           udt_name="timestamptz", is_nullable=True, ordinal_position=4),
        ],
        primary_key=["id"],
        foreign_keys=[
            ForeignKeyMetadata(name="orders_customer_fk", constrained_columns=["customer_id"],
                               referred_schema="public", referred_table="customers",
                               referred_columns=["id"]),
        ],
        indexes=[
            IndexMetadata(name="orders_pkey", columns=["id"], is_unique=True, is_primary=True),
            IndexMetadata(name="orders_customer_idx", columns=["customer_id"], is_unique=False),
        ],
        constraints=[],
        estimated_row_count=0,
    )
    schema = SchemaMetadata(name="public", tables=[customers, orders], table_count=2)
    return DatabaseMetadata(
        database_name="sample_customer_db", server_version="CockroachDB (sample)",
        schemas=[schema], schema_count=1, table_count=2, inspected_at=datetime.now(UTC),
    )


async def main() -> None:
    settings = get_settings()
    if settings.ccloud_api_secret is None:
        print(json.dumps({"ok": False, "error": "CCLOUD_API_SECRET not set"}))
        raise SystemExit(1)

    provider = CCloudApiShadowProvider(
        api_secret=settings.ccloud_api_secret.get_secret_value(),
        base_url=settings.ccloud_api_base_url, plan=settings.shadow_cluster_plan,
        provider_cloud="AWS",
        timeout_seconds=settings.ccloud_api_timeout_seconds,
        max_retries=settings.ccloud_api_max_retries,
        backoff_base_seconds=settings.ccloud_api_backoff_base_seconds,
    )
    snapshot = _snapshot()
    report: dict[str, Any] = {"ok": False}
    cluster_id = None
    try:
        spec = ProvisionSpec(run_id=uuid.uuid4(), cluster_name="",
                             app_tag=settings.shadow_app_tag, cloud="AWS",
                             region=settings.shadow_cluster_region)
        t0 = time.perf_counter()
        handle = await provider.create(spec)
        cluster_id = handle.cluster_id
        await provider.await_ready(handle, timeout_seconds=settings.shadow_provision_timeout_seconds,
                                   poll_interval_seconds=settings.shadow_ready_poll_interval_seconds)
        report["provision_seconds"] = round(time.perf_counter() - t0, 1)
        await provider.provision_sql_access(handle)

        t1 = time.perf_counter()
        load = await ShadowSchemaLoader().load(handle.connection_url, snapshot)
        report["schema_load_seconds"] = round(time.perf_counter() - t1, 1)
        report["loaded"] = {
            "tables": load.tables_created, "columns": load.columns_created,
            "primary_keys": load.primary_keys_created, "indexes": load.indexes_created,
            "foreign_keys": load.foreign_keys_created, "constraints": load.constraints_created,
            "warnings": load.warnings,
        }

        actual = await SchemaAnalyzer().analyze(handle.connection_url)
        cmp = compare_snapshots(snapshot, actual)
        report["comparison"] = {
            "schemas": cmp.schemas_ok, "tables": cmp.tables_ok, "columns": cmp.columns_ok,
            "primary_keys": cmp.primary_keys_ok, "foreign_keys": cmp.foreign_keys_ok,
            "indexes": cmp.indexes_ok, "constraints": cmp.constraints_ok,
            "mismatches": cmp.mismatches,
        }
        report["ok"] = cmp.matched
    finally:
        if cluster_id:
            await provider.destroy(cluster_id=cluster_id)
            report["cluster_destroyed"] = True
        await provider.aclose()

    print(json.dumps(report, indent=2, default=str))
    print("\n=== PHASE 7B CHECKLIST ===")
    c = report.get("comparison", {})
    labels = [
        ("Schemas recreated", "schemas"), ("Tables recreated", "tables"),
        ("Columns recreated", "columns"), ("PKs recreated", "primary_keys"),
        ("FKs recreated", "foreign_keys"), ("Indexes recreated", "indexes"),
        ("Constraints recreated", "constraints"),
    ]
    for label, key in labels:
        print(f"{'[PASS]' if c.get(key) else '[FAIL]'} {label}")
    print(f"{'[PASS]' if report['ok'] else '[FAIL]'} Snapshot matches recreated database")
    print(f"{'[PASS]' if report.get('cluster_destroyed') else '[FAIL]'} Cluster destroyed afterwards")
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
