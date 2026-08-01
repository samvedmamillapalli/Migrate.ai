from __future__ import annotations

import uuid

import sqlglot
from sqlglot.errors import ParseError
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timezone

from app.core.exceptions import ConflictError, ValidationError
from app.core.logging import get_logger
from app.database.models import MigrationRun, MigrationRunStatus, SchemaDiscoveryStatus
from app.database.retry import with_txn_retry
from app.debug.fake_migration import build_fake_schema_snapshot, pick_fake_migration
from app.repositories.migration_run_repository import MigrationRunRepository

logger = get_logger(__name__)

# Same dialect/parse convention as app.policy.engine and app.shadow.schema_snapshot.
_SQL_DIALECT = "postgres"


def _statement_count(sql: str) -> int:
    """Best-effort count of top-level SQL statements.

    Unparseable SQL is treated as a single statement here — sqlglot's own
    parse failure is a *different*, already-handled problem (surfaced by the
    policy engine at predict time as a ``parse_failure`` finding), not this
    check's job to report.
    """
    try:
        statements = sqlglot.parse(sql, dialect=_SQL_DIALECT)
    except ParseError:
        return 1
    return len([s for s in statements if s is not None])

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
        run_kind: str = "standard",
    ) -> MigrationRun:
        normalized_sql = migration_sql.strip()
        if not normalized_sql:
            raise ValidationError("migration_sql must not be empty")
        if _statement_count(normalized_sql) > 1:
            raise ValidationError(
                "migration_sql must be a single SQL statement. CockroachDB "
                "commits DDL per-statement, so if a later statement in a "
                "multi-statement migration fails, the earlier ones stay "
                "applied — a rollback can't be guaranteed. Submit one "
                "statement per migration run."
            )
        identity = (owner_identity or "anonymous").strip() or "anonymous"
        if len(identity) > 256:
            raise ValidationError("owner_identity must be at most 256 characters")
        kind = (run_kind or "standard").strip().lower() or "standard"
        if kind not in {"standard", "chaos", "debug"}:
            raise ValidationError("run_kind must be one of: standard, chaos, debug")

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
                run_kind=kind,
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

    async def create_debug_fake_migration(
        self,
        *,
        owner_identity: str = "debug",
    ) -> MigrationRun:
        """Create a pending run with random SQL + synthetic schema (debug only).

        Does not write grades or memories. Schema is clearly marked debug_synthetic.
        """
        picked = pick_fake_migration()
        snapshot = build_fake_schema_snapshot(for_migration=picked)
        identity = (owner_identity or "debug").strip() or "debug"

        async def _commit() -> MigrationRun:
            run = MigrationRun(
                migration_sql=picked["migration_sql"],
                status=MigrationRunStatus.PENDING,
                owner_identity=identity,
                run_kind="debug",
                schema_snapshot=snapshot,
                schema_discovery_status=SchemaDiscoveryStatus.SUCCEEDED,
                schema_discovered_at=datetime.now(timezone.utc),
                schema_discovery_duration_ms=0.0,
                schema_database_engine="cockroachdb",
                schema_database_version="debug-synthetic",
            )
            created = await self._repository.create(run)
            await self._session.commit()
            await self._session.refresh(created)
            return created

        created = await with_txn_retry(_commit, on_retry=self._session.rollback)
        logger.info(
            "Created debug fake migration run",
            extra={
                "run_id": str(created.id),
                "kind": picked["kind"],
                "debug": True,
            },
        )
        return created

    async def set_connection_secret_arn(
        self,
        run_id: uuid.UUID,
        connection_secret_arn: str,
    ) -> MigrationRun:
        secret = connection_secret_arn.strip()
        if not secret:
            raise ValidationError("connection_secret_arn must not be empty")

        async def _commit() -> MigrationRun:
            run = await self._repository.get_by_id_or_raise(run_id)
            run.connection_secret_arn = secret
            updated = await self._repository.update(run)
            await self._session.commit()
            await self._session.refresh(updated)
            return updated

        return await with_txn_retry(_commit, on_retry=self._session.rollback)

    async def get_migration_run(
        self,
        run_id: uuid.UUID,
        *,
        load_children: bool = False,
    ) -> MigrationRun:
        # A plain read can still land inside another transaction's
        # uncertainty window under CockroachDB serializable isolation
        # (ReadWithinUncertaintyIntervalError) when it races a concurrent
        # write to the same run — e.g. a dashboard poll landing right as
        # grading/persist commits. Retry like every write path already does
        # rather than surfacing a 500 for a transient, retryable conflict.
        async def _read() -> MigrationRun:
            return await self._repository.get_by_id_or_raise(
                run_id,
                load_children=load_children,
            )

        return await with_txn_retry(_read, on_retry=self._session.rollback)

    async def list_migration_runs(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: MigrationRunStatus | None = None,
        owner_identity: str | None = None,
        run_kind: str | None = None,
        exclude_kinds: list[str] | None = None,
    ) -> list[MigrationRun]:
        if offset < 0:
            raise ValidationError("offset must be >= 0")
        if limit < 1 or limit > 100:
            raise ValidationError("limit must be between 1 and 100")

        return await self._repository.list(
            offset=offset,
            limit=limit,
            status=status,
            owner_identity=owner_identity,
            run_kind=run_kind,
            exclude_kinds=exclude_kinds,
        )

    async def count_migration_runs(
        self,
        *,
        status: MigrationRunStatus | None = None,
        owner_identity: str | None = None,
        run_kind: str | None = None,
        exclude_kinds: list[str] | None = None,
    ) -> int:
        return await self._repository.count(
            status=status,
            owner_identity=owner_identity,
            run_kind=run_kind,
            exclude_kinds=exclude_kinds,
        )

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
