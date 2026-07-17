"""Human-watchable demo of the real shadow-cluster feature end to end.

Unlike the verify_phase7*.py scripts (which assert pass/fail), this script is
for *watching* the production code path run against a real CockroachDB Cloud
cluster: ``ShadowClusterOrchestrator.run_lifecycle`` (create -> await ready ->
load real schema -> run migration -> destroy), exactly as the app itself will
call it once wired to an API route.

It prints each stage as it happens, the live cluster id, the persisted
ShadowCluster DB row before/after, and a final leak check.

Run:
    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\demo_shadow_lifecycle.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import get_settings
from app.database import DatabaseSessionManager
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
from app.shadow.factory import create_shadow_provider
from app.shadow.orchestrator import ShadowClusterOrchestrator


def _snapshot() -> DatabaseMetadata:
    customers = TableMetadata(
        name="customers", schema_name="public", column_count=2,
        columns=[
            ColumnMetadata(name="id", data_type="uuid", udt_name="uuid",
                           is_nullable=False, ordinal_position=1, is_primary_key=True),
            ColumnMetadata(name="email", data_type="character varying", udt_name="varchar",
                           is_nullable=False, ordinal_position=2, character_maximum_length=255),
        ],
        primary_key=["id"], foreign_keys=[],
        indexes=[IndexMetadata(name="customers_pkey", columns=["id"], is_unique=True, is_primary=True)],
        constraints=[], estimated_row_count=0,
    )
    schema = SchemaMetadata(name="public", tables=[customers], table_count=1)
    return DatabaseMetadata(
        database_name="demo_customer_db", server_version="CockroachDB (demo)",
        schemas=[schema], schema_count=1, table_count=1, inspected_at=datetime.now(UTC),
    )


async def main() -> None:
    settings = get_settings()
    print(f"SHADOW_PROVIDER = {settings.shadow_provider!r}  (this is what the app will use by default)")

    database = DatabaseSessionManager(settings.database_url.get_secret_value())
    migration_sql = "ALTER TABLE public.customers ADD COLUMN loyalty_points INT8 NOT NULL DEFAULT 0"

    async for session in database.session():
        run_service = MigrationRunService(
            repository=MigrationRunRepository(session), session=session
        )
        run = await run_service.create_migration_run(migration_sql)
        run_id = run.id
        break
    print(f"\n1) Created MigrationRun row: {run_id}  (status={run.status.value})")

    provider = create_shadow_provider(settings)
    try:
        async for session in database.session():
            shadow_service = ShadowClusterService(
                repository=ShadowClusterRepository(session), session=session
            )
            orchestrator = ShadowClusterOrchestrator(
                service=shadow_service, provider=provider, settings=settings
            )
            print("\n2) Running ShadowClusterOrchestrator.run_lifecycle(...)")
            print("   (provision -> await ready -> load real schema -> run migration -> destroy)")
            report = await orchestrator.run_lifecycle(
                run_id=run_id,
                metadata=_snapshot(),
                migration_sql=migration_sql,
            )
            break

        print("\n3) LifecycleReport:")
        print(json.dumps(report.as_dict(), indent=2, default=str))

        async for session in database.session():
            shadow_service = ShadowClusterService(
                repository=ShadowClusterRepository(session), session=session
            )
            row = await shadow_service.get_by_run(run_id)
            print("\n4) Persisted ShadowCluster row after the run:")
            print(
                json.dumps(
                    {
                        "id": str(row.id),
                        "cluster_id": row.cluster_id,
                        "cluster_name": row.cluster_name,
                        "status": row.status.value,
                        "scale_tier": row.scale_tier,
                        "stage_timings": row.stage_timings,
                        "destroyed_at": str(row.destroyed_at) if row.destroyed_at else None,
                    },
                    indent=2,
                )
            )
            break

        live = await provider.list_app_clusters(settings.shadow_app_tag)
        print(f"\n5) Leak check: {len(live)} live cluster(s) still tagged '{settings.shadow_app_tag}' (expect 0)")
    finally:
        await provider.aclose()
        async for session in database.session():
            run_service = MigrationRunService(
                repository=MigrationRunRepository(session), session=session
            )
            try:
                await run_service.delete_migration_run(run_id)
            except Exception:  # noqa: BLE001
                pass
            break

    print("\nDone. If report['succeeded'] is true and the ShadowCluster status is")
    print("DESTROYED with 0 live clusters, the shadow-cluster feature is working end to end.")


if __name__ == "__main__":
    asyncio.run(main())
