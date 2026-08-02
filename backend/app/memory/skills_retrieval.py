"""Vector-only retrieval over CockroachDB Agent Skills — no re-ranking.

Simpler than ``HybridMemoryRetrieval`` deliberately: skills have no owner
scoping, no graded-outcome history to re-rank against, and no scale-tier
proximity concept. Cosine similarity from the query embedding is the whole
signal.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.memory.embedding_client import EmbeddingClient, vector_to_literal
from app.prediction.skills import RetrievedSkill, SkillsRetrieval, SkillsRetrievalResult
from app.repositories.skill_doc_repository import SkillDocRepository

logger = get_logger(__name__)


class CockroachDBSkillsRetrieval(SkillsRetrieval):
    """Semantic search over the vendored CockroachDB Agent Skills Repo."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        embedding_client: EmbeddingClient,
        repository: SkillDocRepository | None = None,
    ) -> None:
        self._session = session
        self._embed = embedding_client
        self._repo = repository or SkillDocRepository(session)

    async def retrieve(
        self,
        *,
        migration_sql: str,
        risk_narrative: str,
        limit: int = 3,
    ) -> SkillsRetrievalResult:
        query = f"{migration_sql}\n\n{risk_narrative}".strip()
        if not query:
            return SkillsRetrievalResult(
                skills=[],
                query_summary="empty query (no migration SQL or risk narrative)",
                retrieval_attempted=False,
                retrieval_mode="skipped",
            )

        try:
            vector = self._embed.embed(query)
            rows, index_used = await self._repo.semantic_search(
                query_vector_literal=vector_to_literal(vector),
                limit=limit,
            )
        except Exception as exc:  # noqa: BLE001 - enrichment, never blocks prediction
            logger.warning(
                "CockroachDB skills retrieval failed",
                extra={"error": f"{type(exc).__name__}: {exc}"},
            )
            return SkillsRetrievalResult(
                skills=[],
                query_summary=f"retrieval failed: {type(exc).__name__}",
                retrieval_attempted=True,
                retrieval_mode="vector",
            )

        skills = [
            RetrievedSkill(
                skill_id=doc.id,
                skill_slug=doc.skill_slug,
                title=doc.title,
                category=doc.category,
                description=doc.description,
                source_url=doc.source_url,
                similarity_score=similarity,
            )
            for doc, similarity in rows
        ]
        logger.info(
            "CockroachDB skills retrieval served",
            extra={"hits": len(skills), "index_used": index_used},
        )
        return SkillsRetrievalResult(
            skills=skills,
            query_summary=f"vector search (limit={limit}, index={index_used})",
            retrieval_attempted=True,
            retrieval_mode="vector",
        )
