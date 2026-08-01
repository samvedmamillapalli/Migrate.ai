from __future__ import annotations

import uuid

from sqlalchemy import select, text

from app.database.models import MigrationMemory
from app.memory.constants import (
    EMBEDDING_STATUS_READY,
    VECTOR_INDEX_READY,
    VECTOR_INDEX_SCOPED,
)
from app.repositories.base import BaseRepository

# How many extra rows to pull from the vector search when structural filters
# (migration_type / scale_tier / min_similarity) will discard some afterwards.
# Those filters cannot go in SQL without disqualifying the vector index, so the
# only way to still return `limit` rows is to over-fetch and narrow.
_OVERFETCH_FACTOR = 4


class MigrationMemoryRepository(BaseRepository[MigrationMemory]):
    model = MigrationMemory

    async def get_by_migration_run_id(
        self,
        run_id: uuid.UUID,
    ) -> MigrationMemory | None:
        result = await self._session.execute(
            select(MigrationMemory).where(MigrationMemory.migration_run_id == run_id)
        )
        return result.scalar_one_or_none()

    async def list_pending_embeddings(self, *, limit: int = 50) -> list[MigrationMemory]:
        result = await self._session.execute(
            select(MigrationMemory)
            .where(MigrationMemory.embedding_status == "pending")
            .order_by(MigrationMemory.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    def vector_candidates_sql(
        owner_placeholders: str,
        *,
        index_hint: str | None = None,
    ) -> str:
        """The owner-scoped nearest-neighbour SQL, as a string.

        Exposed so verification scripts and the health route can ``EXPLAIN``
        the *exact* query this repository issues instead of a hand-copied
        approximation that can drift out of sync with it. See
        ``app/memory/index_health.py``.

        Only ``embedding_status`` and ``owner_identity`` may appear in the
        WHERE clause: they are, respectively, the partial-index predicate and
        the prefix column of ``ix_migration_memories_embedding_scoped``. Any
        other filter added here would make the query ineligible for the vector
        index and silently degrade retrieval to a full scan + brute-force sort
        — see docs/HACKATHON_INTEGRATION_AUDIT.md §1.

        ``index_hint`` forces a specific index and is for diagnostics only —
        never for the production read path. Whether the planner *chooses* the
        vector index is a cost decision that depends on k/N; whether it *can*
        is the structural property worth asserting.
        """
        table = "migration_memories"
        if index_hint:
            table = f"{table}@{index_hint}"
        return f"""
            SELECT
                id,
                (embedding <=> CAST(:qv AS VECTOR(1024))) AS distance
            FROM {table}
            WHERE embedding_status = :ready
              AND owner_identity IN ({owner_placeholders})
            ORDER BY embedding <=> CAST(:qv AS VECTOR(1024))
            LIMIT :lim
            """

    @staticmethod
    def semantic_search_sql(
        owner_placeholders: str | None,
        *,
        index_hint: str | None = None,
    ) -> str:
        """Corpus-wide (``owner_placeholders=None``) or owner-scoped semantic
        search SQL.

        Same rule as above, and it is the whole reason ``migration_type`` and
        ``scale_tier`` are *not* parameters here: those are applied in Python
        after the top-k. Adding them to this WHERE clause would disqualify the
        vector index exactly as the original unscoped index was disqualified.
        """
        table = "migration_memories"
        if index_hint:
            table = f"{table}@{index_hint}"
        owner_clause = (
            f"\n              AND owner_identity IN ({owner_placeholders})"
            if owner_placeholders
            else ""
        )
        return f"""
            SELECT
                id,
                (embedding <=> CAST(:qv AS VECTOR(1024))) AS distance
            FROM {table}
            WHERE embedding_status = :ready{owner_clause}
            ORDER BY embedding <=> CAST(:qv AS VECTOR(1024))
            LIMIT :lim
            """

    async def vector_candidates(
        self,
        *,
        query_vector_literal: str,
        owner_identities: list[str],
        limit: int,
    ) -> list[tuple[MigrationMemory, float]]:
        """Nearest neighbors via CockroachDB VECTOR cosine distance.

        Uses the Distributed Vector Index on ``embedding``. Returns
        (memory, cosine_similarity) where similarity = 1 - cosine_distance.

        No ``embedding IS NOT NULL`` predicate: rows with a NULL vector are not
        present in a vector index at all, so the filter is dead weight the
        planner can only apply *after* the top-k, where it shrinks the
        candidate pool below ``limit``.
        """
        if not owner_identities:
            return []

        # Build a safe IN list for owner scoping (owner + corpus). Each value
        # becomes one prefix span on the vector index.
        owner_params = {f"o{i}": owner for i, owner in enumerate(owner_identities)}
        owner_placeholders = ", ".join(f":o{i}" for i in range(len(owner_identities)))
        sql = text(self.vector_candidates_sql(owner_placeholders))
        params: dict[str, object] = {
            "qv": query_vector_literal,
            "ready": EMBEDDING_STATUS_READY,
            "lim": limit,
            **owner_params,
        }
        result = await self._session.execute(sql, params)
        rows = result.all()
        if not rows:
            return []

        ids = [row[0] for row in rows]
        distance_by_id = {row[0]: float(row[1]) for row in rows}
        memories = await self._session.execute(
            select(MigrationMemory).where(MigrationMemory.id.in_(ids))
        )
        by_id = {m.id: m for m in memories.scalars().all()}
        ordered: list[tuple[MigrationMemory, float]] = []
        for mid in ids:
            mem = by_id.get(mid)
            if mem is None:
                continue
            dist = distance_by_id[mid]
            similarity = max(0.0, min(1.0, 1.0 - dist))
            ordered.append((mem, similarity))
        return ordered

    async def semantic_search(
        self,
        *,
        query_vector_literal: str,
        owner_identities: list[str] | None = None,
        migration_type: str | None = None,
        scale_tier: str | None = None,
        min_similarity: float = 0.0,
        limit: int = 10,
    ) -> tuple[list[tuple[MigrationMemory, float]], str | None]:
        """Free-text semantic search over graded memories.

        ``owner_identities=None`` searches the whole corpus; a list scopes to
        those owners (each value becomes one prefix span on the vector index).
        An *empty* list means "scoped to nobody" — no SQL is issued at all, so
        the caller gets an honest empty result rather than a silent widen to
        every tenant's memories.

        Returns ``(results, index_name)`` — the index name is surfaced to the
        UI so the distributed vector index is visible rather than merely
        claimed. ``index_name`` is ``None`` exactly when no query ran (the
        empty-scope case above); it is never a name attached to a query that
        was never executed.

        ``migration_type`` / ``scale_tier`` are applied in Python **after** the
        top-k, never in SQL. Putting them in the WHERE clause would make the
        query ineligible for the vector index — that is precisely the defect
        documented in docs/HACKATHON_INTEGRATION_AUDIT.md §1.4. We over-fetch
        and then narrow instead.
        """
        if owner_identities is not None and not owner_identities:
            return [], None

        post_filtering = bool(migration_type or scale_tier or min_similarity > 0.0)
        # Over-fetch only when something will be discarded afterwards.
        fetch = limit * _OVERFETCH_FACTOR if post_filtering else limit

        params: dict[str, object] = {
            "qv": query_vector_literal,
            "ready": EMBEDDING_STATUS_READY,
            "lim": fetch,
        }
        if owner_identities:
            params.update({f"o{i}": o for i, o in enumerate(owner_identities)})
            placeholders = ", ".join(f":o{i}" for i in range(len(owner_identities)))
            index_name = VECTOR_INDEX_SCOPED
        else:
            placeholders = None
            index_name = VECTOR_INDEX_READY

        result = await self._session.execute(
            text(self.semantic_search_sql(placeholders)), params
        )
        rows = result.all()
        if not rows:
            return [], index_name

        ids = [row[0] for row in rows]
        distance_by_id = {row[0]: float(row[1]) for row in rows}
        memories = await self._session.execute(
            select(MigrationMemory).where(MigrationMemory.id.in_(ids))
        )
        by_id = {m.id: m for m in memories.scalars().all()}

        ordered: list[tuple[MigrationMemory, float]] = []
        for mid in ids:
            mem = by_id.get(mid)
            if mem is None:
                continue
            similarity = max(0.0, min(1.0, 1.0 - distance_by_id[mid]))
            if similarity < min_similarity:
                continue
            if migration_type and mem.migration_type != migration_type:
                continue
            if scale_tier and mem.scale_tier != scale_tier:
                continue
            ordered.append((mem, similarity))
            if len(ordered) >= limit:
                break
        return ordered, index_name

    async def create(self, entity: MigrationMemory) -> MigrationMemory:
        return await super().create(entity)

    async def update(self, entity: MigrationMemory) -> MigrationMemory:
        return await super().update(entity)
