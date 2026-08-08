"""Workspace HTTP routes — docs/FUTURE_WORKSPACES_PLAN.md.

A workspace scopes migration runs to one target database: a name, an owning
``owner_identity``, and a stored connection reference. Owner-scoped
everywhere, same tenancy pattern as ``app/api/routes/runs.py``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request, status

from app.auth.tenancy import auth_enforced, resolve_owner_identity, session_owner
from app.dependencies import WorkspaceInviteSvc, WorkspaceSvc
from app.schemas.workspace import (
    WorkspaceCreateRequest,
    WorkspaceListResponse,
    WorkspaceResponse,
    WorkspaceUpdateRequest,
)
from app.schemas.workspace_invite import (
    WorkspaceInviteCreateRequest,
    WorkspaceInviteListResponse,
    WorkspaceInviteResponse,
    WorkspaceMemberListResponse,
    WorkspaceMemberResponse,
)
from app.services.connection_secrets import (
    load_connection,
    store_connection_url,
    verify_connection_ping,
)
from app.services.github_setup import assert_repo_installed
from app.services.workspace_invite_service import _effective_status

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _workspace_secret_name(workspace_id: uuid.UUID) -> str:
    # Same store, distinguishable prefix from run-scoped secrets
    # (migration-oracle/connections/{run_id}) purely for AWS-console
    # readability — UUIDs from different ID spaces don't collide either way.
    return f"migration-oracle/connections/workspace/{workspace_id}"


async def _resolve_connection(
    request: Request,
    workspace_id: uuid.UUID,
    *,
    connection_secret_arn: str | None,
    database_url: str | None,
) -> tuple[str | None, str | None]:
    """Returns (secret_arn, connection_label). Both None when neither field
    was provided — a workspace may be created with no connection yet."""
    if database_url:
        secret_arn = await store_connection_url(
            request, _workspace_secret_name(workspace_id), database_url
        )
    elif connection_secret_arn:
        secret_arn = connection_secret_arn
    else:
        return None, None

    connection = await load_connection(request, secret_arn)
    await verify_connection_ping(connection)
    label = f"{connection.host}/{connection.database}"
    return secret_arn, label


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreateRequest,
    service: WorkspaceSvc,
    request: Request,
) -> WorkspaceResponse:
    owner = resolve_owner_identity(request, payload.owner_identity)
    if payload.github_repo_full_name:
        # Checked before anything is stored: a repo the App can't see would
        # save cleanly and then never fire a webhook, with nothing anywhere
        # telling the user why.
        await assert_repo_installed(payload.github_repo_full_name)
    workspace_id = uuid.uuid4()
    secret_arn, label = await _resolve_connection(
        request,
        workspace_id,
        connection_secret_arn=payload.connection_secret_arn,
        database_url=payload.database_url,
    )
    workspace = await service.create_workspace(
        owner_identity=owner,
        name=payload.name,
        connection_secret_arn=secret_arn,
        connection_label=label,
        workspace_id=workspace_id,
        github_repo_full_name=payload.github_repo_full_name,
        github_migration_glob=payload.github_migration_glob,
    )
    return WorkspaceResponse.from_workspace(workspace)


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(
    service: WorkspaceSvc,
    request: Request,
    owner_identity: str | None = Query(default=None, max_length=256),
) -> WorkspaceListResponse:
    """Owned + member workspaces (docs/backendfix.md 2026-08-07 — invites).
    Membership grants visibility here and on the single-workspace GET below;
    it does not grant access to that workspace's runs."""
    owner = session_owner(request) if auth_enforced() else (owner_identity or "").strip()
    if not owner:
        return WorkspaceListResponse(items=[], total=0)
    workspaces = await service.list_accessible_workspaces(owner)
    items = [WorkspaceResponse.from_workspace(w) for w in workspaces]
    return WorkspaceListResponse(items=items, total=len(items))


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: uuid.UUID,
    service: WorkspaceSvc,
    request: Request,
    owner_identity: str | None = Query(default=None, max_length=256),
) -> WorkspaceResponse:
    owner = resolve_owner_identity(request, owner_identity)
    workspace = await service.get_accessible_workspace(workspace_id, owner)
    return WorkspaceResponse.from_workspace(workspace)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: uuid.UUID,
    payload: WorkspaceUpdateRequest,
    service: WorkspaceSvc,
    request: Request,
) -> WorkspaceResponse:
    owner = resolve_owner_identity(request, None)
    if payload.github_repo_full_name and not payload.clear_github_repo:
        await assert_repo_installed(payload.github_repo_full_name)
    secret_arn: str | None = None
    label: str | None = None
    if not payload.clear_connection and (
        payload.connection_secret_arn or payload.database_url
    ):
        secret_arn, label = await _resolve_connection(
            request,
            workspace_id,
            connection_secret_arn=payload.connection_secret_arn,
            database_url=payload.database_url,
        )
    workspace = await service.update_workspace(
        workspace_id,
        owner,
        name=payload.name,
        connection_secret_arn=secret_arn,
        connection_label=label,
        clear_connection=payload.clear_connection,
        github_repo_full_name=payload.github_repo_full_name,
        clear_github_repo=payload.clear_github_repo,
        github_migration_glob=payload.github_migration_glob,
    )
    return WorkspaceResponse.from_workspace(workspace)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_id: uuid.UUID,
    service: WorkspaceSvc,
    request: Request,
) -> None:
    owner = resolve_owner_identity(request, None)
    await service.delete_workspace(workspace_id, owner)


# --- Members ------------------------------------------------------------
# Roster only — see app/database/models/workspace_member.py. Any accessible
# (owner or member) identity can view; only the owner can remove.


@router.get("/{workspace_id}/members", response_model=WorkspaceMemberListResponse)
async def list_workspace_members(
    workspace_id: uuid.UUID,
    service: WorkspaceSvc,
    request: Request,
) -> WorkspaceMemberListResponse:
    owner = resolve_owner_identity(request, None)
    members = await service.list_members(workspace_id, owner)
    items = [WorkspaceMemberResponse.from_member(m) for m in members]
    return WorkspaceMemberListResponse(items=items, total=len(items))


@router.delete(
    "/{workspace_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_workspace_member(
    workspace_id: uuid.UUID,
    member_id: uuid.UUID,
    service: WorkspaceSvc,
    request: Request,
) -> None:
    owner = resolve_owner_identity(request, None)
    await service.remove_member(workspace_id, member_id, owner)


# --- Invites --------------------------------------------------------------
# Owner-only to create/list/revoke, matching workspace-settings access.


@router.post(
    "/{workspace_id}/invites",
    response_model=WorkspaceInviteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_invite(
    workspace_id: uuid.UUID,
    payload: WorkspaceInviteCreateRequest,
    service: WorkspaceInviteSvc,
    request: Request,
) -> WorkspaceInviteResponse:
    from app.database.models import WorkspaceInviteMethod

    owner = resolve_owner_identity(request, None)
    invite = await service.create_invite(
        workspace_id,
        owner,
        method=WorkspaceInviteMethod(payload.method),
        email=payload.email,
        github_username=payload.github_username,
    )
    return WorkspaceInviteResponse.from_invite(
        invite, effective_status=_effective_status(invite)
    )


@router.get("/{workspace_id}/invites", response_model=WorkspaceInviteListResponse)
async def list_workspace_invites(
    workspace_id: uuid.UUID,
    service: WorkspaceInviteSvc,
    request: Request,
) -> WorkspaceInviteListResponse:
    owner = resolve_owner_identity(request, None)
    invites = await service.list_invites(workspace_id, owner)
    items = [
        WorkspaceInviteResponse.from_invite(i, effective_status=_effective_status(i))
        for i in invites
    ]
    return WorkspaceInviteListResponse(items=items, total=len(items))


@router.delete(
    "/{workspace_id}/invites/{invite_id}", response_model=WorkspaceInviteResponse
)
async def revoke_workspace_invite(
    workspace_id: uuid.UUID,
    invite_id: uuid.UUID,
    service: WorkspaceInviteSvc,
    request: Request,
) -> WorkspaceInviteResponse:
    owner = resolve_owner_identity(request, None)
    invite = await service.revoke_invite(workspace_id, invite_id, owner)
    return WorkspaceInviteResponse.from_invite(
        invite, effective_status=_effective_status(invite)
    )
