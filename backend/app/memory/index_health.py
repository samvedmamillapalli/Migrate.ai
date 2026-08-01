"""Is the CockroachDB Distributed Vector Index actually reachable by retrieval?

This exists because the failure mode it guards against is *silent*. Between
Phase 10 and 2026-07-31 the vector index was created but structurally unusable:
it had no prefix columns, so every tenant-scoped retrieval fell back to a filtered
scan plus a brute-force top-k sort. Nothing was slow (42 rows), no test failed,
and no metric moved. See docs/HACKATHON_INTEGRATION_AUDIT.md §1.

The distinction this module is careful about, because getting it wrong produces
false alarms:

* **usable** — can the planner use the vector index for this query *at all*?
  This is the structural property. Before the fix, forcing the index raised
  ``index "..." cannot be used for this query``. That error coming back is the
  real regression signal, and it is what ``problems`` reports on.
* **selected** — does the planner *choose* it, unforced? That is a cost
  decision driven by k/N. On a small corpus the optimizer correctly prefers a
  brute-force scan, which is both cheaper and *exact* (brute force is not
  approximate; ANN is). A `False` here is informational, never a problem.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.memory.constants import (
    CORPUS_OWNER_IDENTITY,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_STATUS_READY,
    VECTOR_INDEX_READY,
    VECTOR_INDEX_SCOPED,
)
from app.repositories.migration_memory_repository import MigrationMemoryRepository

logger = get_logger(__name__)

__all__ = ["VECTOR_INDEX_READY", "VECTOR_INDEX_SCOPED", "check_vector_index",
           "explain", "vector_index_problems"]

# Small-k probe: at any realistic corpus size the planner should pick the index
# here. Chosen well below the production candidate pool so this stays true as
# the corpus grows rather than flipping with it.
_SMALL_K = 5

_VECTOR_SEARCH_NODE = "vector search"
_PREFIX_SPANS = "prefix spans"


def _probe_vector_literal() -> str:
    """A constant probe vector. Index *selection* depends on table statistics,
    not on the vector's values, so no real embedding is needed — which keeps
    this check independent of table contents and safe on an empty corpus."""
    return "[" + ",".join(["0"] * EMBEDDING_DIMENSIONS) + "]"


async def explain(
    session: AsyncSession,
    sql: str,
    params: dict[str, Any],
) -> str:
    """Return the rendered EXPLAIN plan for a query, as one string."""
    result = await session.execute(text("EXPLAIN " + sql), params)
    return "\n".join(str(row[0]) for row in result.fetchall())


async def check_vector_index(
    session: AsyncSession,
    *,
    pool_size: int,
    owner_identity: str = CORPUS_OWNER_IDENTITY,
) -> dict[str, Any]:
    """Probe the vector index four ways. Never raises — a probe failure is
    reported as ``error`` with null verdicts, because this runs inside a health
    route and must not be able to take it down."""
    qv = _probe_vector_literal()
    scopes = [owner_identity, CORPUS_OWNER_IDENTITY]
    scopes = list(dict.fromkeys(scopes))
    placeholders = ", ".join(f":o{i}" for i in range(len(scopes)))
    base_params: dict[str, Any] = {
        "qv": qv,
        "ready": EMBEDDING_STATUS_READY,
        **{f"o{i}": owner for i, owner in enumerate(scopes)},
    }

    report: dict[str, Any] = {
        "scoped_index": VECTOR_INDEX_SCOPED,
        "corpus_index": VECTOR_INDEX_READY,
        "pool_size": pool_size,
        "small_k": _SMALL_K,
        "usable": None,
        "selected_at_pool_size": None,
        "selected_at_small_k": None,
        "corpus_wide_selected": None,
        "error": None,
        "detail": "",
    }

    try:
        # (a) Structural: can the scoped index serve this query when forced?
        forced_sql = MigrationMemoryRepository.vector_candidates_sql(
            placeholders, index_hint=VECTOR_INDEX_SCOPED
        )
        try:
            plan = await explain(
                session, forced_sql, {**base_params, "lim": pool_size}
            )
            report["usable"] = (
                _VECTOR_SEARCH_NODE in plan and _PREFIX_SPANS in plan
            )
            report["forced_plan"] = plan
        except Exception as exc:  # noqa: BLE001 - an unusable index raises here
            report["usable"] = False
            report["forced_plan_error"] = f"{type(exc).__name__}: {exc}"[:500]
            # A failed EXPLAIN can abort the surrounding transaction on
            # PostgreSQL-family servers; roll back so later probes still run.
            await session.rollback()

        unforced_sql = MigrationMemoryRepository.vector_candidates_sql(placeholders)

        # (b) Cost: does the planner choose it at the production pool size?
        plan = await explain(session, unforced_sql, {**base_params, "lim": pool_size})
        report["selected_at_pool_size"] = _VECTOR_SEARCH_NODE in plan

        # (c) Cost: does it choose it at small k, where it always should?
        plan = await explain(session, unforced_sql, {**base_params, "lim": _SMALL_K})
        report["selected_at_small_k"] = _VECTOR_SEARCH_NODE in plan

        # (d) Corpus-wide search rides the no-prefix partial index.
        corpus_sql = MigrationMemoryRepository.semantic_search_sql(None)
        plan = await explain(
            session,
            corpus_sql,
            {"qv": qv, "ready": EMBEDDING_STATUS_READY, "lim": 10},
        )
        report["corpus_wide_selected"] = (
            _VECTOR_SEARCH_NODE in plan and VECTOR_INDEX_READY in plan
        )
    except Exception as exc:  # noqa: BLE001 - health must degrade, not fail
        report["error"] = f"{type(exc).__name__}: {exc}"[:500]
        logger.warning(
            "Vector index health probe failed",
            extra={"error": report["error"]},
        )
        return report

    report["detail"] = _describe(report)
    return report


def _describe(report: dict[str, Any]) -> str:
    if report["usable"] is False:
        return (
            f"{VECTOR_INDEX_SCOPED} cannot serve the retrieval query. Retrieval "
            "is running as a full scan + brute-force top-k. This is the Phase 10 "
            "defect regressing — see docs/HACKATHON_INTEGRATION_AUDIT.md §1."
        )
    if report["selected_at_pool_size"]:
        return "Retrieval runs on the distributed vector index at the production pool size."
    if report["selected_at_small_k"]:
        return (
            f"Index is usable and chosen at k={report['small_k']}, but at the production "
            f"pool size (k={report['pool_size']}) the planner prefers an exact "
            "brute-force scan because k is a large fraction of the corpus. Expected on a "
            "small corpus, and not a defect: brute force is exact, ANN is approximate. "
            "The planner switches to the index as the corpus grows."
        )
    return (
        "Index is usable but the planner is not choosing it at either probe size — "
        "unexpected; inspect the plans."
    )


def vector_index_problems(report: dict[str, Any]) -> list[str]:
    """Problems worth shouting about. Deliberately narrow: only a *structurally*
    unusable index is a problem. Non-selection at large k is the optimizer being
    right, and reporting it as a problem would train operators to ignore this
    field."""
    if report.get("error"):
        return [f"Could not verify vector index health: {report['error']}"]
    if report.get("usable") is False:
        return [
            "Distributed vector index is NOT usable by retrieval "
            f"({report.get('forced_plan_error') or 'planner rejected the index'}) — "
            "retrieval has silently degraded to a full scan"
        ]
    if report.get("corpus_wide_selected") is False:
        return [
            f"Corpus-wide semantic search is not using {VECTOR_INDEX_READY} "
            "(planner chose a scan)"
        ]
    return []
