"""Blast-radius investigation — a genuine Claude tool-use agent with live,
read-only CockroachDB Managed MCP access to the shadow cluster it's
investigating, run once per migration right after execution.

See docs/COCKROACHDB_MCP_INTEGRATION_PLAN.md for the design: this exists
because the deterministic checks elsewhere in this app (schema diff, row
sample, `SHOW JOBS`) can only ever check what a human thought to query for in
advance. This gives the agent live query access and lets it decide what's
worth verifying given the specific migration that ran — a genuine capability
gap the fixed SQL path cannot close, not a slower way to re-derive the same
answer.

Best-effort throughout, like everything else that touches the shadow cluster
in this app: returns None on any failure (no MCP package, no network, no
model access) rather than raising — this is enrichment on top of an
already-measured migration, never a dependency of it.
"""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any

from app.core.logging import get_logger
from app.prediction.bedrock_client import (
    BedrockClient,
    ToolUseResult,
    extract_json_object,
)
from app.shadow.mcp_client import open_shadow_mcp_session

logger = get_logger(__name__)

_PROMPT_VERSION = "blast_radius_investigation_v1"
_PROMPT_PATH = Path(__file__).parent / "prompts" / f"{_PROMPT_VERSION}.txt"
_MAX_TOOL_CALLS = 8


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _build_user_prompt(
    *,
    migration_sql: str,
    schema_diff: dict[str, Any] | None,
    row_sample_after: dict[str, Any] | None,
) -> str:
    return (
        "Migration SQL that was executed on the shadow cluster:\n"
        f"{migration_sql}\n\n"
        "Deterministic schema diff already computed from real before/after "
        "snapshots (added/removed/changed columns, indexes, constraints):\n"
        f"{json.dumps(schema_diff or {}, indent=2)}\n\n"
        "Real row sample already captured after the migration (up to 20 "
        "rows per table, may be truncated below):\n"
        f"{json.dumps(row_sample_after or {}, indent=2)[:4000]}\n\n"
        "Investigate what actually happened using your live tools, per your "
        "instructions."
    )


async def investigate(
    *,
    bedrock_client: BedrockClient,
    model_id: str,
    cluster_id: str,
    database: str,
    api_secret: str,
    mcp_base_url: str,
    migration_sql: str,
    schema_diff: dict[str, Any] | None,
    row_sample_after: dict[str, Any] | None,
    max_tool_calls: int = _MAX_TOOL_CALLS,
) -> dict[str, Any] | None:
    """Run the investigation. Returns a ModelTrace-shaped dict (same shape
    `app.prediction.trace.build_trace` produces, so it drops into the
    existing `explainability["bedrock_traces"]` / "Model Traces" UI with no
    new persistence or rendering path), or None if MCP or Bedrock was
    unavailable for any reason. Never raises."""
    system_prompt = _load_system_prompt()
    user_prompt = _build_user_prompt(
        migration_sql=migration_sql,
        schema_diff=schema_diff,
        row_sample_after=row_sample_after,
    )

    async with open_shadow_mcp_session(
        cluster_id=cluster_id,
        api_secret=api_secret,
        base_url=mcp_base_url,
        max_calls=max_tool_calls,
    ) as session:
        if session is None:
            return None

        try:
            tool_defs = await session.tool_defs()
        except Exception as exc:  # noqa: BLE001 - enrichment, never blocks the migration
            logger.warning(
                "MCP list_tools failed; skipping investigation",
                extra={"error": f"{type(exc).__name__}: {exc}"},
            )
            return None

        if not tool_defs:
            logger.warning("MCP server returned no read-only tools; skipping investigation")
            return None

        tools = [
            {
                "toolSpec": {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": {"json": t.input_schema},
                }
            }
            for t in tool_defs
        ]

        async def tool_executor(name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
            # Every MCP tool here takes a `database` argument; default it to
            # the shadow cluster's own database so the model doesn't have to
            # rediscover which database it's supposed to be looking at.
            args = dict(arguments)
            args.setdefault("database", database)
            call = await session.call_tool(name, args)
            return call.result_text, call.is_error

        started = perf_counter()
        try:
            result: ToolUseResult = await bedrock_client.converse_with_tools(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tools=tools,
                tool_executor=tool_executor,
                model_id=model_id,
                max_tool_calls=max_tool_calls,
            )
        except Exception as exc:  # noqa: BLE001 - enrichment, never blocks the migration
            logger.warning(
                "Blast-radius investigation failed",
                extra={"error": f"{type(exc).__name__}: {exc}"},
            )
            return None
        total_latency_ms = round((perf_counter() - started) * 1000.0, 2)

    parsed: dict[str, Any] | None = None
    validation_error: str | None = None
    try:
        parsed = extract_json_object(result.final_text)
    except Exception as exc:  # noqa: BLE001
        validation_error = f"{type(exc).__name__}: {exc}"

    last_turn = result.turns[-1] if result.turns else None
    attempts = [
        {
            "raw_response": turn.raw_text,
            "parsed": parsed if turn is last_turn else None,
            "validation_error": validation_error if turn is last_turn else None,
            "latency_ms": turn.latency_ms,
            "input_tokens": turn.input_tokens,
            "output_tokens": turn.output_tokens,
            "tool_calls": [
                {
                    "name": c.name,
                    "arguments": c.arguments,
                    "result_text": c.result_text[:2000],
                    "is_error": c.is_error,
                }
                for c in turn.tool_calls
            ]
            or None,
        }
        for turn in result.turns
    ]

    logger.info(
        "Blast-radius investigation completed",
        extra={
            "turns": len(result.turns),
            "tool_calls": len(result.all_tool_calls),
            "parsed_ok": parsed is not None,
            "hit_call_budget": result.hit_call_budget,
        },
    )

    return {
        "kind": "blast_radius_investigation",
        "model_id": model_id,
        "prompt_template_version": _PROMPT_VERSION,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "attempts": attempts,
        "repair_retried": False,
        "final_parsed": parsed,
        "latency_ms_total": total_latency_ms,
        "hit_call_budget": result.hit_call_budget,
    }
