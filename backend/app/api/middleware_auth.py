"""Session auth middleware — Bearer token when AUTH_ENABLED=true or Clerk is configured."""

from __future__ import annotations

from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.auth.tokens import verify_token
from app.config import get_settings

_PUBLIC_PREFIXES = (
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/auth/login",
    "/auth/register",
    "/auth/status",
)


class SessionAuthMiddleware(BaseHTTPMiddleware):
    """When AUTH_ENABLED or Clerk is configured, validate Bearer tokens.

    Supports two token types:
    1. Custom HMAC tokens (when ``AUTH_ENABLED=true``)
    2. Clerk-issued JWTs (when ``CLERK_SECRET_KEY`` + ``CLERK_PUBLISHABLE_KEY`` set)

    Sets ``request.state.owner_identity`` from the validated token.
    Sets ``request.state.auth_method`` to indicate which auth method was used.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_settings()
        request.state.owner_identity = None
        request.state.auth_method = None

        # Determine if any auth is enabled
        custom_auth_enabled = bool(settings.auth_enabled)
        clerk_configured = bool(
            settings.clerk_secret_key and settings.clerk_publishable_key
        )
        auth_enabled = custom_auth_enabled or clerk_configured

        if not auth_enabled:
            return await call_next(request)

        path = request.url.path
        is_public = path == "/" or any(
            path == p or path.startswith(p.rstrip("/") + "/")
            for p in _PUBLIC_PREFIXES
        )

        header = (request.headers.get("Authorization") or "").strip()
        token = ""
        if header.lower().startswith("bearer "):
            token = header[7:].strip()

        if not token:
            if is_public:
                return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={"detail": "Authorization Bearer token required"},
            )

        # Try Clerk JWT verification first (if configured)
        if clerk_configured and token:
            try:
                from app.auth.clerk import verify_clerk_token

                user_info = await verify_clerk_token(token)
                if user_info and user_info.get("owner_identity"):
                    request.state.owner_identity = user_info["owner_identity"]
                    request.state.clerk_user = user_info
                    request.state.auth_method = "clerk"
                    return await call_next(request)
            except Exception:
                # Fall through to custom auth if Clerk verification fails
                pass

        # Try custom HMAC token verification (if configured)
        if custom_auth_enabled:
            secret = (settings.auth_secret or "").strip()
            if not secret:
                if is_public:
                    return await call_next(request)
                return JSONResponse(
                    status_code=503,
                    content={"detail": "AUTH_ENABLED but AUTH_SECRET is not configured"},
                )

            try:
                payload = verify_token(token, secret=secret)
                request.state.owner_identity = payload["owner_identity"]
                request.state.auth_method = "custom"
                return await call_next(request)
            except ValueError:
                # Token invalid — fall through to error if not public
                pass

        if is_public:
            return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or expired token"},
        )
