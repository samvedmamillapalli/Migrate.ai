"""Verify schema analysis against a PostgreSQL-compatible target.

Uses DATABASE_URL from the environment / .env (typically CockroachDB Cloud).
Read-only inspection only — does not modify schema.
"""

from __future__ import annotations

import asyncio
import json
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import get_settings
from app.schema_analysis import SchemaAnalyzer, normalize_target_database_url


async def main() -> None:
    settings = get_settings()
    database_url = settings.database_url.get_secret_value()
    normalized = normalize_target_database_url(database_url)

    analyzer = SchemaAnalyzer()
    metadata = await analyzer.analyze(database_url)

    assert metadata.database_name, "database_name missing"
    assert metadata.schema_count >= 1, "expected at least one schema"
    assert metadata.table_count >= 1, "expected at least one table"
    assert metadata.inspected_at is not None

    # Prefer public.migration_runs if present (app schema).
    migration_runs = None
    for schema in metadata.schemas:
        for table in schema.tables:
            if table.name == "migration_runs":
                migration_runs = table
                break

    assert migration_runs is not None, "migration_runs table not found"
    assert migration_runs.column_count >= 4
    assert "id" in migration_runs.primary_key
    assert any(col.name == "migration_sql" for col in migration_runs.columns)
    assert any(col.name == "status" for col in migration_runs.columns)
    assert len(migration_runs.indexes) >= 1
    assert migration_runs.estimated_row_count is not None
    assert migration_runs.estimated_row_count >= 0

    payload = metadata.model_dump(mode="json", by_alias=True)
    print(
        json.dumps(
            {
                "ok": True,
                "normalized_scheme": normalized.split("://", 1)[0],
                "database_name": metadata.database_name,
                "schema_count": metadata.schema_count,
                "table_count": metadata.table_count,
                "estimated_size_bytes": metadata.estimated_size_bytes,
                "migration_runs": {
                    "schema": migration_runs.schema_name,
                    "column_count": migration_runs.column_count,
                    "primary_key": migration_runs.primary_key,
                    "index_count": len(migration_runs.indexes),
                    "constraint_count": len(migration_runs.constraints),
                    "estimated_row_count": migration_runs.estimated_row_count,
                    "estimated_size_bytes": migration_runs.estimated_size_bytes,
                },
                "sample_table_keys": sorted(payload["schemas"][0]["tables"][0].keys()),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
