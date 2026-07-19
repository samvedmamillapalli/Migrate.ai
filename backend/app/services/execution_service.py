from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.database.models import ExecutionResult
from app.database.retry import with_txn_retry
from app.repositories.execution_result_repository import ExecutionResultRepository

if TYPE_CHECKING:
    from app.services.grading_pipeline_service import GradingPipelineService

logger = get_logger(__name__)


class ExecutionService:
    """Persist the outcome of running a migration on a shadow cluster.

    One ExecutionResult per migration run (unique ``migration_run_id``); an
    existing row is updated so re-runs are idempotent. Owns its transaction
    boundary, consistent with the Phase 4 service pattern.

    After a successful persist, optionally runs Phase 10 grading + memory
    write via ``grading_pipeline`` (2A: hook into persist path; no SFN state).
    """

    def __init__(
        self,
        repository: ExecutionResultRepository,
        session: AsyncSession,
        grading_pipeline: GradingPipelineService | None = None,
    ) -> None:
        self._repository = repository
        self._session = session
        self._grading = grading_pipeline

    async def record_execution(
        self,
        run_id: uuid.UUID,
        *,
        success: bool,
        duration_seconds: float,
        storage_mb: float,
        rollback_required: bool,
        error_message: str | None = None,
        timed_out: bool = False,
        grade: bool = True,
    ) -> ExecutionResult:
        async def _commit() -> ExecutionResult:
            existing = await self._repository.get_by_migration_run_id(run_id)
            if existing is None:
                entity = ExecutionResult(
                    migration_run_id=run_id,
                    success=success,
                    actual_duration_seconds=duration_seconds,
                    actual_storage_mb=storage_mb,
                    rollback_required=rollback_required,
                    timed_out=timed_out,
                    error_message=(error_message or None) and error_message[:2000],
                )
                entity = await self._repository.create(entity)
            else:
                existing.success = success
                existing.actual_duration_seconds = duration_seconds
                existing.actual_storage_mb = storage_mb
                existing.rollback_required = rollback_required
                existing.timed_out = timed_out
                existing.error_message = error_message[:2000] if error_message else None
                entity = await self._repository.update(existing)
            await self._session.commit()
            await self._session.refresh(entity)
            return entity

        result = await with_txn_retry(_commit, on_retry=self._session.rollback)
        logger.info(
            "Recorded execution result",
            extra={
                "run_id": str(run_id),
                "success": success,
                "duration_seconds": round(duration_seconds, 4),
                "rollback_required": rollback_required,
                "timed_out": timed_out,
            },
        )

        if grade and self._grading is not None:
            try:
                await self._grading.grade_run(run_id)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "Automatic grading after persist failed",
                    extra={"run_id": str(run_id), "error": str(exc)},
                )
                if isinstance(exc, ValidationError):
                    logger.warning(
                        "Grading skipped (missing prediction or invalid state)",
                        extra={"run_id": str(run_id), "detail": exc.message},
                    )

        return result


__all__ = ["ExecutionService"]
