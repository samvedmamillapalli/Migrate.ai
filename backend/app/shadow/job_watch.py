"""Shadow job watch — real SQL introspection, no MCP involved.

During ExecuteMigration we poll the schema-change job surface via SQL
(SHOW JOBS / crdb_internal) to show live backfill duration and schema-change
job state. This is independent of, and complementary to, the real MCP-backed
blast-radius investigation in app.shadow.blast_radius_investigator — this
module used to also carry a hardcoded "Managed MCP Server" attribution string
that never made an MCP call; that's gone, see
docs/COCKROACHDB_MCP_INTEGRATION_PLAN.md §0 for why.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.logging import get_logger

logger = get_logger(__name__)


async def snapshot_schema_jobs(conn: AsyncConnection) -> list[dict[str, Any]]:
    """Return recent schema-change / job rows for attribution and S3 artifacts."""
    try:
        result = await conn.execute(
            text(
                """
                SELECT
                  job_id::string AS job_id,
                  job_type,
                  status,
                  description,
                  created::string AS created_at
                FROM [SHOW JOBS]
                WHERE job_type IN (
                  'SCHEMA CHANGE',
                  'NEW SCHEMA CHANGE',
                  'CREATE INDEX',
                  'ALTER TABLE'
                )
                ORDER BY created DESC
                LIMIT 10
                """
            )
        )
        rows = []
        for row in result.mappings().all():
            rows.append(dict(row))
        return rows
    except Exception as exc:  # noqa: BLE001 - best-effort watch
        logger.warning(
            "Shadow job watch query failed",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )
        return []
