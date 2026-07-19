"""Shadow job watch — MCP-compatible blast-radius theater.

The CockroachDB Managed MCP Server exposes cluster/job introspection to IDE
agents (.cursor/mcp.json). During ExecuteMigration we poll the same job surface
via SQL (SHOW JOBS / crdb_internal) so the demo can show live backfill duration
and schema-change job state without a separate vector store or external monitor.
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


def mcp_tool_attribution() -> dict[str, str]:
    return {
        "cockroachdb_tools": (
            "Distributed Vector Indexing (memory retrieval) + "
            "Managed MCP Server / SQL job watch (shadow blast-radius)"
        ),
        "mcp_endpoint": "https://cockroachlabs.cloud/mcp",
        "runtime_watch": "SHOW JOBS on shadow cluster during ExecuteMigration",
    }
