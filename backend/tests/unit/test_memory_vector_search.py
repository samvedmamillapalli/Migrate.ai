"""Regression tests for the CockroachDB vector-index query shapes.

These need no database. They exist because the defect they guard against was
invisible at runtime: between Phase 10 and 2026-07-31 the vector index was
created but structurally unusable, retrieval silently ran as a full scan, and
nothing failed. See docs/HACKATHON_INTEGRATION_AUDIT.md §1.

The rule these lock in: **only `embedding_status` and `owner_identity` may
appear in the WHERE clause of a vector-search query.** `embedding_status` is
the partial-index predicate and `owner_identity` is the prefix column of
`ix_migration_memories_embedding_scoped`. Anything else — `migration_type`,
`scale_tier`, `embedding IS NOT NULL` — makes the query ineligible for the
index and degrades it to a scan + brute-force sort.
"""

from __future__ import annotations

import re

from app.memory.constants import (
    EMBEDDING_STATUS_READY,
    VECTOR_INDEX_READY,
    VECTOR_INDEX_SCOPED,
)
from app.repositories.migration_memory_repository import MigrationMemoryRepository

_DISQUALIFYING = ("migration_type", "scale_tier", "embedding IS NOT NULL")


def _where_clause(sql: str) -> str:
    match = re.search(r"WHERE(.*?)ORDER BY", sql, re.DOTALL | re.IGNORECASE)
    assert match, f"no WHERE..ORDER BY found in:\n{sql}"
    return match.group(1)


def test_retrieval_where_clause_stays_index_eligible() -> None:
    where = _where_clause(MigrationMemoryRepository.vector_candidates_sql(":o0, :o1"))
    assert "embedding_status" in where
    assert "owner_identity" in where
    for bad in _DISQUALIFYING:
        assert bad not in where, (
            f"{bad!r} in the retrieval WHERE clause disqualifies "
            f"{VECTOR_INDEX_SCOPED} — see docs/HACKATHON_INTEGRATION_AUDIT.md §1"
        )


def test_semantic_search_where_clause_stays_index_eligible() -> None:
    scoped = _where_clause(MigrationMemoryRepository.semantic_search_sql(":o0"))
    corpus = _where_clause(MigrationMemoryRepository.semantic_search_sql(None))

    assert "owner_identity" in scoped
    # Corpus-wide carries no owner predicate at all — that is what lets it ride
    # the no-prefix partial index.
    assert "owner_identity" not in corpus
    for clause in (scoped, corpus):
        assert "embedding_status" in clause
        for bad in _DISQUALIFYING:
            assert bad not in clause, f"{bad!r} disqualifies the vector index"


def test_ordering_uses_cosine_distance_operator() -> None:
    """`<=>` is cosine distance and must match the index's vector_cosine_ops.
    A different operator (`<->` L2, `<#>` inner product) silently stops
    matching the index."""
    for sql in (
        MigrationMemoryRepository.vector_candidates_sql(":o0"),
        MigrationMemoryRepository.semantic_search_sql(None),
    ):
        order_by = sql.split("ORDER BY")[1]
        assert "<=>" in order_by
        assert "<->" not in order_by and "<#>" not in order_by


def test_index_hint_targets_the_partial_indexes() -> None:
    hinted = MigrationMemoryRepository.vector_candidates_sql(
        ":o0", index_hint=VECTOR_INDEX_SCOPED
    )
    assert f"migration_memories@{VECTOR_INDEX_SCOPED}" in hinted
    # Un-hinted is the production read path: no hint may leak into it.
    assert "@" not in MigrationMemoryRepository.vector_candidates_sql(":o0")


class _FakeResult:
    def __init__(self, rows: list, scalars: list | None = None) -> None:
        self._rows = rows
        self._scalars = scalars or []

    def all(self) -> list:
        return self._rows

    def scalars(self) -> _FakeResult:
        return _FakeResult(self._scalars, self._scalars)


class _FakeMemory:
    def __init__(self, mid: int, migration_type: str, scale_tier: str) -> None:
        self.id = mid
        self.migration_type = migration_type
        self.scale_tier = scale_tier


class _FakeSession:
    """Returns canned vector-search rows, then the memories for those ids."""

    def __init__(self, memories: list[_FakeMemory], distances: dict[int, float]) -> None:
        self._memories = memories
        self._distances = distances
        self.executed_params: list[dict] = []

    async def execute(self, statement, params=None):  # noqa: ANN001
        if params is not None:
            self.executed_params.append(params)
            rows = [(m.id, self._distances[m.id]) for m in self._memories]
            return _FakeResult(rows[: params["lim"]])
        return _FakeResult([], list(self._memories))


async def _search(session, **kwargs):
    repo = MigrationMemoryRepository.__new__(MigrationMemoryRepository)
    repo._session = session  # noqa: SLF001 - constructing without a real engine
    return await repo.semantic_search(query_vector_literal="[0]", **kwargs)


def test_structural_filters_are_applied_after_the_top_k() -> None:
    """migration_type/scale_tier must narrow in Python, and the SQL must
    over-fetch so the caller still gets `limit` rows."""
    import asyncio

    mems = [
        _FakeMemory(1, "add_column", "large"),
        _FakeMemory(2, "create_index", "large"),
        _FakeMemory(3, "add_column", "small"),
        _FakeMemory(4, "add_column", "large"),
    ]
    distances = {1: 0.10, 2: 0.20, 3: 0.30, 4: 0.40}
    session = _FakeSession(mems, distances)

    rows, index = asyncio.run(
        _search(session, migration_type="add_column", scale_tier="large", limit=2)
    )

    # Over-fetched (limit * 4), not just `limit`, because filtering discards rows.
    assert session.executed_params[0]["lim"] == 8
    assert [m.id for m, _ in rows] == [1, 4]
    assert index == VECTOR_INDEX_READY  # corpus-wide by default
    # similarity = 1 - cosine_distance, ordered desc
    assert rows[0][1] > rows[1][1]
    assert abs(rows[0][1] - 0.90) < 1e-9


def test_unfiltered_search_does_not_over_fetch() -> None:
    import asyncio

    mems = [_FakeMemory(i, "add_column", "large") for i in range(1, 4)]
    session = _FakeSession(mems, {i: 0.1 * i for i in range(1, 4)})
    rows, index = asyncio.run(_search(session, limit=3))
    assert session.executed_params[0]["lim"] == 3
    assert len(rows) == 3
    assert index == VECTOR_INDEX_READY


def test_scoped_search_reports_the_scoped_index() -> None:
    import asyncio

    mems = [_FakeMemory(1, "add_column", "large")]
    session = _FakeSession(mems, {1: 0.05})
    rows, index = asyncio.run(_search(session, owner_identities=["alice"], limit=5))
    assert index == VECTOR_INDEX_SCOPED
    assert session.executed_params[0]["o0"] == "alice"
    assert session.executed_params[0]["ready"] == EMBEDDING_STATUS_READY


def test_empty_owner_scope_returns_nothing_rather_than_widening() -> None:
    """`scope=mine` with no owner must not silently fall back to the whole
    corpus — that would leak other tenants' memories into a personal search."""
    import asyncio

    session = _FakeSession([], {})
    rows, _ = asyncio.run(_search(session, owner_identities=[], limit=5))
    assert rows == []
    assert session.executed_params == []  # no query issued at all


def test_min_similarity_drops_weak_hits() -> None:
    import asyncio

    mems = [_FakeMemory(1, "a", "s"), _FakeMemory(2, "a", "s")]
    session = _FakeSession(mems, {1: 0.1, 2: 0.8})  # sims 0.9, 0.2
    rows, _ = asyncio.run(_search(session, min_similarity=0.5, limit=5))
    assert [m.id for m, _ in rows] == [1]


def test_index_names_match_the_alembic_migration() -> None:
    """If a migration renames an index, these constants must move with it or
    the health probe silently reports a missing index as 'unusable'."""
    from pathlib import Path

    migration = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "m8h4e1f7a596_vector_index_prefix_columns.py"
    ).read_text(encoding="utf-8")
    assert VECTOR_INDEX_SCOPED in migration
    assert VECTOR_INDEX_READY in migration
    assert EMBEDDING_STATUS_READY in migration
