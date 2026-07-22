"""Hybrid retrieval: vector candidates → deterministic re-rank → top N."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.grading.config import get_grading_file
from app.grading.models import GradingFile
from app.memory.constants import CORPUS_OWNER_IDENTITY
from app.memory.embed_text import classify_migration_type
from app.memory.embedding_client import EmbeddingClient, vector_to_literal
from app.prediction.memory import (
    MemoryRetrieval,
    MemoryRetrievalResult,
    RetrievedMemory,
)
from app.repositories.migration_memory_repository import MigrationMemoryRepository

logger = get_logger(__name__)


def _tier_proximity(
    query_tier: str | None,
    memory_tier: str,
    adjacent: set[frozenset[str]],
) -> float:
    if not query_tier:
        return 0.5
    if query_tier == memory_tier:
        return 1.0
    if frozenset({query_tier, memory_tier}) in adjacent:
        return 0.5
    return 0.0


def _flag_ids(flags: list[dict[str, Any]] | None) -> set[str]:
    ids: set[str] = set()
    for f in flags or []:
        if isinstance(f, dict) and f.get("rule_id"):
            ids.add(str(f["rule_id"]))
    return ids


def _flag_overlap(query_flags: set[str], memory_flags: list[dict[str, Any]]) -> float:
    mem_ids = _flag_ids(memory_flags)
    if not query_flags and not mem_ids:
        return 1.0
    if not query_flags or not mem_ids:
        return 0.0
    inter = len(query_flags & mem_ids)
    union = len(query_flags | mem_ids)
    return inter / union if union else 0.0


def _shape_score(
    *,
    query_index_count: int | None,
    query_complexity: int | None,
    mem_index_count: int,
    mem_complexity: int,
) -> float:
    if query_index_count is None and query_complexity is None:
        return 0.5
    qi = query_index_count or 0
    qc = query_complexity or 0
    # Inverse relative difference, clamped.
    idx_diff = abs(qi - mem_index_count) / max(qi, mem_index_count, 1)
    cx_diff = abs(qc - mem_complexity) / max(qc, mem_complexity, 1)
    return max(0.0, 1.0 - (idx_diff + cx_diff) / 2.0)


class HybridMemoryRetrieval(MemoryRetrieval):
    """Phase 10 retrieval behind the Phase 9 MemoryRetrieval interface."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        embedding_client: EmbeddingClient,
        repository: MigrationMemoryRepository | None = None,
        config: GradingFile | None = None,
        owner_identity: str = "anonymous",
        query_risk_flags: list[dict[str, Any]] | None = None,
        query_index_count: int | None = None,
        query_table_complexity: int | None = None,
    ) -> None:
        self._session = session
        self._embed = embedding_client
        self._repo = repository or MigrationMemoryRepository(session)
        self._config = config
        self._owner_identity = owner_identity
        self._query_risk_flags = query_risk_flags or []
        self._query_index_count = query_index_count
        self._query_table_complexity = query_table_complexity
        # Last attribution payload (also returned via to_explainability).
        self.last_attribution: dict[str, Any] | None = None

    def with_request_context(
        self,
        *,
        owner_identity: str,
        query_risk_flags: list[dict[str, Any]] | None = None,
        query_index_count: int | None = None,
        query_table_complexity: int | None = None,
    ) -> HybridMemoryRetrieval:
        """Return a shallow copy bound to the current prediction request."""
        clone = HybridMemoryRetrieval(
            session=self._session,
            embedding_client=self._embed,
            repository=self._repo,
            config=self._config,
            owner_identity=owner_identity,
            query_risk_flags=query_risk_flags,
            query_index_count=query_index_count,
            query_table_complexity=query_table_complexity,
        )
        return clone

    async def retrieve(
        self,
        *,
        migration_sql: str,
        statement_types: list[str],
        scale_tier: str | None,
        limit: int = 5,
        owner_identity: str | None = None,
        risk_flags: list[dict[str, Any]] | None = None,
    ) -> MemoryRetrievalResult:
        cfg = self._config or get_grading_file()
        owner = (owner_identity or self._owner_identity).strip() or "anonymous"
        flags = risk_flags if risk_flags is not None else self._query_risk_flags
        query_flag_ids = _flag_ids(flags)
        migration_type = classify_migration_type(statement_types, migration_sql)

        # Embed a query text focused on mechanism, not raw DDL dominance.
        query_text = (
            f"Migration type {migration_type}. "
            f"Statement types: {', '.join(statement_types) or 'unknown'}. "
            f"Scale tier: {scale_tier or 'unknown'}. "
            f"DDL: {migration_sql[:500]}"
        )
        vector = self._embed.embed(query_text)
        literal = vector_to_literal(vector)

        pool = cfg.retrieval.candidate_pool_size
        final_limit = min(limit, cfg.retrieval.final_limit)
        scopes = [owner, CORPUS_OWNER_IDENTITY]
        # Deduplicate if owner happens to be the corpus constant.
        scopes = list(dict.fromkeys(scopes))

        candidates = await self._repo.vector_candidates(
            query_vector_literal=literal,
            owner_identities=scopes,
            limit=pool,
        )

        adjacent = {
            frozenset(pair) for pair in cfg.retrieval.adjacent_tiers
        }
        weights = cfg.retrieval.weights
        weight_sum = (
            weights.semantic_similarity
            + weights.migration_type_match
            + weights.scale_tier_proximity
            + weights.schema_shape
            + weights.risk_flag_overlap
        ) or 1.0

        scored: list[dict[str, Any]] = []
        for mem, similarity in candidates:
            type_match = 1.0 if mem.migration_type == migration_type else 0.0
            tier_score = _tier_proximity(scale_tier, mem.scale_tier, adjacent)
            shape = _shape_score(
                query_index_count=self._query_index_count,
                query_complexity=self._query_table_complexity,
                mem_index_count=mem.index_count,
                mem_complexity=mem.table_complexity,
            )
            flag_score = _flag_overlap(query_flag_ids, mem.risk_flags)
            final = (
                weights.semantic_similarity * similarity
                + weights.migration_type_match * type_match
                + weights.scale_tier_proximity * tier_score
                + weights.schema_shape * shape
                + weights.risk_flag_overlap * flag_score
            ) / weight_sum
            scored.append(
                {
                    "memory": mem,
                    "similarity_score": similarity,
                    "final_score": final,
                    "factors": {
                        "semantic_similarity": similarity,
                        "migration_type_match": type_match,
                        "scale_tier_proximity": tier_score,
                        "schema_shape": shape,
                        "risk_flag_overlap": flag_score,
                    },
                }
            )

        scored.sort(key=lambda row: row["final_score"], reverse=True)
        top = scored[:final_limit]
        threshold = cfg.retrieval.weak_similarity_threshold

        retrieved: list[RetrievedMemory] = []
        attribution_rows: list[dict[str, Any]] = []
        for rank, row in enumerate(top, start=1):
            mem = row["memory"]
            pred = mem.prediction_summary or {}
            exe = mem.execution_summary or {}
            retrieved.append(
                RetrievedMemory(
                    migration_run_id=mem.migration_run_id,
                    migration_summary=mem.migration_summary,
                    actual_duration_seconds=exe.get("actual_duration_seconds"),
                    actual_storage_mb=exe.get("actual_storage_mb"),
                    predicted_duration_seconds=pred.get("estimated_duration_seconds"),
                    predicted_storage_mb=pred.get("estimated_storage_mb"),
                    surprise_notes=mem.surprise_notes,
                    similarity_score=round(float(row["similarity_score"]), 6),
                    scale_tier=mem.scale_tier,
                )
            )
            attribution_rows.append(
                {
                    "rank": rank,
                    "memory_id": str(mem.id),
                    "migration_run_id": str(mem.migration_run_id),
                    "owner_identity": mem.owner_identity,
                    "migration_type": mem.migration_type,
                    "scale_tier": mem.scale_tier,
                    "similarity_score": round(float(row["similarity_score"]), 6),
                    "final_score": round(float(row["final_score"]), 6),
                    "re_rank_factors": row["factors"],
                    "included_in_prompt": True,
                    "migration_summary": mem.migration_summary,
                    "lessons_learned": mem.lessons_learned,
                    "surprise_notes": mem.surprise_notes,
                    "scalar_accuracy_score": (mem.grade_summary or {}).get(
                        "scalar_accuracy_score"
                    ),
                }
            )

        # Candidates not in top-N still recorded for audit.
        truncated = []
        for rank, row in enumerate(scored[final_limit:], start=final_limit + 1):
            mem = row["memory"]
            truncated.append(
                {
                    "rank": rank,
                    "memory_id": str(mem.id),
                    "migration_run_id": str(mem.migration_run_id),
                    "similarity_score": round(float(row["similarity_score"]), 6),
                    "final_score": round(float(row["final_score"]), 6),
                    "re_rank_factors": row["factors"],
                    "included_in_prompt": False,
                }
            )

        result = MemoryRetrievalResult(
            memories=retrieved,
            query_summary=(
                f"hybrid retrieval owner={owner} corpus={CORPUS_OWNER_IDENTITY} "
                f"type={migration_type} tier={scale_tier} "
                f"candidates={len(candidates)} returned={len(retrieved)}"
            ),
            attribution={
                "candidate_count": len(candidates),
                "owner_identity": owner,
                "corpus_identity": CORPUS_OWNER_IDENTITY,
                "migration_type": migration_type,
                "scale_tier": scale_tier,
                "memories": attribution_rows,
                "truncated_candidates": truncated,
            },
            weak_similarity_threshold=threshold,
            retrieval_attempted=True,
            retrieval_mode="hybrid",
        )
        weak = result.is_empty or all(
            m.similarity_score < threshold for m in result.memories
        )
        self.last_attribution = {
            **(result.attribution or {}),
            "retrieved_count": len(retrieved),
            "query_summary": result.query_summary,
            "weak_retrieval": weak,
            "weak_similarity_threshold": threshold,
        }

        logger.info(
            "Memory retrieval attempt",
            extra={
                "retrieved_count": len(retrieved),
                "candidate_count": len(candidates),
                "scale_tier": scale_tier,
                "statement_types": statement_types,
                "owner_identity": owner,
                "weak_retrieval": weak,
                "empty": result.is_empty,
            },
        )
        return result
