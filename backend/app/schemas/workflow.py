"""Request schemas for discovery and workflow start."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class DiscoverSchemaRequest(BaseModel):
    """Discover schema for a run and optionally register the connection secret.

    Provide either ``connection_secret_arn`` (preferred — password stays in
    Secrets Manager / local secret store) or a one-shot ``database_url`` which
    is stored under a run-scoped secret name and never persisted on the row.
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

    @model_validator(mode="after")
    def require_one(self) -> DiscoverSchemaRequest:
        if not self.connection_secret_arn and not self.database_url:
            raise ValueError(
                "Provide connection_secret_arn or database_url for discovery"
            )
        return self


class StartWorkflowRequest(BaseModel):
    connection_secret_arn: str | None = Field(
        default=None,
        description="Override; defaults to the ARN stored on the run",
    )

    @field_validator("connection_secret_arn")
    @classmethod
    def strip_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None
