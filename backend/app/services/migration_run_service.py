from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ValidationError
from app.core.logging import get_logger
from app.database.models import MigrationRun, MigrationRunStatus, SchemaDiscoveryStatus
from app.database.retry import with_txn_retry
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
            MigrationRunStatus.AWAITING_APPROVAL,
            MigrationRunStatus.FAILED,
        }
    ),
    MigrationRunStatus.AWAITING_APPROVAL: frozenset(
        {
            # proceed → shadow execution
            MigrationRunStatus.RUNNING,
            # accept_recommended → end this run (no AI SQL executed)
            MigrationRunStatus.COMPLETED,
            # cancel
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

    async def create_migration_run(
        self,
        migration_sql: str,
        *,
        owner_identity: str = "anonymous",
        revises_run_id: uuid.UUID | None = None,
    ) -> MigrationRun:
        normalized_sql = migration_sql.strip()
        if not normalized_sql:
            raise ValidationError("migration_sql must not be empty")
        identity = (owner_identity or "anonymous").strip() or "anonymous"
        if len(identity) > 256:
            raise ValidationError("owner_identity must be at most 256 characters")

        if revises_run_id is not None:
            # Ensure the referenced run exists (soft link; no cascade).
            await self._repository.get_by_id_or_raise(revises_run_id)

        async def _commit() -> MigrationRun:
            run = MigrationRun(
                migration_sql=normalized_sql,
                status=MigrationRunStatus.PENDING,
                schema_discovery_status=SchemaDiscoveryStatus.PENDING,
                owner_identity=identity,
                revises_run_id=revises_run_id,
            )
            created = await self._repository.create(run)
            await self._session.commit()
            await self._session.refresh(created)
            return created

        created = await with_txn_retry(
            _commit,
            on_retry=self._session.rollback,
        )

        logger.info(
            "Created migration run",
            extra={
                "run_id": str(created.id),
                "status": created.status.value,
                "owner_identity": identity,
                "revises_run_id": str(revises_run_id) if revises_run_id else None,
            },
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

    async def count_migration_runs(
        self,
        *,
        status: MigrationRunStatus | None = None,
    ) -> int:
        return await self._repository.count(status=status)

    async def update_status(
        self,
        run_id: uuid.UUID,
        new_status: MigrationRunStatus,
    ) -> MigrationRun:
        async def _commit() -> tuple[MigrationRun, MigrationRunStatus]:
            run = await self._repository.get_by_id_or_raise(run_id)
            self._validate_status_transition(run.status, new_status)

            previous = run.status
            run.status = new_status
            updated = await self._repository.update(run)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated, previous

        updated, previous = await with_txn_retry(
            _commit,
            on_retry=self._session.rollback,
        )

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
        async def _commit() -> None:
            await self._repository.delete_by_id(run_id)
            await self._session.commit()

        await with_txn_retry(
            _commit,
            on_retry=self._session.rollback,
        )
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
