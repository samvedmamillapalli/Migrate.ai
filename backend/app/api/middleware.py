"""Demo API-key gate (production-readiness minimum before Clerk)."""

from __future__ import annotations

import secrets
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import get_settings


# Paths that remain public even when DEMO_API_KEY is set.
_PUBLIC_PREFIXES = (
    "/",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/slack/oauth/callback",
)


class DemoApiKeyMiddleware(BaseHTTPMiddleware):
    """Require ``X-API-Key`` when ``DEMO_API_KEY`` is configured.

    Unset key = open local development. Set key = gated demo deploy.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_settings()
        expected = (settings.demo_api_key or "").strip()
        if not expected:
            return await call_next(request)

        path = request.url.path
        if path == "/" or any(
            path == p or path.startswith(p.rstrip("/") + "/")
            for p in _PUBLIC_PREFIXES
            if p != "/"
        ):
            return await call_next(request)
        if path.startswith("/ui"):
            return await call_next(request)

        provided = (request.headers.get("X-API-Key") or "").strip()
        if not provided or not secrets.compare_digest(provided, expected):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": (
                        "Missing or invalid X-API-Key. Set the DEMO_API_KEY "
                        "header to match the server configuration."
                    )
                },
            )
        return await call_next(request)
