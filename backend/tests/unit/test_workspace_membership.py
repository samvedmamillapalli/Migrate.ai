"""WorkspaceService's membership additions — docs/backendfix.md 2026-08-07.

Covers exactly the roster-only scope decided for this feature: a member
can see the workspace (list/get) and the roster, but only the owner can
manage members/invites, the owner's own member row can never be removed
through this path, and adding a member is idempotent (accepting an invite
twice must not create a duplicate row or raise).

Deliberately does NOT test run-level access, because none was added —
MigrationRun tenancy is untouched by this feature by design.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import NotFoundError, UnauthorizedError
from app.database.models import Workspace, WorkspaceMember, WorkspaceMemberRole
from app.services.workspace_service import WorkspaceService


@pytest.fixture
def repository() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def member_repository() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def session() -> AsyncMock:
    mock = AsyncMock()
    mock.commit = AsyncMock()
    mock.refresh = AsyncMock()
    return mock


@pytest.fixture
def service(
    repository: AsyncMock, member_repository: AsyncMock, session: AsyncMock
) -> WorkspaceService:
    return WorkspaceService(
        repository=repository, session=session, member_repository=member_repository
    )


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


def _member(**overrides) -> WorkspaceMember:
    defaults = dict(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        user_identity="member-1",
        role=WorkspaceMemberRole.MEMBER,
    )
    defaults.update(overrides)
    return WorkspaceMember(**defaults)


# ------------------------------------------------------- visibility


@pytest.mark.asyncio
async def test_list_accessible_workspaces_delegates_to_repository(
    service: WorkspaceService, repository: AsyncMock
) -> None:
    workspaces = [_workspace(name="A"), _workspace(name="B")]
    repository.list_accessible.return_value = workspaces

    result = await service.list_accessible_workspaces("someone")

    assert result == workspaces
    repository.list_accessible.assert_awaited_once_with("someone")


@pytest.mark.asyncio
async def test_get_accessible_workspace_raises_not_found_when_no_access(
    service: WorkspaceService, repository: AsyncMock
) -> None:
    repository.get_accessible.return_value = None
    with pytest.raises(NotFoundError):
        await service.get_accessible_workspace(uuid.uuid4(), "outsider")


@pytest.mark.asyncio
async def test_get_accessible_workspace_returns_for_member(
    service: WorkspaceService, repository: AsyncMock
) -> None:
    workspace = _workspace()
    repository.get_accessible.return_value = workspace
    result = await service.get_accessible_workspace(workspace.id, "member-1")
    assert result is workspace


# ------------------------------------------------------------ list_members


@pytest.mark.asyncio
async def test_list_members_requires_accessible_workspace(
    service: WorkspaceService, repository: AsyncMock
) -> None:
    repository.get_accessible.return_value = None
    with pytest.raises(NotFoundError):
        await service.list_members(uuid.uuid4(), "outsider")


@pytest.mark.asyncio
async def test_list_members_returns_roster_for_accessible_member(
    service: WorkspaceService, repository: AsyncMock, member_repository: AsyncMock
) -> None:
    workspace = _workspace()
    repository.get_accessible.return_value = workspace
    members = [
        _member(workspace_id=workspace.id, role=WorkspaceMemberRole.OWNER),
        _member(workspace_id=workspace.id),
    ]
    member_repository.list_for_workspace.return_value = members

    result = await service.list_members(workspace.id, "member-1")
    assert result == members


# ------------------------------------------------------------- add_member


@pytest.mark.asyncio
async def test_add_member_creates_new_row(
    service: WorkspaceService, member_repository: AsyncMock, session: AsyncMock
) -> None:
    workspace_id = uuid.uuid4()
    member_repository.get_by_workspace_and_user.return_value = None
    created = _member(workspace_id=workspace_id, user_identity="new-person")
    member_repository.create.return_value = created

    result = await service.add_member(workspace_id, "new-person")

    assert result is created
    member_repository.create.assert_awaited_once()
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_add_member_is_idempotent_no_duplicate_on_existing(
    service: WorkspaceService, member_repository: AsyncMock
) -> None:
    """Accepting an invite twice (double-click, or a token reused after
    already joining) must not create a duplicate row or raise."""
    workspace_id = uuid.uuid4()
    existing = _member(workspace_id=workspace_id, user_identity="already-in")
    member_repository.get_by_workspace_and_user.return_value = existing

    result = await service.add_member(workspace_id, "already-in")

    assert result is existing
    member_repository.create.assert_not_awaited()


# ---------------------------------------------------------- remove_member


@pytest.mark.asyncio
async def test_remove_member_requires_owner(
    service: WorkspaceService, repository: AsyncMock
) -> None:
    repository.get_owned.return_value = None
    with pytest.raises(NotFoundError):
        await service.remove_member(uuid.uuid4(), uuid.uuid4(), "not-the-owner")


@pytest.mark.asyncio
async def test_remove_member_rejects_removing_the_owner_row(
    service: WorkspaceService, repository: AsyncMock, member_repository: AsyncMock
) -> None:
    """The workspace's 'owner' member row can never be removed through this
    path — that would leave a workspace with no owner."""
    workspace = _workspace()
    repository.get_owned.return_value = workspace
    owner_member = _member(
        workspace_id=workspace.id,
        user_identity=workspace.owner_identity,
        role=WorkspaceMemberRole.OWNER,
    )
    member_repository.get_owned_by_id.return_value = owner_member

    with pytest.raises(UnauthorizedError):
        await service.remove_member(workspace.id, owner_member.id, workspace.owner_identity)
    member_repository.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_remove_member_deletes_a_regular_member(
    service: WorkspaceService,
    repository: AsyncMock,
    member_repository: AsyncMock,
    session: AsyncMock,
) -> None:
    workspace = _workspace()
    repository.get_owned.return_value = workspace
    member = _member(workspace_id=workspace.id)
    member_repository.get_owned_by_id.return_value = member

    await service.remove_member(workspace.id, member.id, workspace.owner_identity)

    member_repository.delete.assert_awaited_once_with(member)
    session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_remove_member_not_found(
    service: WorkspaceService, repository: AsyncMock, member_repository: AsyncMock
) -> None:
    workspace = _workspace()
    repository.get_owned.return_value = workspace
    member_repository.get_owned_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.remove_member(workspace.id, uuid.uuid4(), workspace.owner_identity)


# ------------------------------------------------------ create_workspace


@pytest.mark.asyncio
async def test_create_workspace_also_creates_owner_member_row(
    service: WorkspaceService,
    repository: AsyncMock,
    member_repository: AsyncMock,
) -> None:
    repository.get_by_owner_and_name.return_value = None
    created_workspace = _workspace(owner_identity="owner-1", name="Prod")
    repository.create.return_value = created_workspace

    await service.create_workspace(owner_identity="owner-1", name="Prod")

    member_repository.create.assert_awaited_once()
    created_member_arg = member_repository.create.await_args.args[0]
    assert created_member_arg.user_identity == "owner-1"
    assert created_member_arg.role == WorkspaceMemberRole.OWNER
