"""Public invite acceptance routes — docs/backendfix.md 2026-08-07.

``GET /invites/{token}`` is unauthenticated by design: the token in the URL
*is* the credential (same convention as any shareable-link invite), so a
signed-out visitor can see what they're being invited to before signing in.
Allowlisted in app/api/middleware_auth.py's public-path list.
``POST /invites/{token}/accept`` still requires a real session — the
middleware validates any Bearer token present regardless of the public
allowlist, and ``resolve_owner_identity`` enforces auth_enforced() the same
way every other authenticated route in this app does.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.auth.tenancy import resolve_owner_identity
from app.dependencies import WorkspaceInviteSvc
from app.schemas.workspace_invite import InviteAcceptResponse, InvitePreviewResponse

router = APIRouter(prefix="/invites", tags=["invites"])


@router.get("/{token}", response_model=InvitePreviewResponse)
async def get_invite_preview(
    token: str,
    service: WorkspaceInviteSvc,
) -> InvitePreviewResponse:
    invite, workspace, effective_status = await service.get_preview(token)
    return InvitePreviewResponse(
        workspace_name=workspace.name,
        inviter_identity=invite.inviter_identity,
        # No profile-data source (no users table) — the frontend already
        # falls back to inviter_identity when this is null.
        inviter_display_name=None,
        method=invite.method.value,
        status=effective_status,
        expires_at=invite.expires_at,
    )


@router.post(
    "/{token}/accept",
    response_model=InviteAcceptResponse,
    status_code=status.HTTP_200_OK,
)
async def accept_invite(
    token: str,
    service: WorkspaceInviteSvc,
    request: Request,
) -> InviteAcceptResponse:
    accepting_identity = resolve_owner_identity(request, None)
    workspace = await service.accept_invite(token, accepting_identity)
    return InviteAcceptResponse(workspace_id=workspace.id, workspace_name=workspace.name)
