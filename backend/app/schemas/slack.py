"""Pydantic schemas for the Slack OAuth integration."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SlackInstallAuthorizeResponse(BaseModel):
    """Redirect target for Slack's OAuth v2 authorization page."""

    authorize_url: str
    state: str
    expires_in_seconds: int


class SlackInstallationResponse(BaseModel):
    """Public view of a Slack installation — never exposes the bot token."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_identity: str
    team_id: str
    team_name: str | None = None
    bot_user_id: str
    scope: str
    installed_at: datetime
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_installation(cls, row) -> SlackInstallationResponse:
        return cls(
            id=row.id,
            owner_identity=row.owner_identity,
            team_id=row.team_id,
            team_name=row.team_name,
            bot_user_id=row.bot_user_id,
            scope=row.scope,
            installed_at=row.installed_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class SlackStatusResponse(BaseModel):
    """Liveness/diagnostic endpoint for the Slack integration."""

    configured: bool
    connected: bool
    team_id: str | None = None
    team_name: str | None = None
    scope: str | None = None


class SlackDisconnectResponse(BaseModel):
    disconnected: bool
    owner_identity: str
