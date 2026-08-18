"""Resolve a Clerk user ID to a human display name via the Clerk Backend API.

There is no local users table (see app/api/routes/invites.py), so the only
source of truth for "what is this person called" is Clerk itself. Used to
turn a raw ``user_2AbC...`` ID shown to an invitee into an actual name.

Best-effort: any failure (no secret key configured, network error, user
deleted) returns ``None`` and the caller falls back to the raw identity —
this must never turn a cosmetic lookup into a broken invite flow.
"""

from __future__ import annotations

import httpx

from app.core.logging import get_logger
from app.core.ttl_cache import cached

logger = get_logger(__name__)

_CLERK_API = "https://api.clerk.com/v1"
_HTTP_TIMEOUT_SECONDS = 10.0
_CACHE_TTL_SECONDS = 600.0

# Clerk's edge/WAF 403s requests with no recognizable User-Agent (verified
# against clerk_test_token.py) — any explicit UA is accepted.
_USER_AGENT = "migration-oracle-backend/1.0"


def _display_name_from_payload(payload: dict) -> str | None:
    first = (payload.get("first_name") or "").strip()
    last = (payload.get("last_name") or "").strip()
    full = " ".join(part for part in (first, last) if part)
    if full:
        return full

    username = (payload.get("username") or "").strip()
    if username:
        return username

    for email in payload.get("email_addresses") or []:
        address = (email.get("email_address") or "").strip()
        if address:
            return address

    return None


async def _fetch_display_name(user_id: str, secret_key: str) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{_CLERK_API}/users/{user_id}",
                headers={
                    "Authorization": f"Bearer {secret_key}",
                    "User-Agent": _USER_AGENT,
                },
            )
        if response.status_code != 200:
            return None
        return _display_name_from_payload(response.json())
    except Exception as exc:
        logger.warning("Clerk profile lookup failed for %s: %s", user_id, exc)
        return None


async def get_display_name(user_id: str) -> str | None:
    """Best-effort display name for a Clerk user ID, cached for 10 minutes."""
    from app.config import get_settings

    settings = get_settings()
    secret_key = settings.clerk_secret_key
    if not secret_key or not user_id:
        return None

    return await cached(
        f"clerk_display_name:{user_id}",
        _CACHE_TTL_SECONDS,
        lambda: _fetch_display_name(user_id, secret_key),
    )
