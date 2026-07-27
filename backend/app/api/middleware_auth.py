"""Session auth middleware — Bearer token when AUTH_ENABLED=true."""

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
    """When AUTH_ENABLED, require Authorization: Bearer <token> on API routes.

    Sets ``request.state.owner_identity`` from the token for tenant isolation.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_settings()
        request.state.owner_identity = None
        request.state.auth_enabled = bool(settings.auth_enabled)

        if not settings.auth_enabled:
            return await call_next(request)

        path = request.url.path
        if path == "/" or any(
            path == p or path.startswith(p.rstrip("/") + "/")
            for p in _PUBLIC_PREFIXES
        ):
            # Still accept optional Bearer on public paths (e.g. /auth/me).
            header = (request.headers.get("Authorization") or "").strip()
            if header.lower().startswith("bearer "):
                token = header[7:].strip()
                secret = (settings.auth_secret or "").strip()
                if secret and token:
                    try:
                        payload = verify_token(token, secret=secret)
                        request.state.owner_identity = payload["owner_identity"]
                    except ValueError:
                        pass
            return await call_next(request)

        secret = (settings.auth_secret or "").strip()
        if not secret:
            return JSONResponse(
                status_code=503,
                content={"detail": "AUTH_ENABLED but AUTH_SECRET is not configured"},
            )

        header = (request.headers.get("Authorization") or "").strip()
        if not header.lower().startswith("bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authorization Bearer token required"},
            )
        token = header[7:].strip()
        try:
            payload = verify_token(token, secret=secret)
        except ValueError as exc:
            return JSONResponse(status_code=401, content={"detail": str(exc)})

        request.state.owner_identity = payload["owner_identity"]
        return await call_next(request)
