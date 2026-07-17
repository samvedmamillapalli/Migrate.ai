from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ConflictError, ValidationError
from app.database.models import MigrationRun, MigrationRunStatus
from app.services.migration_run_service import MigrationRunService


@pytest.fixture
def repository() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def session() -> AsyncMock:
    mock = AsyncMock()
    mock.commit = AsyncMock()
    mock.refresh = AsyncMock()
    return mock


@pytest.fixture
def service(repository: AsyncMock, session: AsyncMock) -> MigrationRunService:
    return MigrationRunService(repository=repository, session=session)


@pytest.mark.asyncio
async def test_create_migration_run_rejects_empty_sql(
    service: MigrationRunService,
) -> None:
    with pytest.raises(ValidationError):
        await service.create_migration_run("   ")


@pytest.mark.asyncio
async def test_create_migration_run_persists_pending(
    service: MigrationRunService,
    repository: AsyncMock,
    session: AsyncMock,
) -> None:
    created = MigrationRun(
        id=uuid.uuid4(),
        migration_sql="ALTER TABLE t ADD COLUMN c INT",
        status=MigrationRunStatus.PENDING,
    )
    repository.create.return_value = created

    result = await service.create_migration_run(
        "  ALTER TABLE t ADD COLUMN c INT  "
    )

    assert result.status == MigrationRunStatus.PENDING
    repository.create.assert_awaited_once()
    created_arg = repository.create.await_args.args[0]
    assert created_arg.migration_sql == "ALTER TABLE t ADD COLUMN c INT"
    assert created_arg.schema_discovery_status.value == "pending"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_status_allows_valid_transition(
    service: MigrationRunService,
    repository: AsyncMock,
    session: AsyncMock,
) -> None:
    run = MigrationRun(
        id=uuid.uuid4(),
        migration_sql="SELECT 1",
        status=MigrationRunStatus.PENDING,
    )
    repository.get_by_id_or_raise.return_value = run
    repository.update.return_value = run

    updated = await service.update_status(run.id, MigrationRunStatus.PREDICTING)

    assert updated.status == MigrationRunStatus.PREDICTING
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_status_rejects_invalid_transition(
    service: MigrationRunService,
    repository: AsyncMock,
) -> None:
    run = MigrationRun(
        id=uuid.uuid4(),
        migration_sql="SELECT 1",
        status=MigrationRunStatus.PENDING,
    )
    repository.get_by_id_or_raise.return_value = run

    with pytest.raises(ConflictError):
        await service.update_status(run.id, MigrationRunStatus.COMPLETED)


@pytest.mark.asyncio
async def test_list_migration_runs_validates_limit(
    service: MigrationRunService,
) -> None:
    with pytest.raises(ValidationError):
        await service.list_migration_runs(limit=0)
