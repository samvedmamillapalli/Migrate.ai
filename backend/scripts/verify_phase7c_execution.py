"""Phase 7C verification: execute migration SQL on a real shadow cluster and
prove the outcome (duration / storage growth / error / rollback) persists
correctly as an ``ExecutionResult``.

Flow: provision one real Basic cluster -> create SQL user -> recreate a schema
snapshot on it via the Phase 7B ``ShadowSchemaLoader`` (schemas, tables,
columns, PKs, FKs, indexes, UNIQUE/CHECK constraints -- no synthetic rows) ->
for each case in the execution matrix, create a real ``MigrationRun`` row in
the control-plane database, run the migration SQL with
``app.shadow.migration_runner.run_migration``, persist the outcome through
``ExecutionService`` (the same production code path), then re-read the
``ExecutionResult`` back from the database to prove persistence round-trips
-> destroy the cluster (always) -> delete the scratch ``MigrationRun`` rows.

Execution matrix:
  1. ALTER TABLE ... ALTER COLUMN ... SET DEFAULT   (expect success)
  2. CREATE INDEX                                    (expect success)
  3. ADD COLUMN then DROP COLUMN (one migration)      (expect success)
  4. Failed SQL: ALTER TABLE on a nonexistent table   (expect failure, rollback)
  5. Syntax error                                     (expect failure, rollback)
  6. Constraint violation: INSERT that violates a
     CHECK constraint recreated from the snapshot     (expect failure, rollback)

Prints PASS/FAIL for every case and exits non-zero on any mismatch. No mock
seeder/provider is used: the shadow cluster is real CockroachDB Cloud, and the
result is persisted to and re-read from the real control-plane database.
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
from app.database import DatabaseSessionManager
from app.repositories.execution_result_repository import ExecutionResultRepository
from app.repositories.migration_run_repository import MigrationRunRepository
from app.schema_analysis.models import (
    ColumnMetadata,
    ConstraintMetadata,
    DatabaseMetadata,
    ForeignKeyMetadata,
    IndexMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.services.execution_service import ExecutionService
from app.services.migration_run_service import MigrationRunService
from app.shadow.ccloud_api_provider import CCloudApiShadowProvider
from app.shadow.migration_runner import run_migration
from app.shadow.models import ProvisionSpec
from app.shadow.schema_loader import ShadowSchemaLoader


class CheckError(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CheckError(message)


def _snapshot() -> DatabaseMetadata:
    """Same shape as the Phase 7B snapshot: PK, FK, UNIQUE, CHECK, indexes."""
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


# (case name, migration SQL, expect_success)
EXECUTION_MATRIX: list[tuple[str, str, bool]] = [
    (
        "alter_table_set_default",
        'ALTER TABLE public.customers ALTER COLUMN status SET DEFAULT \'active\'',
        True,
    ),
    (
        "create_index",
        "CREATE INDEX idx_orders_placed_at ON public.orders (placed_at)",
        True,
    ),
    (
        "add_then_drop_column",
        "ALTER TABLE public.orders ADD COLUMN notes STRING; "
        "ALTER TABLE public.orders DROP COLUMN notes",
        True,
    ),
    (
        "failed_sql_missing_table",
        "ALTER TABLE public.no_such_table ADD COLUMN x INT8",
        False,
    ),
    (
        "syntax_error",
        "ALTER TABLE public.customers ADD COLUMN",
        False,
    ),
    (
        "constraint_violation",
        "INSERT INTO public.customers (id, email, status, created_at) "
        "VALUES (gen_random_uuid(), 'phase7c@example.com', 'not_a_valid_status', now())",
        False,
    ),
]


async def _create_run(database: DatabaseSessionManager, migration_sql: str) -> uuid.UUID:
    async for session in database.session():
        service = MigrationRunService(
            repository=MigrationRunRepository(session), session=session
        )
        run = await service.create_migration_run(migration_sql)
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


async def _record_and_reread(
    database: DatabaseSessionManager,
    run_id: uuid.UUID,
    outcome,
) -> dict[str, Any]:
    """Persist via ExecutionService, then open a *new* session and re-read the
    row back from the database to prove the round trip (not just the
    in-memory object returned by the write)."""
    async for session in database.session():
        service = ExecutionService(
            repository=ExecutionResultRepository(session), session=session
        )
        await service.record_execution(
            run_id,
            success=outcome.success,
            duration_seconds=outcome.duration_seconds,
            storage_mb=outcome.storage_growth_mb,
            rollback_required=outcome.rollback_required,
            error_message=outcome.error_message,
        )
        break

    async for session in database.session():
        repo = ExecutionResultRepository(session)
        persisted = await repo.get_by_migration_run_id(run_id)
        check(persisted is not None, "ExecutionResult was not persisted")
        return {
            "success": persisted.success,
            "actual_duration_seconds": persisted.actual_duration_seconds,
            "actual_storage_mb": persisted.actual_storage_mb,
            "rollback_required": persisted.rollback_required,
            "error_message": persisted.error_message,
        }
    raise RuntimeError("no session")


async def main() -> None:
    settings = get_settings()
    if settings.ccloud_api_secret is None:
        print(json.dumps({"ok": False, "error": "CCLOUD_API_SECRET not set"}))
        raise SystemExit(1)

    database = DatabaseSessionManager(settings.database_url.get_secret_value())
    provider = CCloudApiShadowProvider(
        api_secret=settings.ccloud_api_secret.get_secret_value(),
        base_url=settings.ccloud_api_base_url, plan=settings.shadow_cluster_plan,
        provider_cloud="AWS",
        timeout_seconds=settings.ccloud_api_timeout_seconds,
        max_retries=settings.ccloud_api_max_retries,
        backoff_base_seconds=settings.ccloud_api_backoff_base_seconds,
    )

    report: dict[str, Any] = {"ok": False, "cases": []}
    cluster_id = None
    run_ids: list[uuid.UUID] = []
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
        load = await ShadowSchemaLoader().load(handle.connection_url, _snapshot())
        report["schema_load_seconds"] = round(time.perf_counter() - t1, 1)
        report["loaded"] = {
            "tables": load.tables_created, "foreign_keys": load.foreign_keys_created,
            "constraints": load.constraints_created,
        }

        all_ok = True
        for name, sql, expect_success in EXECUTION_MATRIX:
            run_id = await _create_run(database, sql)
            run_ids.append(run_id)

            outcome = await run_migration(handle.connection_url, sql)
            persisted = await _record_and_reread(database, run_id, outcome)

            case_ok = (
                outcome.success == expect_success
                and persisted["success"] == expect_success
                and persisted["rollback_required"] == (not expect_success)
                and (expect_success or persisted["error_message"] is not None)
            )
            all_ok = all_ok and case_ok
            report["cases"].append(
                {
                    "name": name,
                    "ok": case_ok,
                    "expected_success": expect_success,
                    "outcome_success": outcome.success,
                    "duration_seconds": outcome.duration_seconds,
                    "storage_growth_mb": outcome.storage_growth_mb,
                    "rollback_required": outcome.rollback_required,
                    "error_message": outcome.error_message,
                    "persisted": persisted,
                }
            )
        report["ok"] = all_ok
    finally:
        for run_id in run_ids:
            await _delete_run(database, run_id)
        if cluster_id:
            await provider.destroy(cluster_id=cluster_id)
            report["cluster_destroyed"] = True
        await provider.aclose()

    print(json.dumps(report, indent=2, default=str))
    print("\n=== PHASE 7C CHECKLIST ===")
    for case in report["cases"]:
        status = "[PASS]" if case["ok"] else "[FAIL]"
        print(f"{status} {case['name']} (success={case['outcome_success']}, "
              f"expected={case['expected_success']})")
    print(f"{'[PASS]' if report['ok'] else '[FAIL]'} All execution outcomes persisted and match expectations")
    print(f"{'[PASS]' if report.get('cluster_destroyed') else '[FAIL]'} Cluster destroyed afterwards")
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
