"""Pydantic schemas for workspaces — docs/FUTURE_WORKSPACES_PLAN.md."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


_GITHUB_REPO_PATTERN = r"^[\w.-]+/[\w.-]+$"


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
    # docs/FUTURE_GITHUB_INTEGRATION_PLAN.md — links a repo to this workspace
    # so a PR webhook can resolve to it. One repo maps to at most one
    # workspace (enforced at the service layer via a partial unique index).
    github_repo_full_name: str | None = Field(
        default=None,
        max_length=256,
        description='"owner/repo", e.g. "my-org/my-service"',
    )
    github_migration_glob: str | None = Field(
        default=None,
        max_length=512,
        description=(
            "Glob matched against changed file paths to detect a migration "
            "in a PR. Defaults to backend/alembic/versions/*.py."
        ),
    )

    @field_validator("connection_secret_arn", "database_url", "owner_identity")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("github_repo_full_name")
    @classmethod
    def validate_github_repo_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not re.match(_GITHUB_REPO_PATTERN, normalized):
            raise ValueError('github_repo_full_name must look like "owner/repo"')
        return normalized

    @field_validator("github_migration_glob")
    @classmethod
    def strip_glob(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    connection_secret_arn: str | None = None
    database_url: str | None = None
    clear_connection: bool = False
    github_repo_full_name: str | None = None
    clear_github_repo: bool = False
    github_migration_glob: str | None = None

    @field_validator("connection_secret_arn", "database_url", "github_migration_glob")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("github_repo_full_name")
    @classmethod
    def validate_github_repo_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not re.match(_GITHUB_REPO_PATTERN, normalized):
            raise ValueError('github_repo_full_name must look like "owner/repo"')
        return normalized


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
    github_repo_full_name: str | None = None
    github_migration_glob: str = "backend/alembic/versions/*.py"
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
            github_repo_full_name=workspace.github_repo_full_name,
            github_migration_glob=workspace.github_migration_glob,
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
        )


class WorkspaceListResponse(BaseModel):
    items: list[WorkspaceResponse]
    total: int
