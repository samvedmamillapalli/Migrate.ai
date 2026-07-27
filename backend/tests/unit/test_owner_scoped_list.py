from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

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
async def test_list_migration_runs_passes_owner_identity(
    service: MigrationRunService,
    repository: AsyncMock,
) -> None:
    repository.list.return_value = []
    await service.list_migration_runs(
        offset=0,
        limit=10,
        owner_identity="alice@example.com",
    )
    repository.list.assert_awaited_once()
    kwargs = repository.list.await_args.kwargs
    assert kwargs["owner_identity"] == "alice@example.com"
    assert kwargs["limit"] == 10


@pytest.mark.asyncio
async def test_count_migration_runs_passes_owner_identity(
    service: MigrationRunService,
    repository: AsyncMock,
) -> None:
    repository.count.return_value = 0
    await service.count_migration_runs(owner_identity="bob")
    repository.count.assert_awaited_once_with(
        status=None,
        owner_identity="bob",
    )


@pytest.mark.asyncio
async def test_list_migration_runs_without_owner(
    service: MigrationRunService,
    repository: AsyncMock,
) -> None:
    repository.list.return_value = [
        MigrationRun(
            id=uuid.uuid4(),
            migration_sql="SELECT 1",
            status=MigrationRunStatus.PENDING,
        )
    ]
    rows = await service.list_migration_runs(limit=5)
    assert len(rows) == 1
    assert repository.list.await_args.kwargs["owner_identity"] is None
