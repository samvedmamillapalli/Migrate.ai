"""WorkspaceService — docs/FUTURE_WORKSPACES_PLAN.md.

Covers: name/owner validation, per-owner name uniqueness, ownership-scoped
get/update/delete (a workspace_id that exists but belongs to someone else
must behave identically to one that doesn't exist at all), and that delete
does nothing beyond removing the row — no application-level cascade, since
the FK's ON DELETE SET NULL at the database layer already handles orphaning
referencing runs (see the workspaces migration).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.database.models import Workspace
from app.services.workspace_service import WorkspaceService


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
def service(repository: AsyncMock, session: AsyncMock) -> WorkspaceService:
    return WorkspaceService(repository=repository, session=session)


def _workspace(**overrides) -> Workspace:
    defaults = dict(
        id=uuid.uuid4(),
        owner_identity="owner-1",
        name="Default",
        connection_secret_arn=None,
        connection_label=None,
        is_default=False,
    )
    defaults.update(overrides)
    return Workspace(**defaults)


# --------------------------------------------------------------- create


@pytest.mark.asyncio
async def test_create_workspace_rejects_empty_name(service: WorkspaceService) -> None:
    with pytest.raises(ValidationError):
        await service.create_workspace(owner_identity="owner-1", name="   ")


@pytest.mark.asyncio
async def test_create_workspace_rejects_empty_owner(service: WorkspaceService) -> None:
    with pytest.raises(ValidationError):
        await service.create_workspace(owner_identity="  ", name="Prod")


@pytest.mark.asyncio
async def test_create_workspace_rejects_duplicate_name_for_same_owner(
    service: WorkspaceService, repository: AsyncMock
) -> None:
    repository.get_by_owner_and_name.return_value = _workspace(name="Prod")
    with pytest.raises(ConflictError):
        await service.create_workspace(owner_identity="owner-1", name="Prod")
    repository.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_workspace_persists_and_strips_fields(
    service: WorkspaceService, repository: AsyncMock
) -> None:
    repository.get_by_owner_and_name.return_value = None
    created = _workspace(name="Prod", connection_secret_arn="arn:secret")
    repository.create.return_value = created

    result = await service.create_workspace(
        owner_identity="  owner-1  ",
        name="  Prod  ",
        connection_secret_arn="arn:secret",
        connection_label="db.example.com/prod",
    )

    assert result.name == "Prod"
    repository.create.assert_awaited_once()
    created_arg = repository.create.await_args.args[0]
    assert created_arg.owner_identity == "owner-1"
    assert created_arg.name == "Prod"
    assert created_arg.connection_secret_arn == "arn:secret"
    assert created_arg.is_default is False


# ------------------------------------------------------------- ownership


@pytest.mark.asyncio
async def test_get_owned_workspace_raises_not_found_when_missing_or_not_owned(
    service: WorkspaceService, repository: AsyncMock
) -> None:
    """Same behavior for "doesn't exist" and "belongs to someone else" —
    the repository's get_owned already filters by owner_identity, so
    WorkspaceService never distinguishes the two, matching get_owned_run's
    tenancy posture elsewhere in this app."""
    repository.get_owned.return_value = None
    with pytest.raises(NotFoundError):
        await service.get_owned_workspace(uuid.uuid4(), "owner-1")


@pytest.mark.asyncio
async def test_get_owned_workspace_returns_when_owned(
    service: WorkspaceService, repository: AsyncMock
) -> None:
    workspace = _workspace()
    repository.get_owned.return_value = workspace
    result = await service.get_owned_workspace(workspace.id, "owner-1")
    assert result is workspace


@pytest.mark.asyncio
async def test_list_workspaces_requires_owner(service: WorkspaceService) -> None:
    with pytest.raises(ValidationError):
        await service.list_workspaces("")


# -------------------------------------------------------------- update


@pytest.mark.asyncio
async def test_update_workspace_rename_checks_uniqueness_against_other_rows(
    service: WorkspaceService, repository: AsyncMock
) -> None:
    workspace = _workspace(name="Old")
    other = _workspace(id=uuid.uuid4(), name="New")
    repository.get_owned.return_value = workspace
    repository.get_by_owner_and_name.return_value = other

    with pytest.raises(ConflictError):
        await service.update_workspace(workspace.id, "owner-1", name="New")


@pytest.mark.asyncio
async def test_update_workspace_rename_to_self_is_a_noop_not_a_conflict(
    service: WorkspaceService, repository: AsyncMock
) -> None:
    """Renaming a workspace to the name it already has must not trip the
    uniqueness check against itself."""
    workspace = _workspace(name="Prod")
    repository.get_owned.return_value = workspace
    repository.update.return_value = workspace

    result = await service.update_workspace(workspace.id, "owner-1", name="Prod")
    assert result.name == "Prod"
    repository.get_by_owner_and_name.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_workspace_clear_connection_removes_arn_and_label(
    service: WorkspaceService, repository: AsyncMock
) -> None:
    workspace = _workspace(
        connection_secret_arn="arn:old", connection_label="old-host/db"
    )
    repository.get_owned.return_value = workspace
    repository.update.return_value = workspace

    result = await service.update_workspace(
        workspace.id, "owner-1", clear_connection=True
    )
    assert result.connection_secret_arn is None
    assert result.connection_label is None


@pytest.mark.asyncio
async def test_update_workspace_with_no_connection_args_leaves_existing_connection(
    service: WorkspaceService, repository: AsyncMock
) -> None:
    """connection_secret_arn=None on the call means "don't touch it" —
    distinct from clear_connection=True, which explicitly detaches it."""
    workspace = _workspace(connection_secret_arn="arn:keep-me")
    repository.get_owned.return_value = workspace
    repository.get_by_owner_and_name.return_value = None
    repository.update.return_value = workspace

    result = await service.update_workspace(workspace.id, "owner-1", name="Renamed")
    assert result.connection_secret_arn == "arn:keep-me"


# -------------------------------------------------------------- delete


@pytest.mark.asyncio
async def test_delete_workspace_requires_ownership(
    service: WorkspaceService, repository: AsyncMock
) -> None:
    repository.get_owned.return_value = None
    with pytest.raises(NotFoundError):
        await service.delete_workspace(uuid.uuid4(), "owner-1")
    repository.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_workspace_deletes_row_only_no_cascade_logic(
    service: WorkspaceService, repository: AsyncMock, session: AsyncMock
) -> None:
    """No application-level touching of migration_runs here — the FK's
    ON DELETE SET NULL (see the workspaces migration) does the orphaning
    at the database layer, not this service."""
    workspace = _workspace()
    repository.get_owned.return_value = workspace

    await service.delete_workspace(workspace.id, "owner-1")

    repository.delete.assert_awaited_once_with(workspace)
    session.commit.assert_awaited()
