"""Pydantic schemas for workspace invites/members — matches the hand-written
TypeScript types in frontend/oracle/apps/web/lib/api/endpoints.ts field for
field (this is the contract that was built to, not the other way around).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database.models import WorkspaceInvite, WorkspaceMember

InviteMethod = Literal["email", "github", "link"]
# "expired" is never stored — computed at read time from expires_at (see
# workspace_invite_service._effective_status) — but is a real value these
# response fields can carry, so it belongs in the wire type.
InviteStatus = Literal["pending", "accepted", "revoked", "expired"]
MemberRole = Literal["owner", "member"]


class WorkspaceInviteCreateRequest(BaseModel):
    method: InviteMethod
    email: str | None = None
    github_username: str | None = None

    @field_validator("email", "github_username")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WorkspaceInviteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    workspace_name: str | None = None
    inviter_identity: str
    method: InviteMethod
    email: str | None = None
    github_username: str | None = None
    token: str | None = None
    status: InviteStatus
    created_at: datetime | None = None
    expires_at: datetime | None = None
    accepted_at: datetime | None = None
    accepted_by: str | None = None
    # Only meaningful for method="email", and only on the create response —
    # None on every list/revoke response (delivery isn't re-attempted or
    # re-checked on read). False means the invite row exists but no email
    # went out (SES not configured, sandbox rejected the recipient, etc.);
    # the frontend must not say "sent" in that case.
    email_delivered: bool | None = None

    @classmethod
    def from_invite(
        cls,
        invite: WorkspaceInvite,
        *,
        effective_status: InviteStatus,
        workspace_name: str | None = None,
        email_delivered: bool | None = None,
    ) -> WorkspaceInviteResponse:
        return cls(
            id=invite.id,
            workspace_id=invite.workspace_id,
            workspace_name=workspace_name,
            inviter_identity=invite.inviter_identity,
            method=invite.method.value,  # type: ignore[arg-type]
            email=invite.email,
            github_username=invite.github_username,
            token=invite.token,
            status=effective_status,
            created_at=invite.created_at,
            expires_at=invite.expires_at,
            accepted_at=invite.accepted_at,
            accepted_by=invite.accepted_by,
            email_delivered=email_delivered,
        )


class WorkspaceInviteListResponse(BaseModel):
    items: list[WorkspaceInviteResponse]
    total: int


class WorkspaceMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    user_identity: str
    # There is no local users table — display_name comes from the Clerk
    # Backend API at read time (app/auth/clerk_profile.py) and is None on any
    # lookup failure, never fabricated. email/avatar_url stay null; nothing
    # currently resolves them. The frontend already falls back to
    # user_identity when display_name is absent.
    display_name: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    role: MemberRole
    joined_at: datetime | None = None

    @classmethod
    def from_member(
        cls, member: WorkspaceMember, *, display_name: str | None = None
    ) -> WorkspaceMemberResponse:
        return cls(
            id=member.id,
            workspace_id=member.workspace_id,
            user_identity=member.user_identity,
            display_name=display_name,
            role=member.role.value,  # type: ignore[arg-type]
            joined_at=member.created_at,
        )


class WorkspaceMemberListResponse(BaseModel):
    items: list[WorkspaceMemberResponse]
    total: int


class InvitePreviewResponse(BaseModel):
    workspace_name: str
    inviter_identity: str
    inviter_display_name: str | None = None
    method: InviteMethod
    status: InviteStatus
    expires_at: datetime | None = None


class InviteAcceptResponse(BaseModel):
    workspace_id: uuid.UUID
    workspace_name: str
