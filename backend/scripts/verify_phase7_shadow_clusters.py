"""Phase 7 verification: shadow cluster orchestration.

Exercises the full lifecycle end to end and prints clear pass/fail output with
measured per-stage timings, so the checkpoint can be validated by hand before
Phase 8 wraps it in Step Functions.

What it checks:
  1. Full lifecycle: create -> await ready -> seed -> run migration -> destroy,
     with real per-stage timings (provisioning latency is measured, not assumed).
  2. Idempotent teardown: destroying an already-destroyed cluster succeeds.
  3. Concurrency cap of 2: a third simultaneous run is refused a slot.
  4. Guaranteed teardown on the failure path: a broken migration still tears the
     cluster down (no leak).
  5. Sweeper: an expired DB-tracked cluster and an old provider-tagged orphan are
     both reaped.

Provider is chosen by SHADOW_PROVIDER. The default "mock" provisions an isolated
scratch database on the control-plane cluster, so this runs offline with no
ccloud install or API key. Set SHADOW_PROVIDER=ccloud (plus a real CCLOUD_API_KEY)
to validate the same flow against real CockroachDB Cloud.

Blast radius of a migration is reported as backfill duration / storage growth,
never as lock duration: CockroachDB runs schema changes as online background jobs.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import traceback
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.database import DatabaseSessionManager
from app.database.models import ShadowClusterStatus
from app.database.session import normalize_database_url
from app.repositories.migration_run_repository import MigrationRunRepository
from app.repositories.shadow_cluster_repository import ShadowClusterRepository
from app.schema_analysis.models import (
    ColumnMetadata,
    DatabaseMetadata,
    IndexMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.services.migration_run_service import MigrationRunService
from app.services.shadow_cluster_service import ShadowClusterService
from app.shadow.concurrency import acquire_slot
from app.shadow.factory import create_shadow_provider
from app.shadow.models import ProvisionSpec, ScaleTier
from app.shadow.orchestrator import ShadowClusterOrchestrator
from app.shadow.sweeper import ShadowClusterSweeper


class CheckError(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CheckError(message)


def _sample_metadata() -> DatabaseMetadata:
    """A small, self-contained customer schema snapshot to recreate + seed."""
    customers = TableMetadata(
        name="customers",
        schema_name="public",
        column_count=4,
        columns=[
            ColumnMetadata(
                name="id", data_type="uuid", udt_name="uuid",
                is_nullable=False, ordinal_position=1, is_primary_key=True,
            ),
            ColumnMetadata(
                name="email", data_type="character varying", udt_name="varchar",
                is_nullable=False, ordinal_position=2,
                character_maximum_length=255,
            ),
            ColumnMetadata(
                name="created_at", data_type="timestamp with time zone",
                udt_name="timestamptz", is_nullable=False, ordinal_position=3,
            ),
            ColumnMetadata(
                name="is_active", data_type="boolean", udt_name="bool",
                is_nullable=False, ordinal_position=4,
            ),
        ],
        primary_key=["id"],
        foreign_keys=[],
        indexes=[
            IndexMetadata(
                name="customers_pkey", columns=["id"], is_unique=True,
                is_primary=True,
            ),
            IndexMetadata(
                name="customers_email_key", columns=["email"], is_unique=True,
            ),
        ],
        constraints=[],
        estimated_row_count=500,
    )
    orders = TableMetadata(
        name="orders",
        schema_name="public",
        column_count=4,
        columns=[
            ColumnMetadata(
                name="id", data_type="uuid", udt_name="uuid",
                is_nullable=False, ordinal_position=1, is_primary_key=True,
            ),
            ColumnMetadata(
                name="customer_id", data_type="uuid", udt_name="uuid",
                is_nullable=False, ordinal_position=2,
            ),
            ColumnMetadata(
                name="amount", data_type="numeric", udt_name="numeric",
                is_nullable=False, ordinal_position=3,
            ),
            ColumnMetadata(
                name="placed_at", data_type="timestamp with time zone",
                udt_name="timestamptz", is_nullable=True, ordinal_position=4,
            ),
        ],
        primary_key=["id"],
        foreign_keys=[],
        indexes=[
            IndexMetadata(
                name="orders_pkey", columns=["id"], is_unique=True,
                is_primary=True,
            ),
            IndexMetadata(name="orders_customer_id_idx", columns=["customer_id"],
                          is_unique=False),
        ],
        constraints=[],
        estimated_row_count=800,
    )
    schema = SchemaMetadata(name="public", tables=[customers, orders], table_count=2)
    return DatabaseMetadata(
        database_name="sample_customer_db",
        server_version="CockroachDB CCL (sample)",
        schemas=[schema],
        schema_count=1,
        table_count=2,
        inspected_at=datetime.now(UTC),
    )


async def _new_run(database: DatabaseSessionManager, sql: str) -> uuid.UUID:
    async for session in database.session():
        service = MigrationRunService(
            repository=MigrationRunRepository(session), session=session
        )
        run = await service.create_migration_run(sql)
        return run.id
    raise RuntimeError("no session")


async def _delete_run(database: DatabaseSessionManager, run_id: uuid.UUID) -> None:
    async for session in database.session():
        service = MigrationRunService(
            repository=MigrationRunRepository(session), session=session
        )
        try:
            await service.delete_migration_run(run_id)
        except Exception:  # noqa: BLE001
            pass
        return


async def _admin_execute(admin_url: str, statement: str) -> None:
    engine = create_async_engine(normalize_database_url(admin_url), pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            ac = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await ac.execute(text(statement))
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------


async def test_full_lifecycle(database: DatabaseSessionManager) -> dict[str, Any]:
    settings = get_settings()
    metadata = _sample_metadata()
    migration_sql = (
        "ALTER TABLE customers ADD COLUMN loyalty_points INT8 NOT NULL DEFAULT 0"
    )
    run_id = await _new_run(database, migration_sql)
    provider = create_shadow_provider(settings)
    try:
        async for session in database.session():
            service = ShadowClusterService(
                repository=ShadowClusterRepository(session), session=session
            )
            orchestrator = ShadowClusterOrchestrator(
                service=service, provider=provider, settings=settings
            )
            report = await orchestrator.run_lifecycle(
                run_id=run_id,
                metadata=metadata,
                migration_sql=migration_sql,
                scale_tier=ScaleTier.SMALL,
            )
            break

        check(report.succeeded, f"lifecycle did not succeed: {report.error}")
        check(report.torn_down, "cluster was not torn down")
        check(report.seed is not None, "no schema-load report")
        check(report.seed.tables_created > 0, "no tables recreated")
        check(report.timings.seed_ms is not None, "seed not timed")
        check(report.migration_duration_seconds is not None, "migration not timed")

        # Confirm the row landed in DESTROYED with recorded timings.
        async for session in database.session():
            service = ShadowClusterService(
                repository=ShadowClusterRepository(session), session=session
            )
            row = await service.get_by_run(run_id)
            check(row is not None, "shadow row missing")
            check(
                row.status == ShadowClusterStatus.DESTROYED,
                f"final status is {row.status.value}, expected destroyed",
            )
            check(row.stage_timings is not None, "stage timings not persisted")
            check(row.destroyed_at is not None, "destroyed_at not set")
            break
    finally:
        await provider.aclose()
        await _delete_run(database, run_id)

    return {
        "succeeded": report.succeeded,
        "torn_down": report.torn_down,
        "scale_tier": report.scale_tier.value,
        "tables_created": report.seed.tables_created,
        "indexes_created": report.seed.indexes_created,
        "foreign_keys_created": report.seed.foreign_keys_created,
        "constraints_created": report.seed.constraints_created,
        "migration_duration_seconds": report.migration_duration_seconds,
        "storage_growth_mb": report.storage_growth_mb,
        "timings_ms": report.timings.as_dict(),
    }


async def test_idempotent_teardown() -> dict[str, Any]:
    settings = get_settings()
    provider = create_shadow_provider(settings)
    try:
        spec = ProvisionSpec(
            run_id=uuid.uuid4(),
            cluster_name=f"{settings.shadow_app_tag}-idem",
            app_tag=settings.shadow_app_tag,
            cloud=settings.shadow_cluster_cloud,
            region=settings.shadow_cluster_region,
        )
        cluster = await provider.create(spec)
        first = await provider.destroy(cluster_id=cluster.cluster_id)
        second = await provider.destroy(cluster_id=cluster.cluster_id)
        third = await provider.destroy(cluster_id="never-existed-cluster")
        check(first and second and third, "destroy was not idempotent")
    finally:
        await provider.aclose()
    return {"destroy_twice_ok": True, "destroy_unknown_ok": True}


async def test_concurrency_cap(database: DatabaseSessionManager) -> dict[str, Any]:
    settings = get_settings()
    run_ids = [await _new_run(database, f"SELECT {i}") for i in range(3)]
    admitted: list[bool] = []
    try:
        async for session in database.session():
            service = ShadowClusterService(
                repository=ShadowClusterRepository(session), session=session
            )
            for run_id in run_ids:
                row = await service.try_admit(
                    run_id=run_id,
                    region=settings.shadow_cluster_region,
                    provider="mock",
                    scale_tier="small",
                    max_concurrent=2,
                    max_lifetime_minutes=30,
                )
                admitted.append(row is not None)
            break
        check(admitted == [True, True, False],
              f"expected [True, True, False], got {admitted}")

        # Overflow run must wait, then time out quickly when no slot frees.
        timed_out = False
        try:
            async for session in database.session():
                service = ShadowClusterService(
                    repository=ShadowClusterRepository(session), session=session
                )
                await acquire_slot(
                    service,
                    run_id=run_ids[2],
                    region=settings.shadow_cluster_region,
                    provider="mock",
                    scale_tier="small",
                    max_concurrent=2,
                    max_lifetime_minutes=30,
                    wait_timeout_seconds=1,
                    poll_interval_seconds=0.2,
                )
                break
        except Exception as exc:  # SlotAcquisitionTimeout
            timed_out = "slot" in str(exc).lower()
        check(timed_out, "overflow run did not queue/timeout as expected")
    finally:
        for run_id in run_ids:
            await _delete_run(database, run_id)
    return {"admitted": admitted, "overflow_queued_and_timed_out": True}


async def test_failure_path_teardown(database: DatabaseSessionManager) -> dict[str, Any]:
    settings = get_settings()
    metadata = _sample_metadata()
    # Deliberately broken migration: references a table that was never seeded.
    migration_sql = "ALTER TABLE table_that_does_not_exist ADD COLUMN x INT8"
    run_id = await _new_run(database, migration_sql)
    provider = create_shadow_provider(settings)
    try:
        async for session in database.session():
            service = ShadowClusterService(
                repository=ShadowClusterRepository(session), session=session
            )
            orchestrator = ShadowClusterOrchestrator(
                service=service, provider=provider, settings=settings
            )
            report = await orchestrator.run_lifecycle(
                run_id=run_id,
                metadata=metadata,
                migration_sql=migration_sql,
                scale_tier=ScaleTier.SMALL,
            )
            break

        check(not report.succeeded, "broken migration unexpectedly succeeded")
        check(report.error is not None, "no error recorded for failed migration")
        check(report.torn_down, "cluster leaked on failure path (not torn down)")

        async for session in database.session():
            service = ShadowClusterService(
                repository=ShadowClusterRepository(session), session=session
            )
            row = await service.get_by_run(run_id)
            check(
                row.status == ShadowClusterStatus.DESTROYED,
                f"failure-path final status is {row.status.value}",
            )
            check(row.error_message is not None, "error_message not persisted")
            break
    finally:
        await provider.aclose()
        await _delete_run(database, run_id)

    return {
        "succeeded": report.succeeded,
        "torn_down": report.torn_down,
        "error": report.error,
    }


async def test_sweeper(database: DatabaseSessionManager) -> dict[str, Any]:
    settings = get_settings()
    admin_url = settings.database_url.get_secret_value()
    provider = create_shadow_provider(settings)

    # (a) DB-driven: an active shadow row whose max lifetime has already passed.
    run_id = await _new_run(database, "SELECT 'sweep'")
    async for session in database.session():
        service = ShadowClusterService(
            repository=ShadowClusterRepository(session), session=session
        )
        row = await service.try_admit(
            run_id=run_id,
            region=settings.shadow_cluster_region,
            provider="mock",
            scale_tier="small",
            max_concurrent=2,
            max_lifetime_minutes=30,
        )
        shadow_id = row.id
        break
    # Force it to look expired.
    await _admin_execute(
        admin_url,
        "UPDATE shadow_clusters SET expires_at = '2000-01-01T00:00:00Z' "
        f"WHERE id = '{shadow_id}'",
    )

    # (b) Provider-driven: an old app-tagged orphan scratch DB (name carries an
    #     epoch ~2 hours in the past, so it is older than the max lifetime).
    old_epoch = int(time.time()) - 7200
    orphan_db = f"migration_oracle_sweep0001_{old_epoch}"
    await _admin_execute(admin_url, f'CREATE DATABASE IF NOT EXISTS "{orphan_db}"')

    swept: dict[str, Any] = {}
    try:
        async for session in database.session():
            service = ShadowClusterService(
                repository=ShadowClusterRepository(session), session=session
            )
            sweeper = ShadowClusterSweeper(
                service=service,
                provider=provider,
                app_tag=settings.shadow_app_tag,
                max_lifetime_minutes=settings.shadow_max_lifetime_minutes,
            )
            swept = await sweeper.sweep()
            break

        check(str(shadow_id) in swept["swept_db_rows"], "expired DB row not swept")

        async for session in database.session():
            service = ShadowClusterService(
                repository=ShadowClusterRepository(session), session=session
            )
            row = await service.get(shadow_id)
            check(
                row.status == ShadowClusterStatus.DESTROYED,
                f"swept row status is {row.status.value}",
            )
            break

        # Confirm the old orphan database was actually dropped.
        engine = create_async_engine(normalize_database_url(admin_url))
        try:
            async with engine.connect() as conn:
                dbs = [
                    str(r[0])
                    for r in (await conn.execute(text("SHOW DATABASES"))).all()
                ]
        finally:
            await engine.dispose()
        check(orphan_db not in dbs, "old orphan scratch DB was not reaped")
    finally:
        await provider.aclose()
        await _admin_execute(admin_url, f'DROP DATABASE IF EXISTS "{orphan_db}" CASCADE')
        await _delete_run(database, run_id)

    return {
        "swept_db_rows": len(swept.get("swept_db_rows", [])),
        "swept_provider_clusters": swept.get("swept_provider_clusters", []),
        "errors": swept.get("errors", []),
    }


async def main() -> None:
    settings = get_settings()
    report: dict[str, Any] = {"ok": False, "provider": settings.shadow_provider}
    database = DatabaseSessionManager(settings.database_url.get_secret_value())
    try:
        report["full_lifecycle"] = await test_full_lifecycle(database)
        report["idempotent_teardown"] = await test_idempotent_teardown()
        report["concurrency_cap"] = await test_concurrency_cap(database)
        report["failure_path_teardown"] = await test_failure_path_teardown(database)
        report["sweeper"] = await test_sweeper(database)
        report["ok"] = True
    except Exception as exc:  # noqa: BLE001
        report["ok"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        print(json.dumps(report, indent=2, default=str))
        await database.close()
        raise SystemExit(1) from exc
    finally:
        await database.close()

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
