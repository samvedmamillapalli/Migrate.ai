"""Pydantic schemas for the GitHub OAuth identity integration — matches the
hand-written TypeScript types in
frontend/oracle/apps/web/lib/api/endpoints.ts (GithubStatusResponse /
GithubInstallAuthorizeResponse / GithubDisconnectResponse) field for field.
"""

from __future__ import annotations

from pydantic import BaseModel


class GithubIdentityInstallAuthorizeResponse(BaseModel):
    """Redirect target for GitHub's OAuth authorization page."""

    authorize_url: str


class GithubIdentityStatusResponse(BaseModel):
    """Liveness/diagnostic endpoint for the GitHub identity integration."""

    connected: bool
    configured: bool
    username: str | None = None
    avatar_url: str | None = None


class GithubIdentityDisconnectResponse(BaseModel):
    connected: bool = False
