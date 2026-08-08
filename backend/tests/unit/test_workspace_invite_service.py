"""WorkspaceInviteService — docs/backendfix.md 2026-08-07.

Covers: owner-only create/list/revoke, required fields per method, public
token preview (including lazily-computed "expired" — never a stored
status), and accept (idempotent membership creation, rejects
non-pending invites with the right effective status in the error).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.database.models import (
    Workspace,
    WorkspaceInvite,
    WorkspaceInviteMethod,
    WorkspaceInviteStatus,
    WorkspaceMemberRole,
)
from app.services.workspace_invite_service import WorkspaceInviteService, _effective_status


def _workspace(**overrides) -> Workspace:
    defaults = dict(
        id=uuid.uuid4(),
        owner_identity="owner-1",
        name="Prod",
        connection_secret_arn=None,
        connection_label=None,
        is_default=False,
    )
    defaults.update(overrides)
    return Workspace(**defaults)


def _invite(**overrides) -> WorkspaceInvite:
    defaults = dict(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        inviter_identity="owner-1",
        method=WorkspaceInviteMethod.LINK,
        email=None,
        github_username=None,
        token="tok_abc123",
        status=WorkspaceInviteStatus.PENDING,
        expires_at=datetime.now(UTC) + timedelta(days=14),
        accepted_at=None,
        accepted_by=None,
    )
    defaults.update(overrides)
    return WorkspaceInvite(**defaults)


@pytest.fixture
def repository() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def workspace_service() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def session() -> AsyncMock:
    mock = AsyncMock()
    mock.commit = AsyncMock()
    mock.refresh = AsyncMock()
    return mock


@pytest.fixture
def service(
    repository: AsyncMock, workspace_service: AsyncMock, session: AsyncMock
) -> WorkspaceInviteService:
    return WorkspaceInviteService(
        repository=repository,
        workspace_service=workspace_service,
        session=session,
        email_service=None,
    )


# ------------------------------------------------------------ _effective_status


def test_effective_status_pending_and_not_expired() -> None:
    invite = _invite(expires_at=datetime.now(UTC) + timedelta(days=1))
    assert _effective_status(invite) == "pending"


def test_effective_status_computes_expired_lazily() -> None:
    """Never a stored value — derived from comparing expires_at to now."""
    invite = _invite(
        status=WorkspaceInviteStatus.PENDING,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert _effective_status(invite) == "expired"


def test_effective_status_accepted_stays_accepted_even_if_past_expiry() -> None:
    invite = _invite(
        status=WorkspaceInviteStatus.ACCEPTED,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert _effective_status(invite) == "accepted"


def test_effective_status_revoked_stays_revoked() -> None:
    invite = _invite(status=WorkspaceInviteStatus.REVOKED)
    assert _effective_status(invite) == "revoked"


# ------------------------------------------------------------- create_invite


@pytest.mark.asyncio
async def test_create_invite_requires_owner(
    service: WorkspaceInviteService, workspace_service: AsyncMock
) -> None:
    workspace_service.get_owned_workspace.side_effect = NotFoundError("nope")
    with pytest.raises(NotFoundError):
        await service.create_invite(
            uuid.uuid4(), "not-owner", method=WorkspaceInviteMethod.LINK
        )


@pytest.mark.asyncio
async def test_create_invite_link_needs_no_extra_fields(
    service: WorkspaceInviteService,
    workspace_service: AsyncMock,
    repository: AsyncMock,
) -> None:
    workspace = _workspace()
    workspace_service.get_owned_workspace.return_value = workspace
    created = _invite(workspace_id=workspace.id, method=WorkspaceInviteMethod.LINK)
    repository.create.return_value = created

    result = await service.create_invite(
        workspace.id, workspace.owner_identity, method=WorkspaceInviteMethod.LINK
    )
    assert result is created


@pytest.mark.asyncio
async def test_create_invite_email_requires_email_field(
    service: WorkspaceInviteService, workspace_service: AsyncMock
) -> None:
    workspace_service.get_owned_workspace.return_value = _workspace()
    with pytest.raises(ValidationError):
        await service.create_invite(
            uuid.uuid4(), "owner-1", method=WorkspaceInviteMethod.EMAIL
        )


@pytest.mark.asyncio
async def test_create_invite_github_requires_username_field(
    service: WorkspaceInviteService, workspace_service: AsyncMock
) -> None:
    workspace_service.get_owned_workspace.return_value = _workspace()
    with pytest.raises(ValidationError):
        await service.create_invite(
            uuid.uuid4(), "owner-1", method=WorkspaceInviteMethod.GITHUB
        )


@pytest.mark.asyncio
async def test_create_invite_generates_a_real_token_and_expiry(
    service: WorkspaceInviteService,
    workspace_service: AsyncMock,
    repository: AsyncMock,
) -> None:
    workspace = _workspace()
    workspace_service.get_owned_workspace.return_value = workspace
    repository.create.side_effect = lambda entity: entity  # echo back what was built

    result = await service.create_invite(
        workspace.id, workspace.owner_identity, method=WorkspaceInviteMethod.LINK
    )
    assert result.token and len(result.token) > 20
    assert result.expires_at > datetime.now(UTC) + timedelta(days=13)
    assert result.status == WorkspaceInviteStatus.PENDING


@pytest.mark.asyncio
async def test_create_invite_sends_email_best_effort_when_email_method(
    workspace_service: AsyncMock, repository: AsyncMock, session: AsyncMock
) -> None:
    email_service = AsyncMock()
    email_service.send_workspace_invite = AsyncMock(return_value=True)
    service = WorkspaceInviteService(
        repository=repository,
        workspace_service=workspace_service,
        session=session,
        email_service=email_service,
    )
    workspace = _workspace()
    workspace_service.get_owned_workspace.return_value = workspace
    created = _invite(
        workspace_id=workspace.id,
        method=WorkspaceInviteMethod.EMAIL,
        email="teammate@example.com",
    )
    repository.create.return_value = created

    await service.create_invite(
        workspace.id,
        workspace.owner_identity,
        method=WorkspaceInviteMethod.EMAIL,
        email="teammate@example.com",
    )
    email_service.send_workspace_invite.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_invite_link_method_never_calls_email(
    workspace_service: AsyncMock, repository: AsyncMock, session: AsyncMock
) -> None:
    email_service = AsyncMock()
    service = WorkspaceInviteService(
        repository=repository,
        workspace_service=workspace_service,
        session=session,
        email_service=email_service,
    )
    workspace = _workspace()
    workspace_service.get_owned_workspace.return_value = workspace
    repository.create.return_value = _invite(
        workspace_id=workspace.id, method=WorkspaceInviteMethod.LINK
    )

    await service.create_invite(
        workspace.id, workspace.owner_identity, method=WorkspaceInviteMethod.LINK
    )
    email_service.send_workspace_invite.assert_not_awaited()


# --------------------------------------------------------------- list/revoke


@pytest.mark.asyncio
async def test_list_invites_requires_owner(
    service: WorkspaceInviteService, workspace_service: AsyncMock
) -> None:
    workspace_service.get_owned_workspace.side_effect = NotFoundError("nope")
    with pytest.raises(NotFoundError):
        await service.list_invites(uuid.uuid4(), "not-owner")


@pytest.mark.asyncio
async def test_revoke_invite_sets_status_revoked(
    service: WorkspaceInviteService,
    workspace_service: AsyncMock,
    repository: AsyncMock,
) -> None:
    workspace = _workspace()
    workspace_service.get_owned_workspace.return_value = workspace
    invite = _invite(workspace_id=workspace.id)
    repository.get_owned_by_id.return_value = invite
    repository.update.return_value = invite

    result = await service.revoke_invite(workspace.id, invite.id, workspace.owner_identity)
    assert result.status == WorkspaceInviteStatus.REVOKED


@pytest.mark.asyncio
async def test_revoke_invite_not_found(
    service: WorkspaceInviteService,
    workspace_service: AsyncMock,
    repository: AsyncMock,
) -> None:
    workspace_service.get_owned_workspace.return_value = _workspace()
    repository.get_owned_by_id.return_value = None
    with pytest.raises(NotFoundError):
        await service.revoke_invite(uuid.uuid4(), uuid.uuid4(), "owner-1")


# ------------------------------------------------------------------- preview


@pytest.mark.asyncio
async def test_get_preview_unknown_token_raises_not_found(
    service: WorkspaceInviteService, repository: AsyncMock
) -> None:
    repository.get_by_token.return_value = None
    with pytest.raises(NotFoundError):
        await service.get_preview("nonexistent-token")


@pytest.mark.asyncio
async def test_get_preview_returns_workspace_and_effective_status(
    service: WorkspaceInviteService,
    repository: AsyncMock,
    workspace_service: AsyncMock,
) -> None:
    workspace = _workspace()
    invite = _invite(workspace_id=workspace.id)
    repository.get_by_token.return_value = invite
    workspace_service.get_workspace_by_id.return_value = workspace

    result_invite, result_workspace, status = await service.get_preview(invite.token)
    assert result_invite is invite
    assert result_workspace is workspace
    assert status == "pending"


@pytest.mark.asyncio
async def test_get_preview_does_not_raise_for_revoked_invite(
    service: WorkspaceInviteService,
    repository: AsyncMock,
    workspace_service: AsyncMock,
) -> None:
    """The preview must show *why* an invite is unusable, not error out —
    only accept() raises for a non-pending invite."""
    invite = _invite(status=WorkspaceInviteStatus.REVOKED)
    repository.get_by_token.return_value = invite
    workspace_service.get_workspace_by_id.return_value = _workspace()

    _, _, status = await service.get_preview(invite.token)
    assert status == "revoked"


# -------------------------------------------------------------------- accept


@pytest.mark.asyncio
async def test_accept_invite_unknown_token_raises_not_found(
    service: WorkspaceInviteService, repository: AsyncMock
) -> None:
    repository.get_by_token.return_value = None
    with pytest.raises(NotFoundError):
        await service.accept_invite("nonexistent-token", "someone")


@pytest.mark.asyncio
async def test_accept_invite_rejects_already_accepted(
    service: WorkspaceInviteService, repository: AsyncMock
) -> None:
    invite = _invite(status=WorkspaceInviteStatus.ACCEPTED)
    repository.get_by_token.return_value = invite
    with pytest.raises(ConflictError):
        await service.accept_invite(invite.token, "someone")


@pytest.mark.asyncio
async def test_accept_invite_rejects_revoked(
    service: WorkspaceInviteService, repository: AsyncMock
) -> None:
    invite = _invite(status=WorkspaceInviteStatus.REVOKED)
    repository.get_by_token.return_value = invite
    with pytest.raises(ConflictError):
        await service.accept_invite(invite.token, "someone")


@pytest.mark.asyncio
async def test_accept_invite_rejects_expired(
    service: WorkspaceInviteService, repository: AsyncMock
) -> None:
    invite = _invite(
        status=WorkspaceInviteStatus.PENDING,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    repository.get_by_token.return_value = invite
    with pytest.raises(ConflictError):
        await service.accept_invite(invite.token, "someone")


@pytest.mark.asyncio
async def test_accept_invite_success_adds_member_and_marks_accepted(
    service: WorkspaceInviteService,
    repository: AsyncMock,
    workspace_service: AsyncMock,
) -> None:
    workspace = _workspace()
    invite = _invite(workspace_id=workspace.id)
    repository.get_by_token.return_value = invite
    workspace_service.get_workspace_by_id.return_value = workspace

    result = await service.accept_invite(invite.token, "new-teammate")

    assert result is workspace
    workspace_service.add_member.assert_awaited_once_with(
        workspace.id, "new-teammate", role=WorkspaceMemberRole.MEMBER
    )
    assert invite.status == WorkspaceInviteStatus.ACCEPTED
    assert invite.accepted_by == "new-teammate"
    assert invite.accepted_at is not None
    repository.update.assert_awaited_once()
