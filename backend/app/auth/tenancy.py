"""Tenant isolation helpers for Wave 2 auth."""

from __future__ import annotations

from fastapi import Request

from app.config import get_settings
from app.core.exceptions import UnauthorizedError, ValidationError
from app.database.models import MigrationRun


def session_owner(request: Request) -> str | None:
    return getattr(request.state, "owner_identity", None)


def require_session_owner(request: Request) -> str:
    settings = get_settings()
    owner = session_owner(request)
    if settings.auth_enabled:
        if not owner:
            raise UnauthorizedError("Authentication required")
        return owner
    return owner or ""


def resolve_owner_identity(request: Request, client_owner: str | None) -> str:
    """When auth is on, the token owner wins; otherwise use the client value."""
    settings = get_settings()
    if settings.auth_enabled:
        return require_session_owner(request)
    identity = (client_owner or "").strip()
    if not identity:
        raise ValidationError("owner_identity is required")
    return identity


def assert_run_access(request: Request, run: MigrationRun) -> None:
    settings = get_settings()
    if not settings.auth_enabled:
        return
    owner = require_session_owner(request)
    if (run.owner_identity or "") != owner:
        raise UnauthorizedError("Not allowed to access this migration run")
