from __future__ import annotations

from sqlalchemy import select, text

from app.database.models import CockroachDBSkillDoc
from app.memory.constants import EMBEDDING_STATUS_READY, VECTOR_INDEX_SKILL_DOCS
from app.repositories.base import BaseRepository


class SkillDocRepository(BaseRepository[CockroachDBSkillDoc]):
    """Semantic search over the vendored CockroachDB Agent Skills Repo.

    Mirrors ``MigrationMemoryRepository.semantic_search`` deliberately: same
    over-fetch-then-Python-filter shape, same reason — this table has no
    tenancy dimension, so there is no owner predicate to worry about, but any
    future structural filter (e.g. by category) must stay out of the WHERE
    clause for the same reason it must for migration_memories: it would
    disqualify ``ix_skill_docs_embedding_ready`` for the same structural
    reason documented in docs/HACKATHON_INTEGRATION_AUDIT.md §1.
    """

    model = CockroachDBSkillDoc

    @staticmethod
    def semantic_search_sql(*, index_hint: str | None = None) -> str:
        """Exposed so verification scripts can EXPLAIN the exact query issued."""
        table = "cockroachdb_skill_docs"
        if index_hint:
            table = f"{table}@{index_hint}"
        return f"""
            SELECT
                id,
                (embedding <=> CAST(:qv AS VECTOR(1024))) AS distance
            FROM {table}
            WHERE embedding_status = :ready
            ORDER BY embedding <=> CAST(:qv AS VECTOR(1024))
            LIMIT :lim
            """

    async def semantic_search(
        self,
        *,
        query_vector_literal: str,
        limit: int = 5,
    ) -> tuple[list[tuple[CockroachDBSkillDoc, float]], str | None]:
        """Nearest skills via CockroachDB VECTOR cosine distance.

        Returns ``(results, index_name)`` — same contract as
        ``MigrationMemoryRepository.semantic_search``, so the UI/tool-result
        formatting can show a real index name, not a claim.
        """
        params: dict[str, object] = {
            "qv": query_vector_literal,
            "ready": EMBEDDING_STATUS_READY,
            "lim": limit,
        }
        result = await self._session.execute(
            text(self.semantic_search_sql()), params
        )
        rows = result.all()
        if not rows:
            return [], VECTOR_INDEX_SKILL_DOCS

        ids = [row[0] for row in rows]
        distance_by_id = {row[0]: float(row[1]) for row in rows}
        docs = await self._session.execute(
            select(CockroachDBSkillDoc).where(CockroachDBSkillDoc.id.in_(ids))
        )
        by_id = {d.id: d for d in docs.scalars().all()}

        ordered: list[tuple[CockroachDBSkillDoc, float]] = []
        for did in ids:
            doc = by_id.get(did)
            if doc is None:
                continue
            similarity = max(0.0, min(1.0, 1.0 - distance_by_id[did]))
            ordered.append((doc, similarity))
        return ordered, VECTOR_INDEX_SKILL_DOCS
