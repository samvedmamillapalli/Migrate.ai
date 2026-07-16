from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ValidationError
from app.core.logging import get_logger
from app.database.models import MigrationRun, MigrationRunStatus
from app.repositories.migration_run_repository import MigrationRunRepository

logger = get_logger(__name__)

ALLOWED_STATUS_TRANSITIONS: dict[MigrationRunStatus, frozenset[MigrationRunStatus]] = {
    MigrationRunStatus.PENDING: frozenset(
        {
            MigrationRunStatus.PREDICTING,
            MigrationRunStatus.FAILED,
        }
    ),
    MigrationRunStatus.PREDICTING: frozenset(
        {
            MigrationRunStatus.RUNNING,
            MigrationRunStatus.FAILED,
        }
    ),
    MigrationRunStatus.RUNNING: frozenset(
        {
            MigrationRunStatus.COMPLETED,
            MigrationRunStatus.FAILED,
        }
    ),
    MigrationRunStatus.COMPLETED: frozenset(),
    MigrationRunStatus.FAILED: frozenset(),
}


class MigrationRunService:
    """Business logic for MigrationRun lifecycle operations."""

    def __init__(
        self,
        repository: MigrationRunRepository,
        session: AsyncSession,
    ) -> None:
        self._repository = repository
        self._session = session

    async def create_migration_run(self, migration_sql: str) -> MigrationRun:
        normalized_sql = migration_sql.strip()
        if not normalized_sql:
            raise ValidationError("migration_sql must not be empty")

        run = MigrationRun(
            migration_sql=normalized_sql,
            status=MigrationRunStatus.PENDING,
        )
        created = await self._repository.create(run)
        await self._session.commit()
        await self._session.refresh(created)

        logger.info(
            "Created migration run",
            extra={"run_id": str(created.id), "status": created.status.value},
        )
        return created

    async def get_migration_run(
        self,
        run_id: uuid.UUID,
        *,
        load_children: bool = False,
    ) -> MigrationRun:
        return await self._repository.get_by_id_or_raise(
            run_id,
            load_children=load_children,
        )

    async def list_migration_runs(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: MigrationRunStatus | None = None,
    ) -> list[MigrationRun]:
        if offset < 0:
            raise ValidationError("offset must be >= 0")
        if limit < 1 or limit > 100:
            raise ValidationError("limit must be between 1 and 100")

        return await self._repository.list(
            offset=offset,
            limit=limit,
            status=status,
        )

    async def update_status(
        self,
        run_id: uuid.UUID,
        new_status: MigrationRunStatus,
    ) -> MigrationRun:
        run = await self._repository.get_by_id_or_raise(run_id)
        self._validate_status_transition(run.status, new_status)

        previous = run.status
        run.status = new_status
        updated = await self._repository.update(run)
        await self._session.commit()
        await self._session.refresh(updated)

        logger.info(
            "Updated migration run status",
            extra={
                "run_id": str(updated.id),
                "from_status": previous.value,
                "to_status": updated.status.value,
            },
        )
        return updated

    async def delete_migration_run(self, run_id: uuid.UUID) -> None:
        await self._repository.delete_by_id(run_id)
        await self._session.commit()
        logger.info("Deleted migration run", extra={"run_id": str(run_id)})

    @staticmethod
    def _validate_status_transition(
        current: MigrationRunStatus,
        new_status: MigrationRunStatus,
    ) -> None:
        if current == new_status:
            raise ConflictError(
                f"MigrationRun is already in status '{current.value}'"
            )

        allowed = ALLOWED_STATUS_TRANSITIONS.get(current, frozenset())
        if new_status not in allowed:
            raise ConflictError(
                f"Invalid status transition: {current.value} -> {new_status.value}"
            )


__all__ = ["ALLOWED_STATUS_TRANSITIONS", "MigrationRunService"]
