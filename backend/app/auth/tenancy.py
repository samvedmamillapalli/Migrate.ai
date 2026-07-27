"""Tenant isolation helpers for Wave 2 auth (custom HMAC + Clerk JWT)."""

from __future__ import annotations

from fastapi import Request

from app.config import get_settings
from app.core.exceptions import UnauthorizedError, ValidationError
from app.database.models import MigrationRun


def auth_enforced() -> bool:
    """True when API requires a validated Bearer token (custom or Clerk)."""
    settings = get_settings()
    if settings.auth_enabled:
        return True
    return bool(settings.clerk_secret_key and settings.clerk_publishable_key)


def session_owner(request: Request) -> str | None:
    return getattr(request.state, "owner_identity", None)


def require_session_owner(request: Request) -> str:
    owner = session_owner(request)
    if auth_enforced():
        if not owner:
            raise UnauthorizedError("Authentication required")
        return owner
    return owner or ""


def resolve_owner_identity(request: Request, client_owner: str | None) -> str:
    """When auth is on, the token owner wins; otherwise use the client value."""
    if auth_enforced():
        return require_session_owner(request)
    identity = (client_owner or "").strip()
    if not identity:
        raise ValidationError("owner_identity is required")
    return identity


def assert_run_access(request: Request, run: MigrationRun) -> None:
    if not auth_enforced():
        return
    owner = require_session_owner(request)
    if (run.owner_identity or "") != owner:
        raise UnauthorizedError("Not allowed to access this migration run")
