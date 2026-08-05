"""Request schemas for discovery and workflow start."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class DiscoverSchemaRequest(BaseModel):
    """Discover schema for a run and optionally register the connection secret.

    Provide either ``connection_secret_arn`` (preferred — password stays in
    Secrets Manager / local secret store) or a one-shot ``database_url`` which
    is stored under a run-scoped secret name and never persisted on the row.

    Both may be omitted when the run belongs to a workspace with a stored
    connection (docs/FUTURE_WORKSPACES_PLAN.md) — the route falls back to
    ``workspace.connection_secret_arn`` in that case. There is no hard
    "require one" validator here anymore for that reason; the route raises
    if, after considering the workspace fallback, nothing usable was found.
    """

    connection_secret_arn: str | None = None
    database_url: str | None = Field(
        default=None,
        description="One-shot connection URL; stored as a secret, never on the run row",
    )

    @field_validator("connection_secret_arn", "database_url")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class StartWorkflowRequest(BaseModel):
    connection_secret_arn: str | None = Field(
        default=None,
        description="Override; defaults to the ARN stored on the run",
    )
    database_url: str | None = Field(
        default=None,
        description=(
            "One-shot read-only URL when the run has no connection_secret_arn yet "
            "(same store path as POST /discover)"
        ),
    )

    @field_validator("connection_secret_arn", "database_url")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
