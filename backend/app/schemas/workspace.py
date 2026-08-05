"""Pydantic schemas for workspaces — docs/FUTURE_WORKSPACES_PLAN.md."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    owner_identity: str | None = Field(
        default=None,
        max_length=256,
        description="Ignored when auth is enforced (token owner wins).",
    )
    # Same "provide either" convention as DiscoverSchemaRequest — both
    # optional, a workspace may be created with no stored connection yet.
    connection_secret_arn: str | None = None
    database_url: str | None = Field(
        default=None,
        description="One-shot connection URL; stored as a secret, never persisted on the row",
    )

    @field_validator("connection_secret_arn", "database_url", "owner_identity")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    connection_secret_arn: str | None = None
    database_url: str | None = None
    clear_connection: bool = False

    @field_validator("connection_secret_arn", "database_url")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_identity: str
    name: str
    # Exposed directly, matching MigrationRunResponse.connection_secret_arn —
    # it's a pointer/name, not the credential itself.
    connection_secret_arn: str | None = None
    connection_label: str | None = None
    has_connection: bool = False
    is_default: bool = False
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_workspace(cls, workspace) -> WorkspaceResponse:
        return cls(
            id=workspace.id,
            owner_identity=workspace.owner_identity,
            name=workspace.name,
            connection_secret_arn=workspace.connection_secret_arn,
            connection_label=workspace.connection_label,
            has_connection=bool(workspace.connection_secret_arn),
            is_default=workspace.is_default,
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
        )


class WorkspaceListResponse(BaseModel):
    items: list[WorkspaceResponse]
    total: int
