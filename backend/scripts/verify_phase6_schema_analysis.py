"""Comprehensive Phase 6 Schema Analysis verification.

Read-only. Uses DATABASE_URL (CockroachDB Cloud / PostgreSQL-compatible).
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from pydantic import ValidationError

from app.config import get_settings
from app.schema_analysis import (
    DatabaseMetadata,
    SchemaAnalysisConnection,
    SchemaAnalyzer,
    normalize_target_database_url,
    redact_database_url,
)
from app.schema_analysis.models import (
    ColumnMetadata,
    IndexMetadata,
    SchemaMetadata,
    TableMetadata,
)


class CheckError(Exception):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CheckError(message)


async def verify_connection_and_cleanup(database_url: str) -> dict[str, Any]:
    conn = SchemaAnalysisConnection(database_url)
    try:
        version = await conn.ping()
        check(bool(version), "ping returned empty version")
        check("cockroachdb" in version.lower() or "postgresql" in version.lower(),
              f"unexpected version string: {version[:80]}")
        engine = conn.engine
        check(engine is not None, "engine missing after ping")
    finally:
        await conn.close()

    try:
        _ = conn.engine
        raise CheckError("engine still accessible after close()")
    except RuntimeError as exc:
        check("closed" in str(exc).lower(), f"unexpected close error: {exc}")

    # Context manager path
    async with SchemaAnalysisConnection(database_url) as managed:
        version2 = await managed.ping()
        check(bool(version2), "context-manager ping failed")
    try:
        _ = managed.engine
        raise CheckError("engine still accessible after context exit")
    except RuntimeError:
        pass

    redacted = redact_database_url(database_url)
    check("@" in redacted or "://" in redacted, "redact_database_url malformed")
    if ":" in database_url.split("@", 1)[0]:
        check("***" in redacted, "password not redacted")

    return {"version": version, "cleanup_ok": True}


async def verify_metadata(database_url: str) -> dict[str, Any]:
    analyzer = SchemaAnalyzer()
    metadata = await analyzer.analyze(database_url)

    check(isinstance(metadata, DatabaseMetadata), "not DatabaseMetadata")
    check(bool(metadata.database_name), "database_name empty")
    check(metadata.schema_count >= 1, "no schemas")
    check(metadata.table_count >= 1, "no tables")
    check(len(metadata.schemas) == metadata.schema_count, "schema_count mismatch")
    check(
        sum(s.table_count for s in metadata.schemas) == metadata.table_count,
        "table_count mismatch",
    )
    check(metadata.inspected_at is not None, "inspected_at missing")
    check(
        metadata.server_version is None
        or "cockroachdb" in metadata.server_version.lower()
        or "postgresql" in metadata.server_version.lower(),
        "unexpected server_version",
    )

    # Round-trip / serialize as valid Pydantic payload
    payload = metadata.model_dump(mode="json", by_alias=True)
    rebuilt = DatabaseMetadata.model_validate(payload)
    check(rebuilt.database_name == metadata.database_name, "round-trip failed")

    tables_by_name: dict[str, TableMetadata] = {}
    total_columns = 0
    total_indexes = 0
    total_pks = 0
    total_fks = 0
    row_counts_present = 0
    table_sizes_present = 0

    for schema in metadata.schemas:
        check(isinstance(schema, SchemaMetadata), "schema type")
        check(schema.table_count == len(schema.tables), "schema table_count")
        for table in schema.tables:
            check(isinstance(table, TableMetadata), "table type")
            check(table.schema_name == schema.name, "table schema mismatch")
            check(table.column_count == len(table.columns), "column_count mismatch")
            check(len(table.columns) >= 1, f"{table.name} has no columns")
            for column in table.columns:
                check(isinstance(column, ColumnMetadata), "column type")
                check(bool(column.name), "empty column name")
                check(bool(column.data_type), "empty data_type")
                check(column.ordinal_position >= 1, "bad ordinal_position")
            for index in table.indexes:
                check(isinstance(index, IndexMetadata), "index type")
                check(bool(index.name), "empty index name")
                check(len(index.columns) >= 1, f"index {index.name} has no columns")

            tables_by_name[table.name] = table
            total_columns += table.column_count
            total_indexes += len(table.indexes)
            if table.primary_key:
                total_pks += 1
            total_fks += len(table.foreign_keys)
            if table.estimated_row_count is not None:
                row_counts_present += 1
                check(table.estimated_row_count >= 0, "negative row count")
            if table.estimated_size_bytes is not None:
                table_sizes_present += 1
                check(table.estimated_size_bytes >= 0, "negative table size")

    # Application tables should exist on this project's DB.
    check("migration_runs" in tables_by_name, "migration_runs missing")
    migration_runs = tables_by_name["migration_runs"]
    check("id" in migration_runs.primary_key, "migration_runs PK missing id")
    check(
        any(c.name == "migration_sql" for c in migration_runs.columns),
        "migration_sql column missing",
    )
    check(len(migration_runs.indexes) >= 1, "migration_runs indexes missing")
    check(
        migration_runs.estimated_row_count is not None,
        "migration_runs row estimate missing",
    )

    # Child tables with FKs to migration_runs
    fk_tables = [
        name
        for name in (
            "predictions",
            "execution_results",
            "learned_outcomes",
            "shadow_clusters",
        )
        if name in tables_by_name
    ]
    check(len(fk_tables) >= 1, "expected child tables with FKs")

    fk_found = False
    for name in fk_tables:
        table = tables_by_name[name]
        check("id" in table.primary_key or len(table.primary_key) >= 1,
              f"{name} missing primary key")
        for fk in table.foreign_keys:
            if (
                fk.referred_table == "migration_runs"
                and "migration_run_id" in fk.constrained_columns
            ):
                fk_found = True
                check(bool(fk.name), f"{name} FK missing name")
                check(len(fk.referred_columns) >= 1, f"{name} FK missing referred cols")
    check(fk_found, "no foreign keys to migration_runs discovered")

    # JSON alias: schema_name serializes as "schema"
    table_json = migration_runs.model_dump(mode="json", by_alias=True)
    check(table_json.get("schema") == "public" or "schema" in table_json,
          "schema alias missing in dump")

    return {
        "database_name": metadata.database_name,
        "server_version": (metadata.server_version or "")[:80],
        "schema_count": metadata.schema_count,
        "table_count": metadata.table_count,
        "total_columns": total_columns,
        "total_indexes": total_indexes,
        "tables_with_pk": total_pks,
        "total_foreign_keys": total_fks,
        "tables_with_row_estimates": row_counts_present,
        "tables_with_size_estimates": table_sizes_present,
        "database_size_bytes": metadata.estimated_size_bytes,
        "fk_tables_checked": fk_tables,
        "migration_runs": {
            "columns": migration_runs.column_count,
            "primary_key": migration_runs.primary_key,
            "indexes": len(migration_runs.indexes),
            "constraints": len(migration_runs.constraints),
            "estimated_row_count": migration_runs.estimated_row_count,
            "estimated_size_bytes": migration_runs.estimated_size_bytes,
        },
        "pydantic_ok": True,
    }


async def verify_url_normalization(database_url: str) -> dict[str, Any]:
    normalized = normalize_target_database_url(database_url)
    check(
        normalized.startswith("cockroachdb+psycopg://")
        or normalized.startswith("postgresql+psycopg://"),
        f"unexpected normalized scheme: {normalized.split('://', 1)[0]}",
    )
    # PostgreSQL-compatible schemes accepted
    for scheme in ("postgresql://", "postgres://"):
        sample = scheme + "user:pass@localhost:5432/db"
        out = normalize_target_database_url(sample)
        check(out.startswith("postgresql+psycopg://"), f"failed for {scheme}")

    cockroach_sample = "cockroachdb://user:pass@localhost:26257/db"
    out_crdb = normalize_target_database_url(cockroach_sample)
    check(out_crdb.startswith("cockroachdb+psycopg://"), "cockroach scheme failed")

    return {
        "normalized_scheme": normalized.split("://", 1)[0],
        "postgres_compatible_urls_ok": True,
        "cockroach_urls_ok": True,
    }


async def main() -> None:
    settings = get_settings()
    database_url = settings.database_url.get_secret_value()

    report: dict[str, Any] = {"ok": False}
    try:
        report["url_normalization"] = await verify_url_normalization(database_url)
        report["connection"] = await verify_connection_and_cleanup(database_url)
        report["metadata"] = await verify_metadata(database_url)
        report["ok"] = True
    except Exception as exc:
        report["ok"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        print(json.dumps(report, indent=2, default=str))
        raise SystemExit(1) from exc

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
