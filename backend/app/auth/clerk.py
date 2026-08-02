"""Clerk JWT verification module.

Validates Clerk-issued JWTs using Clerk's JWKS endpoint (RS256).
Extracts the ``sub`` claim as ``owner_identity`` for tenant isolation.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
from jwt import PyJWKClient, decode as jwt_decode

from app.core.logging import get_logger

logger = get_logger(__name__)

# Clerk's JWKS cache
_CLERK_JWKS_CACHE: dict[str, Any] = {}
_CLERK_JWKS_CACHE_TTL = 3600  # 1 hour
_CLERK_JWKS_CACHE_TIMESTAMP: float = 0


def _normalize_clerk_domain(value: str) -> str:
    """Normalize Clerk domain strings to a valid hostname."""
    domain = (value or "").strip()
    domain = domain.replace("https://", "").replace("http://", "")
    domain = domain.rstrip("/")
    # Some Clerk key encodings include a trailing marker; strip it so the
    # JWKS URL hostname remains valid.
    domain = domain.rstrip("$")
    return domain


def _get_clerk_jwks_client(publishable_key: str) -> PyJWKClient:
    """Get or create a cached JWKS client for Clerk."""
    global _CLERK_JWKS_CACHE, _CLERK_JWKS_CACHE_TIMESTAMP

    jwks_url = f"https://{_extract_clerk_domain(publishable_key)}/.well-known/jwks.json"

    now = time.time()
    cache_key = f"jwks:{jwks_url}"

    if cache_key in _CLERK_JWKS_CACHE and (now - _CLERK_JWKS_CACHE_TIMESTAMP) < _CLERK_JWKS_CACHE_TTL:
        return _CLERK_JWKS_CACHE[cache_key]

    client = PyJWKClient(jwks_url, cache_keys=True)
    _CLERK_JWKS_CACHE[cache_key] = client
    _CLERK_JWKS_CACHE_TIMESTAMP = now
    return client


def _extract_clerk_domain(publishable_key: str) -> str:
    """Extract the Clerk domain from the publishable key."""
    from app.config import get_settings

    settings = get_settings()
    if settings.clerk_frontend_api_url:
        return _normalize_clerk_domain(settings.clerk_frontend_api_url)

    key = publishable_key.strip()
    for prefix in ("pk_live_", "pk_test_"):
        if key.startswith(prefix):
            encoded = key[len(prefix):]
            if "$" in encoded:
                encoded = encoded.split("$")[0]
            try:
                import base64
                padding = 4 - len(encoded) % 4
                if padding != 4:
                    encoded += "=" * padding
                decoded = base64.urlsafe_b64decode(encoded).decode("utf-8")
                if decoded:
                    return _normalize_clerk_domain(decoded)
            except Exception:
                pass
                return _normalize_clerk_domain(f"{encoded}.clerk.accounts.dev")

            return _normalize_clerk_domain("clerk.accounts.dev")


class ClerkTokenError(Exception):
    """Raised when Clerk token validation fails."""


class ClerkJwtValidator:
    """Validates Clerk-issued JWTs and extracts user identity."""

    def __init__(
        self,
        *,
        secret_key: str,
        publishable_key: str,
        frontend_api_url: str | None = None,
    ) -> None:
        self._secret_key = secret_key
        self._publishable_key = publishable_key
        self._frontend_api_url = frontend_api_url
        self._jwks_client: PyJWKClient | None = None

    @property
    def _jwks(self) -> PyJWKClient:
        if self._jwks_client is None:
            if self._frontend_api_url:
                normalized = _normalize_clerk_domain(self._frontend_api_url)
                jwks_url = f"https://{normalized}/.well-known/jwks.json"
                self._jwks_client = PyJWKClient(jwks_url, cache_keys=True)
            else:
                self._jwks_client = _get_clerk_jwks_client(self._publishable_key)
        return self._jwks_client

    def verify_token(self, token: str) -> dict[str, Any]:
        """Verify a Clerk JWT and return its payload."""
        if not token:
            raise ClerkTokenError("Empty token")

        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)

            payload = jwt_decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                options={
                    "verify_exp": True,
                    "verify_iat": True,
                    "require": ["exp", "sub"],
                },
            )

            if "sub" not in payload:
                raise ClerkTokenError("Token missing 'sub' claim (user ID)")

            return payload
        except ClerkTokenError:
            raise
        except Exception as exc:
            raise ClerkTokenError(f"Clerk JWT verification failed: {exc}") from exc

    def extract_owner_identity(self, payload: dict[str, Any]) -> str:
        """Extract the owner identity from a verified Clerk JWT payload."""
        owner = (
            payload.get("sub")
            or payload.get("user_id")
            or payload.get("id")
            or ""
        )
        return str(owner).strip()

    def extract_user_info(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Extract user information from a verified Clerk JWT payload."""
        return {
            "owner_identity": self.extract_owner_identity(payload),
            "email": payload.get("email") or "",
            "first_name": payload.get("first_name") or "",
            "last_name": payload.get("last_name") or "",
            "image_url": payload.get("image_url") or "",
            "session_id": payload.get("sid") or "",
        }


# Singleton instance
_validator_instance: ClerkJwtValidator | None = None


def get_clerk_validator() -> ClerkJwtValidator | None:
    """Get or create the Clerk JWT validator singleton.

    Returns None if Clerk is not configured.
    """
    global _validator_instance

    if _validator_instance is not None:
        return _validator_instance

    try:
        from app.config import get_settings

        settings = get_settings()
        if not settings.clerk_secret_key or not settings.clerk_publishable_key:
            return None

        _validator_instance = ClerkJwtValidator(
            secret_key=settings.clerk_secret_key,
            publishable_key=settings.clerk_publishable_key,
            frontend_api_url=settings.clerk_frontend_api_url,
        )
        return _validator_instance
    except Exception as exc:
        logger.warning("Failed to initialize Clerk validator", exc_info=exc)
        return None


async def verify_clerk_token(token: str) -> dict[str, Any] | None:
    """Verify a Clerk JWT and return user info."""
    validator = get_clerk_validator()
    if validator is None:
        return None

    try:
        payload = validator.verify_token(token)
        return validator.extract_user_info(payload)
    except ClerkTokenError as exc:
        # WARNING, not debug: every environment running this app defaults its
        # log level above DEBUG, so a debug-level line here is invisible in
        # practice — this is the one message that explains *why* a request
        # got a generic 401, and it must not require flipping log levels to see.
        logger.warning("Clerk token verification failed: %s", exc)
        return None
