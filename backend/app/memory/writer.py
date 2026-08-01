"""Write graded run memories and repair pending embeddings."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.models import (
    Approval,
    ExecutionResult,
    Grade,
    MigrationMemory,
    MigrationRun,
    Prediction,
)
from app.database.retry import with_txn_retry
from app.memory.constants import (
    EMBEDDING_STATUS_FAILED,
    EMBEDDING_STATUS_PENDING,
    EMBEDDING_STATUS_READY,
)
from app.memory.embed_text import (
    classify_migration_type,
    compose_embed_text,
    summarize_migration,
    summarize_schema,
)
from app.memory.embedding_client import (
    EmbeddingClient,
    EmbeddingAccessError,
    EmbeddingInvocationError,
    vector_to_literal,
)
from app.repositories.migration_memory_repository import MigrationMemoryRepository

logger = get_logger(__name__)


def _prediction_summary(prediction: Prediction) -> dict[str, Any]:
    return {
        "estimated_duration_seconds": prediction.estimated_duration_seconds,
        "estimated_storage_mb": prediction.estimated_storage_mb,
        "rollback_risk": (
            prediction.rollback_risk.value
            if hasattr(prediction.rollback_risk, "value")
            else str(prediction.rollback_risk)
        ),
        "confidence_score": prediction.confidence_score,
        "raw_confidence_score": prediction.raw_confidence_score,
        "risk_explanation": prediction.reasoning,
    }


def _execution_summary(execution: ExecutionResult) -> dict[str, Any]:
    return {
        "success": execution.success,
        "actual_duration_seconds": execution.actual_duration_seconds,
        "actual_storage_mb": execution.actual_storage_mb,
        "rollback_required": execution.rollback_required,
        "timed_out": execution.timed_out,
        "error_message": execution.error_message,
    }


def _grade_summary(grade: Grade) -> dict[str, Any]:
    return {
        "scalar_accuracy_score": grade.scalar_accuracy_score,
        "scale_tier": grade.scale_tier,
        "timed_out": grade.timed_out,
        "duration_within_band": grade.duration_within_band,
        "storage_within_band": grade.storage_within_band,
        "rollback_within_band": grade.rollback_within_band,
        "outcome_class": grade.outcome_class,
        "dimension_details": grade.dimension_details,
    }


def _approval_summary(approval: Approval | None) -> dict[str, Any] | None:
    if approval is None:
        return None
    return {
        "decision": (
            approval.decision.value
            if hasattr(approval.decision, "value")
            else str(approval.decision)
        ),
        "approver_identity": approval.approver_identity,
        "override_rationale": approval.override_rationale,
    }


class MemoryWriteService:
    """Persist migration_memories after grading; embed with Titan when possible."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        repository: MigrationMemoryRepository,
        embedding_client: EmbeddingClient | None,
        embedding_model_id: str | None = None,
    ) -> None:
        self._session = session
        self._repo = repository
        self._embed = embedding_client
        self._model_id = (embedding_model_id or "").strip() or None

    async def write_memory(
        self,
        *,
        run: MigrationRun,
        prediction: Prediction,
        execution: ExecutionResult,
        grade: Grade,
    ) -> MigrationMemory:
        migration_type = classify_migration_type(
            run.parsed_statement_types,
            run.migration_sql,
        )
        migration_summary = summarize_migration(run.migration_sql, migration_type)
        schema_summary, index_count, complexity = summarize_schema(run.schema_snapshot)
        risk_narrative = prediction.reasoning or ""
        embed_text = compose_embed_text(
            migration_summary=migration_summary,
            risk_narrative=risk_narrative,
            lessons_learned=grade.lessons_learned,
            surprise_notes=grade.surprise_notes,
            migration_sql=run.migration_sql,
        )

        embedding_literal: str | None = None
        embedding_status = EMBEDDING_STATUS_PENDING
        embedding_error: str | None = None
        if self._embed is not None:
            try:
                vector = self._embed.embed(embed_text, model_id=self._model_id)
                embedding_literal = vector_to_literal(vector)
                embedding_status = EMBEDDING_STATUS_READY
            except (EmbeddingAccessError, EmbeddingInvocationError, Exception) as exc:
                embedding_status = EMBEDDING_STATUS_PENDING
                embedding_error = f"{type(exc).__name__}: {exc}"[:2000]
                logger.warning(
                    "Embedding failed; memory left pending",
                    extra={"run_id": str(run.id), "error": embedding_error},
                )

        async def _commit() -> MigrationMemory:
            existing = await self._repo.get_by_migration_run_id(run.id)
            payload = dict(
                owner_identity=run.owner_identity or "anonymous",
                scale_tier=grade.scale_tier,
                migration_type=migration_type,
                migration_summary=migration_summary,
                schema_summary=schema_summary,
                risk_flags=list(run.risk_flags or []),
                prediction_summary=_prediction_summary(prediction),
                recommendation_summary=run.recommendation,
                approval_summary=_approval_summary(run.approval),
                execution_summary=_execution_summary(execution),
                grade_summary=_grade_summary(grade),
                lessons_learned=grade.lessons_learned,
                surprise_notes=grade.surprise_notes,
                embed_text=embed_text,
                embedding=embedding_literal,
                embedding_status=embedding_status,
                embedding_error=embedding_error,
                embedding_model_id=self._model_id,
                index_count=index_count,
                table_complexity=complexity,
            )
            if existing is None:
                entity = MigrationMemory(migration_run_id=run.id, **payload)
                entity = await self._repo.create(entity)
            else:
                for key, value in payload.items():
                    setattr(existing, key, value)
                entity = await self._repo.update(existing)
            await self._session.commit()
            await self._session.refresh(entity)
            return entity

        memory = await with_txn_retry(_commit, on_retry=self._session.rollback)
        logger.info(
            "Wrote migration memory",
            extra={
                "run_id": str(run.id),
                "memory_id": str(memory.id),
                "embedding_status": memory.embedding_status,
            },
        )
        return memory

    async def repair_pending_embedding(
        self,
        *,
        memory_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        limit: int = 20,
    ) -> list[MigrationMemory]:
        """Retry Titan embed for pending memories (admin/maintenance path)."""
        if self._embed is None:
            raise EmbeddingInvocationError(
                "No embedding client configured; cannot repair pending embeddings"
            )

        if run_id is not None:
            mem = await self._repo.get_by_migration_run_id(run_id)
            targets = [mem] if mem is not None else []
        elif memory_id is not None:
            mem = await self._repo.get_by_id(memory_id)
            targets = [mem] if mem is not None else []
        else:
            targets = await self._repo.list_pending_embeddings(limit=limit)

        repaired: list[MigrationMemory] = []
        for mem in targets:
            if mem is None:
                continue
            try:
                vector = self._embed.embed(mem.embed_text, model_id=self._model_id)
                mem.embedding = vector_to_literal(vector)
                mem.embedding_status = EMBEDDING_STATUS_READY
                mem.embedding_error = None
                mem.embedding_model_id = self._model_id
            except Exception as exc:  # noqa: BLE001
                mem.embedding_status = EMBEDDING_STATUS_FAILED
                mem.embedding_error = f"{type(exc).__name__}: {exc}"[:2000]
            await self._repo.update(mem)
            repaired.append(mem)

        await self._session.commit()
        return repaired
