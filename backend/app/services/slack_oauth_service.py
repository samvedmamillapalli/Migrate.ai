"""Slack OAuth v2 service — install redirect, callback exchange, persistence.

Owns the business logic and transactions for Slack OAuth:
- server-side OAuth ``state`` generation/verification (HMAC-SHA256, TTL-bounded)
- Fernet encryption of the bot access token at rest
- Slack ``oauth.v2.access`` code exchange via httpx
- upsert of one SlackInstallation per Clerk ``owner_identity``
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.exceptions import SlackOAuthError, SlackStateError, ValidationError
from app.core.logging import get_logger
from app.database.models import SlackInstallation
from app.database.retry import with_txn_retry
from app.repositories.slack_installation_repository import SlackInstallationRepository
from app.schemas.slack import SlackInstallAuthorizeResponse

logger = get_logger(__name__)

_SLACK_AUTHORIZE_URL = "https://slack.com/oauth/v2/authorize"
_SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access"
_STATE_VERSION = 1


def _get_fernet(settings: Settings | None = None) -> Any | None:
    """Return a Fernet cipher for token encryption, or None when unset.

    In non-production environments an unset key falls back to an ephemeral
    key derived from the app's database URL so local demos still work. In
    production an unset key is a hard error.

    Accepts an explicit ``settings`` so callers with an injected instance
    (``SlackOAuthService._settings``) don't silently fall back to a fresh
    global lookup that ignores that injection — that mismatch previously
    meant two service instances built with different ``Settings`` still
    encrypted/decrypted tokens using whichever settings ``get_settings()``'s
    cache happened to return, not the instance's own configuration.
    """
    settings = settings or get_settings()
    raw = settings.slack_token_encryption_key
    if raw is not None and raw.get_secret_value().strip():
        try:
            from cryptography.fernet import Fernet

            return Fernet(raw.get_secret_value().strip().encode("ascii"))
        except Exception as exc:
            raise SlackOAuthError(
                "SLACK_TOKEN_ENCRYPTION_KEY is not a valid Fernet key"
            ) from exc

    env = settings.environment.strip().lower()
    if env in {"production", "prod"}:
        raise SlackOAuthError(
            "SLACK_TOKEN_ENCRYPTION_KEY is required in production"
        )

    # Dev/local fallback: derive an ephemeral key from the database URL so
    # tokens are still opaque in the DB without a shared deployment secret.
    logger.warning(
        "SLACK_TOKEN_ENCRYPTION_KEY unset; deriving ephemeral Fernet key "
        "(dev-only, tokens will not survive an engine restart)"
    )
    digest = hashlib.sha256(
        settings.database_url.get_secret_value().encode("utf-8")
    ).digest()
    return _fernet_from_bytes(digest)


def _fernet_from_bytes(raw: bytes) -> Any:
    from cryptography.fernet import Fernet

    return Fernet(base64.urlsafe_b64encode(raw))


class SlackOAuthService:
    """Coordinates Slack OAuth install/callback/disconnect and persistence."""

    def __init__(
        self,
        repository: SlackInstallationRepository,
        session: AsyncSession,
    ) -> None:
        self._repository = repository
        self._session = session
        self._settings: Settings = get_settings()

    # --- Configuration helpers ---

    @property
    def configured(self) -> bool:
        s = self._settings
        return bool(
            s.slack_client_id
            and s.slack_client_secret
            and s.slack_client_secret.get_secret_value()
            and s.slack_redirect_uri
        )

    def _require_configured(self) -> None:
        if not self.configured:
            raise SlackOAuthError(
                "Slack OAuth is not configured. Set SLACK_CLIENT_ID, "
                "SLACK_CLIENT_SECRET, and SLACK_REDIRECT_URI."
            )

    # --- State sign / verify (CSRF protection) ---

    def _state_secret(self) -> bytes:
        secret = (self._settings.slack_state_secret or "").strip()
        if not secret:
            raise SlackOAuthError(
                "SLACK_STATE_SECRET is required for Slack OAuth state signing"
            )
        return secret.encode("utf-8")

    def _sign_state(self, owner_identity: str, nonce: str, expires_at: int) -> str:
        payload = {
            "v": _STATE_VERSION,
            "owner": owner_identity,
            "nonce": nonce,
            "exp": expires_at,
        }
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = hmac.new(
            self._state_secret(),
            body,
            hashlib.sha256,
        ).hexdigest()
        encoded = base64.urlsafe_b64encode(body).decode("ascii")
        return f"{signature}.{encoded}"

    def issue_state(self, owner_identity: str) -> tuple[str, int]:
        """Create a signed, TTL-bounded OAuth state for the given owner."""
        ttl = int(self._settings.slack_state_ttl_seconds)
        expires_at = int(time.time()) + ttl
        nonce = uuid.uuid4().hex
        return self._sign_state(owner_identity, nonce, expires_at), ttl

    def verify_state(self, state: str) -> str:
        """Validate the signed state and return the embedded owner identity."""
        if not state:
            raise SlackStateError("Missing OAuth state")
        parts = state.split(".", 1)
        if len(parts) != 2:
            raise SlackStateError("Malformed OAuth state")
        signature, encoded = parts
        try:
            body = base64.urlsafe_b64decode(encoded.encode("ascii"))
        except Exception as exc:
            raise SlackStateError("Malformed OAuth state payload") from exc

        expected = hmac.new(
            self._state_secret(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise SlackStateError("OAuth state signature mismatch")

        try:
            payload = json.loads(body.decode("utf-8"))
            version = int(payload.get("v", 0))
            owner = str(payload.get("owner", "")).strip()
            expires_at = int(payload.get("exp", 0))
        except (ValueError, TypeError, KeyError) as exc:
            raise SlackStateError("OAuth state payload is invalid") from exc

        if version != _STATE_VERSION:
            raise SlackStateError("OAuth state version mismatch")
        if not owner:
            raise SlackStateError("OAuth state missing owner identity")
        if int(time.time()) > expires_at:
            raise SlackStateError("OAuth state has expired")

        return owner

    # --- Token encryption ---

    def encrypt_token(self, token: str) -> str:
        fernet = _get_fernet(self._settings)
        if fernet is None:
            return token
        return fernet.encrypt(token.encode("utf-8")).decode("ascii")

    def decrypt_token(self, ciphertext: str) -> str:
        fernet = _get_fernet(self._settings)
        if fernet is None:
            return ciphertext
        try:
            return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except Exception as exc:
            raise SlackOAuthError("Failed to decrypt Slack bot token") from exc

    # --- Authorize URL ---

    async def build_authorize_url(self, owner_identity: str) -> SlackInstallAuthorizeResponse:
        """Build the Slack v2 OAuth authorize URL for the given owner."""
        self._require_configured()
        owner = (owner_identity or "").strip()
        if not owner:
            raise ValidationError("owner_identity is required for Slack install")

        state, ttl = self.issue_state(owner)
        params = {
            "client_id": self._settings.slack_client_id,
            "scope": self._settings.slack_bot_scope,
            "state": state,
            "redirect_uri": self._settings.slack_redirect_uri,
        }
        url = f"{_SLACK_AUTHORIZE_URL}?{urlencode(params)}"
        return SlackInstallAuthorizeResponse(
            authorize_url=url,
            state=state,
            expires_in_seconds=ttl,
        )

    # --- OAuth code exchange ---

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange a temporary Slack OAuth code for an access token."""
        self._require_configured()
        if not code:
            raise SlackOAuthError("Missing OAuth code")

        form = {
            "client_id": self._settings.slack_client_id,
            "client_secret": self._settings.slack_client_secret.get_secret_value(),
            "code": code,
            "redirect_uri": self._settings.slack_redirect_uri,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(_SLACK_TOKEN_URL, data=form)
            except httpx.HTTPError as exc:
                raise SlackOAuthError(
                    f"Slack OAuth exchange failed at network layer: {exc}"
                ) from exc

        if resp.status_code >= 400:
            raise SlackOAuthError(
                f"Slack OAuth exchange failed with HTTP {resp.status_code}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise SlackOAuthError("Slack OAuth exchange returned invalid JSON") from exc

        if not data.get("ok"):
            error = str(data.get("error", "unknown_error"))
            raise SlackOAuthError(f"Slack OAuth exchange failed: {error}")

        access_token = str(data.get("access_token", "")).strip()
        bot_user_id = str(
            (data.get("bot_user_id") or "")
        ).strip()
        team_id = str(data.get("team", {}).get("id", "")).strip() if isinstance(
            data.get("team"), dict
        ) else str(data.get("team_id", "")).strip()
        team_name = (
            str(data.get("team", {}).get("name", "")).strip()
            if isinstance(data.get("team"), dict)
            else str(data.get("team_name", "")).strip() or None
        )
        scopes = str(data.get("scope", "")).strip()
        authed_user = data.get("authed_user") or {}
        authed_user_id = str(authed_user.get("id", "")).strip() if isinstance(authed_user, dict) else ""

        if not access_token:
            raise SlackOAuthError("Slack OAuth response did not include an access_token")
        if not bot_user_id:
            # Some Slack apps don't install a bot (only a user token). Require a
            # bot so subsequent chat:write calls have a bot identity.
            raise SlackOAuthError(
                "Slack OAuth response did not include a bot_user_id; "
                "verify the app has a Bot Token Scope such as chat:write"
            )
        if not team_id:
            raise SlackOAuthError("Slack OAuth response did not include a team id")

        return {
            "access_token": access_token,
            "bot_user_id": bot_user_id,
            "team_id": team_id,
            "team_name": team_name or None,
            "scope": scopes,
            "authed_user_id": authed_user_id,
        }

    # --- Install (upsert) ---

    async def install(
        self,
        *,
        owner_identity: str,
        code: str,
        state: str,
    ) -> SlackInstallation:
        """Validate state, exchange the code, and upsert the installation."""
        owner = self.verify_state(state)
        if owner != (owner_identity or "").strip():
            raise SlackStateError(
                "OAuth state owner does not match the authenticated user"
            )

        token_data = await self.exchange_code(code)

        # exchange_code returns "" (never None) when Slack's response omitted
        # authed_user.id — normalize to None so the model's nullable column
        # and the notification service's fallback chain both see "absent"
        # consistently, rather than persisting an empty string as a value.
        authed_user_id = token_data.get("authed_user_id") or None

        async def _commit() -> tuple[SlackInstallation, bool]:
            existing = await self._repository.get_by_owner(owner)
            now = datetime.now(UTC)
            encrypted = self.encrypt_token(token_data["access_token"])

            if existing is not None:
                existing.team_id = token_data["team_id"]
                existing.team_name = token_data["team_name"]
                existing.bot_user_id = token_data["bot_user_id"]
                existing.authed_user_id = authed_user_id
                existing.bot_access_token = encrypted
                existing.scope = token_data["scope"]
                existing.installed_at = now
                updated = await self._repository.update(existing)
            else:
                updated = SlackInstallation(
                    owner_identity=owner,
                    team_id=token_data["team_id"],
                    team_name=token_data["team_name"],
                    bot_user_id=token_data["bot_user_id"],
                    authed_user_id=authed_user_id,
                    bot_access_token=encrypted,
                    scope=token_data["scope"],
                    installed_at=now,
                )
                updated = await self._repository.create(updated)

            await self._session.commit()
            await self._session.refresh(updated)
            return updated, existing is not None

        installation, had_existing = await with_txn_retry(
            _commit, on_retry=self._session.rollback
        )
        logger.info(
            "Slack installation upserted",
            extra={
                "owner_identity": owner,
                "team_id": token_data["team_id"],
                "had_existing": had_existing,
            },
        )
        return installation

    # --- Lookup / disconnect ---

    async def get_installation(self, owner_identity: str) -> SlackInstallation | None:
        owner = (owner_identity or "").strip()
        if not owner:
            return None
        return await self._repository.get_by_owner(owner)

    async def disconnect(self, owner_identity: str) -> bool:
        owner = (owner_identity or "").strip()
        if not owner:
            raise ValidationError("owner_identity is required")
        async def _commit() -> bool:
            deleted = await self._repository.delete_by_owner(owner)
            await self._session.commit()
            return deleted

        deleted = await with_txn_retry(_commit, on_retry=self._session.rollback)
        if deleted:
            logger.info(
                "Slack installation disconnected",
                extra={"owner_identity": owner},
            )
        return deleted


__all__ = ["SlackOAuthService"]
