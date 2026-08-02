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
from typing import Any, TYPE_CHECKING

from app.core.logging import get_logger
from app.prediction.bedrock_client import (
    BedrockClient,
    ToolUseResult,
    extract_json_object,
)
from app.shadow.mcp_client import open_shadow_mcp_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.memory.embedding_client import EmbeddingClient

logger = get_logger(__name__)

_PROMPT_VERSION = "blast_radius_investigation_v3"
_PROMPT_PATH = Path(__file__).parent / "prompts" / f"{_PROMPT_VERSION}.txt"
_MAX_TOOL_CALLS = 8

# CockroachDB Agent Skills Repo tool (docs/cockroach_hookup.md §5), sidelined
# 2026-08-02 per user decision: retrieval proven live and functional, but
# judged not impactful enough to a core feature to keep active. Code stays
# intact and tested — flip this back to True to re-enable, no other changes
# needed. search_prior_migrations (a different feature, Distributed Vector
# Indexing over this app's own history) is unaffected and stays on.
_SKILLS_TOOL_ENABLED = False

# Agent-facing semantic search over Migration Oracle's own graded history.
MEMORY_TOOL_NAME = "search_prior_migrations"

# This text is fed back into the model's context, so it is capped hard. Five
# hits of ~4 short lines each stays well inside a sane share of the window.
_MEMORY_TOOL_MAX_LIMIT = 5
_MEMORY_RESULT_MAX_CHARS = 4000
_MEMORY_FIELD_MAX_CHARS = 240

_MEMORY_TOOL_SPEC: dict[str, Any] = {
    "toolSpec": {
        "name": MEMORY_TOOL_NAME,
        "description": (
            "Semantic search over Migration Oracle's memory of past "
            "migrations, backed by CockroachDB's distributed vector index. "
            "Searches institutional history — previously graded runs (with "
            "predicted vs actual outcomes and lessons learned) and documented "
            "open-source migration incidents. This does NOT query the shadow "
            "cluster. Use a natural-language description of the migration "
            "mechanism you are curious about, not SQL."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Natural-language description of the mechanism, "
                            "e.g. 'backfill stalled adding a NOT NULL column "
                            "to a large table'."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            f"Max results (1-{_MEMORY_TOOL_MAX_LIMIT}, default 5)."
                        ),
                    },
                },
                "required": ["query"],
            }
        },
    }
}

# Agent-facing semantic search over the vendored CockroachDB Agent Skills Repo
# (cockroachlabs/cockroachdb-skills), embedded into cockroachdb_skill_docs and
# retrieved via the same CockroachDB Distributed Vector Index mechanism as
# search_prior_migrations — see docs/cockroach_hookup.md §5.
SKILLS_TOOL_NAME = "search_cockroachdb_skills"

_SKILLS_TOOL_MAX_LIMIT = 3
_SKILLS_RESULT_MAX_CHARS = 4000
_SKILLS_FIELD_MAX_CHARS = 600

_SKILLS_TOOL_SPEC: dict[str, Any] = {
    "toolSpec": {
        "name": SKILLS_TOOL_NAME,
        "description": (
            "Semantic search over Cockroach Labs' own documented operational "
            "expertise (the open-source CockroachDB Agent Skills Repo — "
            "github.com/cockroachlabs/cockroachdb-skills), backed by "
            "CockroachDB's distributed vector index. Use this when the "
            "migration's mechanism touches something CockroachDB has "
            "documented guidance for — storage/backfill risk on CREATE "
            "INDEX / ADD COLUMN UNIQUE / ALTER PRIMARY KEY, privilege "
            "hardening, cluster health, range distribution, table "
            "statistics, or background job behavior. This is vendor "
            "documentation, not institutional history — use "
            "search_prior_migrations for our own graded runs instead."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Natural-language description of the operational "
                            "concern, e.g. 'storage headroom needed for "
                            "CREATE UNIQUE INDEX backfill'."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            f"Max results (1-{_SKILLS_TOOL_MAX_LIMIT}, default 3)."
                        ),
                    },
                },
                "required": ["query"],
            }
        },
    }
}


def _clip(value: Any, limit: int = _MEMORY_FIELD_MAX_CHARS) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _format_memory_hits(rows: list[tuple[Any, float]], index_used: str | None) -> str:
    """Compact plain-text rendering of search hits for the model's context."""
    if not rows:
        return (
            "No prior migrations in memory matched that query. This mechanism "
            "has no recorded history — treat it as unprecedented rather than "
            "assuming it is safe."
        )

    lines: list[str] = []
    for rank, (mem, similarity) in enumerate(rows, start=1):
        pred = mem.prediction_summary or {}
        exe = mem.execution_summary or {}
        grade = mem.grade_summary if isinstance(mem.grade_summary, dict) else {}
        integrity = grade.get("integrity") if isinstance(grade.get("integrity"), dict) else {}

        predicted = pred.get("estimated_duration_seconds")
        actual = exe.get("actual_duration_seconds")
        if predicted is not None and actual is not None:
            duration = f"predicted {float(predicted):.0f}s -> actual {float(actual):.0f}s"
        else:
            duration = "duration not recorded"

        # A documented incident is not a measured run of ours; saying so keeps
        # the model from citing it as if we had graded it ourselves.
        origin = (
            "documented open-source incident (not one of our graded runs)"
            if integrity.get("not_a_graded_run")
            else "our graded run"
        )

        lines.append(
            f"[{rank}] similarity {similarity:.2f} | {origin} | "
            f"{mem.migration_type}/{mem.scale_tier} | "
            f"outcome {grade.get('outcome_class') or 'unknown'} | {duration}\n"
            f"    what: {_clip(mem.migration_summary)}\n"
            f"    lesson: {_clip(mem.lessons_learned)}"
        )

    header = f"{len(rows)} prior migration(s) via CockroachDB vector index"
    if index_used:
        header += f" ({index_used})"
    body = header + ":\n" + "\n".join(lines)
    if len(body) > _MEMORY_RESULT_MAX_CHARS:
        body = body[: _MEMORY_RESULT_MAX_CHARS - 1] + "…"
    return body


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


async def _search_prior_migrations(
    *,
    session: AsyncSession,
    embedding_client: EmbeddingClient,
    arguments: dict[str, Any],
) -> tuple[str, bool]:
    """Run the agent's memory search. Returns (result_text, is_error).

    Never raises: a failed search is a finding the model can reason about
    ("history unavailable"), not a crash — the whole investigation is
    best-effort enrichment on top of an already-measured migration.
    """
    from app.memory.embedding_client import vector_to_literal
    from app.repositories.migration_memory_repository import MigrationMemoryRepository

    query = str(arguments.get("query") or "").strip()
    if not query:
        return ("search_prior_migrations requires a non-empty 'query'.", True)

    try:
        raw_limit = int(arguments.get("limit") or _MEMORY_TOOL_MAX_LIMIT)
    except (TypeError, ValueError):
        raw_limit = _MEMORY_TOOL_MAX_LIMIT
    limit = max(1, min(_MEMORY_TOOL_MAX_LIMIT, raw_limit))

    try:
        vector = embedding_client.embed(query)
        rows, index_used = await MigrationMemoryRepository(session).semantic_search(
            query_vector_literal=vector_to_literal(vector),
            # Corpus-wide: the investigating agent should draw on the shared
            # open-source corpus and every graded run, not just one tenant's.
            owner_identities=None,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001 - a failed search is a finding, not a crash
        logger.warning(
            "search_prior_migrations failed",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )
        return (
            f"Memory search unavailable ({type(exc).__name__}). Proceed using "
            "only the live shadow-cluster evidence; do not guess at history.",
            True,
        )

    logger.info(
        "search_prior_migrations served",
        extra={"query": query[:120], "hits": len(rows), "index_used": index_used},
    )
    return (_format_memory_hits(rows, index_used), False)


def _format_skill_hits(rows: list[tuple[Any, float]], index_used: str | None) -> str:
    """Compact plain-text rendering of skill search hits for the model's context."""
    if not rows:
        return (
            "No CockroachDB Agent Skill matched that query closely. Proceed "
            "using your own knowledge; do not fabricate a citation."
        )

    lines: list[str] = []
    for rank, (doc, similarity) in enumerate(rows, start=1):
        body = " ".join(str(doc.body or "").split())
        excerpt = body if len(body) <= _SKILLS_FIELD_MAX_CHARS else body[: _SKILLS_FIELD_MAX_CHARS - 1] + "…"
        lines.append(
            f"[{rank}] similarity {similarity:.2f} | {doc.title} ({doc.category})\n"
            f"    source: {doc.source_url}\n"
            f"    excerpt: {excerpt}"
        )

    header = f"{len(rows)} CockroachDB Agent Skill(s) via CockroachDB vector index"
    if index_used:
        header += f" ({index_used})"
    body_text = header + ":\n" + "\n".join(lines)
    if len(body_text) > _SKILLS_RESULT_MAX_CHARS:
        body_text = body_text[: _SKILLS_RESULT_MAX_CHARS - 1] + "…"
    return body_text


async def _search_cockroachdb_skills(
    *,
    session: AsyncSession,
    embedding_client: EmbeddingClient,
    arguments: dict[str, Any],
) -> tuple[str, bool]:
    """Run the agent's CockroachDB Agent Skills search. Returns (result_text, is_error).

    Never raises, same contract as _search_prior_migrations: a failed search
    is a finding the model can reason about, not a crash.
    """
    from app.memory.embedding_client import vector_to_literal
    from app.repositories.skill_doc_repository import SkillDocRepository

    query = str(arguments.get("query") or "").strip()
    if not query:
        return (f"{SKILLS_TOOL_NAME} requires a non-empty 'query'.", True)

    try:
        raw_limit = int(arguments.get("limit") or _SKILLS_TOOL_MAX_LIMIT)
    except (TypeError, ValueError):
        raw_limit = _SKILLS_TOOL_MAX_LIMIT
    limit = max(1, min(_SKILLS_TOOL_MAX_LIMIT, raw_limit))

    try:
        vector = embedding_client.embed(query)
        rows, index_used = await SkillDocRepository(session).semantic_search(
            query_vector_literal=vector_to_literal(vector),
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001 - a failed search is a finding, not a crash
        logger.warning(
            "search_cockroachdb_skills failed",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )
        return (
            f"CockroachDB Agent Skills search unavailable ({type(exc).__name__}). "
            "Proceed using only the live shadow-cluster evidence and your own "
            "knowledge; do not fabricate a citation.",
            True,
        )

    logger.info(
        "search_cockroachdb_skills served",
        extra={"query": query[:120], "hits": len(rows), "index_used": index_used},
    )
    return (_format_skill_hits(rows, index_used), False)


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
    session: AsyncSession | None = None,
    embedding_client: EmbeddingClient | None = None,
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

    # `mcp_session`, not `session` — `session` is the CockroachDB AsyncSession
    # parameter above, which the memory tool needs; shadowing it here would
    # silently break search_prior_migrations.
    async with open_shadow_mcp_session(
        cluster_id=cluster_id,
        api_secret=api_secret,
        base_url=mcp_base_url,
        max_calls=max_tool_calls,
    ) as mcp_session:
        if mcp_session is None:
            return None

        try:
            tool_defs = await mcp_session.tool_defs()
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

        # Offer the memory/skills searches only when they can actually be
        # served. Adding a toolSpec without a session/embedder would
        # advertise a tool that errors on every call and burns the model's
        # budget doing it.
        local_tools_available = session is not None and embedding_client is not None
        if local_tools_available:
            tools.append(_MEMORY_TOOL_SPEC)
            if _SKILLS_TOOL_ENABLED:
                tools.append(_SKILLS_TOOL_SPEC)
        else:
            logger.info(
                "search_prior_migrations / search_cockroachdb_skills not "
                "offered (no DB session or embedding client passed); "
                "investigation will use MCP tools only"
            )

        async def tool_executor(name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
            if name == MEMORY_TOOL_NAME:
                # Local tool, not MCP — it queries Migration Oracle's own
                # memory. Still counted against converse_with_tools'
                # max_tool_calls budget, which tallies every dispatch here
                # regardless of which tool served it.
                assert session is not None and embedding_client is not None
                return await _search_prior_migrations(
                    session=session,
                    embedding_client=embedding_client,
                    arguments=arguments,
                )
            if name == SKILLS_TOOL_NAME:
                # Also local, not MCP — queries the vendored CockroachDB
                # Agent Skills Repo content, not the shadow cluster.
                assert session is not None and embedding_client is not None
                return await _search_cockroachdb_skills(
                    session=session,
                    embedding_client=embedding_client,
                    arguments=arguments,
                )
            # Every MCP tool here takes a `database` argument; default it to
            # the shadow cluster's own database so the model doesn't have to
            # rediscover which database it's supposed to be looking at.
            args = dict(arguments)
            args.setdefault("database", database)
            call = await mcp_session.call_tool(name, args)
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
