"""Memory retrieval interface.

Phase 9 defined the interface and shipped a stub. Phase 10 implements hybrid
retrieval behind the same interface (see ``app.memory.retrieval``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.logging import get_logger

logger = get_logger(__name__)


class RetrievedMemory(BaseModel):
    """One historical memory useful in a prompt and memory panel."""

    model_config = ConfigDict(frozen=True)

    memory_id: UUID | None = None
    migration_run_id: UUID | None = None
    migration_summary: str
    actual_duration_seconds: float | None = None
    actual_storage_mb: float | None = None
    predicted_duration_seconds: float | None = None
    predicted_storage_mb: float | None = None
    surprise_notes: str | None = None
    similarity_score: float = Field(ge=0.0, le=1.0)
    scale_tier: str | None = None
    # Integrity: open-source incidents are not graded shadow runs.
    memory_origin: str | None = None
    not_a_graded_run: bool = False
    source_url: str | None = None
    ui_label: str | None = None
    lessons_learned: str | None = None


class MemoryRetrievalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    memories: list[RetrievedMemory] = Field(default_factory=list)
    query_summary: str = ""
    # Full attribution (candidates, re-rank factors, prompt inclusion). Optional
    # so the Phase 9 stub stays simple; hybrid retrieval fills this in.
    attribution: dict[str, Any] | None = None
    weak_similarity_threshold: float = 0.5
    # Phase 11: distinguish empty retrieval from never-attempted.
    retrieval_attempted: bool = True
    retrieval_mode: str = "hybrid"  # hybrid | stub | skipped

    @property
    def is_empty(self) -> bool:
        return len(self.memories) == 0

    def to_prompt_context(self) -> list[dict[str, Any]]:
        return [m.model_dump(mode="json") for m in self.memories]

    def to_explainability(self) -> dict[str, Any]:
        weak = self.is_empty or all(
            m.similarity_score < self.weak_similarity_threshold for m in self.memories
        )
        base: dict[str, Any] = {
            "retrieval_attempted": self.retrieval_attempted,
            "retrieval_mode": self.retrieval_mode,
            "retrieved_count": len(self.memories),
            "memories": [m.model_dump(mode="json") for m in self.memories],
            "query_summary": self.query_summary,
            "weak_retrieval": weak if self.retrieval_attempted else None,
            "weak_similarity_threshold": self.weak_similarity_threshold,
            "empty_vs_never_attempted": (
                "never_attempted"
                if not self.retrieval_attempted
                else ("empty" if self.is_empty else "hits")
            ),
        }
        if self.attribution:
            base["attribution"] = self.attribution
        return base


class MemoryRetrieval(ABC):
    """Similarity search over graded outcomes (hybrid in Phase 10)."""

    @abstractmethod
    async def retrieve(
        self,
        *,
        migration_sql: str,
        statement_types: list[str],
        scale_tier: str | None,
        limit: int = 5,
    ) -> MemoryRetrievalResult:
        """Return similar past migrations. May be empty."""


class StubMemoryRetrieval(MemoryRetrieval):
    """Empty retrieval for offline tests that intentionally skip memory."""

    async def retrieve(
        self,
        *,
        migration_sql: str,
        statement_types: list[str],
        scale_tier: str | None,
        limit: int = 5,
    ) -> MemoryRetrievalResult:
        result = MemoryRetrievalResult(
            memories=[],
            query_summary=(
                f"stub retrieval (limit={limit}, tier={scale_tier}, "
                f"types={statement_types})"
            ),
            weak_similarity_threshold=0.5,
            retrieval_attempted=True,
            retrieval_mode="stub",
        )
        logger.info(
            "Memory retrieval attempt",
            extra={
                "retrieved_count": 0,
                "scale_tier": scale_tier,
                "statement_types": statement_types,
                "migration_sql_length": len(migration_sql),
                "limit": limit,
                "stub": True,
                "empty": True,
                "retrieval_mode": "stub",
            },
        )
        return result
