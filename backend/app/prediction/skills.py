"""CockroachDB Agent Skills retrieval interface for the prediction/
recommendation prompts — RAG-style context injection, mirroring
``app.prediction.memory`` deliberately.

Unlike the blast-radius investigation's ``search_cockroachdb_skills`` tool
(an agent-driven call the model chooses to make mid-investigation), this
retrieval runs unconditionally, once, before either Bedrock call — the
predictor and recommender make a single ``generate()`` call each with no
tool-use loop, so retrieval is pre-fetched and injected as prompt context
instead, the same way ``MemoryRetrievalResult`` is.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.logging import get_logger

logger = get_logger(__name__)


class RetrievedSkill(BaseModel):
    """One CockroachDB Agent Skill useful in a prompt and citation panel."""

    model_config = ConfigDict(frozen=True)

    skill_id: UUID | None = None
    skill_slug: str
    title: str
    category: str
    description: str
    source_url: str
    similarity_score: float = Field(ge=0.0, le=1.0)


class SkillsRetrievalResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    skills: list[RetrievedSkill] = Field(default_factory=list)
    query_summary: str = ""
    retrieval_attempted: bool = True
    retrieval_mode: str = "vector"  # vector | stub | skipped

    @property
    def is_empty(self) -> bool:
        return len(self.skills) == 0

    def to_prompt_context(self) -> list[dict[str, Any]]:
        return [s.model_dump(mode="json") for s in self.skills]

    def to_explainability(self) -> dict[str, Any]:
        return {
            "retrieval_attempted": self.retrieval_attempted,
            "retrieval_mode": self.retrieval_mode,
            "retrieved_count": len(self.skills),
            "skills": [s.model_dump(mode="json") for s in self.skills],
            "query_summary": self.query_summary,
        }


class SkillsRetrieval(ABC):
    """Similarity search over the vendored CockroachDB Agent Skills Repo."""

    @abstractmethod
    async def retrieve(
        self,
        *,
        migration_sql: str,
        risk_narrative: str,
        limit: int = 3,
    ) -> SkillsRetrievalResult:
        """Return relevant CockroachDB Agent Skills. May be empty."""


class StubSkillsRetrieval(SkillsRetrieval):
    """Empty retrieval for offline tests / when Bedrock embeddings are unavailable."""

    async def retrieve(
        self,
        *,
        migration_sql: str,
        risk_narrative: str,
        limit: int = 3,
    ) -> SkillsRetrievalResult:
        return SkillsRetrievalResult(
            skills=[],
            query_summary="stub retrieval (skills lookup skipped)",
            retrieval_attempted=True,
            retrieval_mode="stub",
        )
