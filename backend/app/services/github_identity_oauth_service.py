"""GitHub OAuth identity service — install redirect, callback exchange,
persistence. Mirrors SlackOAuthService's structure exactly (state signing,
token encryption, upsert-by-owner); the only real differences are GitHub's
OAuth endpoints and response shape.

Owns:
- server-side OAuth ``state`` generation/verification (HMAC-SHA256, TTL-bounded)
- Fernet encryption of the access token at rest
- GitHub's standard OAuth 2.0 code exchange via httpx
- upsert of one GithubIdentity per Clerk ``owner_identity``

Never used to act on any repo — ``scope`` is ``read:user`` only. This is a
different credential entirely from the GitHub App used for PR-integration
webhooks (see app/services/github_app_client.py).
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
from app.core.exceptions import GithubOAuthError, GithubStateError, ValidationError
from app.core.logging import get_logger
from app.database.models import GithubIdentity
from app.database.retry import with_txn_retry
from app.repositories.github_identity_repository import GithubIdentityRepository
from app.schemas.github_identity import GithubIdentityInstallAuthorizeResponse

logger = get_logger(__name__)

_GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GITHUB_USER_URL = "https://api.github.com/user"
_OAUTH_SCOPE = "read:user"
_STATE_VERSION = 1


def _get_fernet(settings: Settings | None = None) -> Any | None:
    """Return a Fernet cipher for token encryption, or None when unset.

    Same dev-fallback posture as slack_oauth_service._get_fernet: an unset
    key derives an ephemeral one from the database URL outside production
    (tokens won't survive an engine restart), and is a hard error in
    production. Accepts explicit ``settings`` so an injected instance never
    silently falls back to a mismatched global lookup.
    """
    settings = settings or get_settings()
    raw = settings.github_oauth_token_encryption_key
    if raw is not None and raw.get_secret_value().strip():
        try:
            from cryptography.fernet import Fernet

            return Fernet(raw.get_secret_value().strip().encode("ascii"))
        except Exception as exc:
            raise GithubOAuthError(
                "GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY is not a valid Fernet key"
            ) from exc

    env = settings.environment.strip().lower()
    if env in {"production", "prod"}:
        raise GithubOAuthError(
            "GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY is required in production"
        )

    logger.warning(
        "GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY unset; deriving ephemeral Fernet key "
        "(dev-only, tokens will not survive an engine restart)"
    )
    digest = hashlib.sha256(
        settings.database_url.get_secret_value().encode("utf-8")
    ).digest()
    return _fernet_from_bytes(digest)


def _fernet_from_bytes(raw: bytes) -> Any:
    from cryptography.fernet import Fernet

    return Fernet(base64.urlsafe_b64encode(raw))


class GithubIdentityOAuthService:
    """Coordinates GitHub OAuth identity install/callback/disconnect and
    persistence."""

    def __init__(
        self,
        repository: GithubIdentityRepository,
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
            s.github_oauth_client_id
            and s.github_oauth_client_secret
            and s.github_oauth_client_secret.get_secret_value()
            and s.github_oauth_redirect_uri
        )

    def _require_configured(self) -> None:
        if not self.configured:
            raise GithubOAuthError(
                "GitHub OAuth identity is not configured. Set "
                "GITHUB_OAUTH_CLIENT_ID, GITHUB_OAUTH_CLIENT_SECRET, and "
                "GITHUB_OAUTH_REDIRECT_URI."
            )

    # --- State sign / verify (CSRF protection) ---

    def _state_secret(self) -> bytes:
        secret = (self._settings.github_oauth_state_secret or "").strip()
        if not secret:
            raise GithubOAuthError(
                "GITHUB_OAUTH_STATE_SECRET is required for GitHub OAuth state signing"
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
        signature = hmac.new(self._state_secret(), body, hashlib.sha256).hexdigest()
        encoded = base64.urlsafe_b64encode(body).decode("ascii")
        return f"{signature}.{encoded}"

    def issue_state(self, owner_identity: str) -> tuple[str, int]:
        ttl = int(self._settings.github_oauth_state_ttl_seconds)
        expires_at = int(time.time()) + ttl
        nonce = uuid.uuid4().hex
        return self._sign_state(owner_identity, nonce, expires_at), ttl

    def verify_state(self, state: str) -> str:
        if not state:
            raise GithubStateError("Missing OAuth state")
        parts = state.split(".", 1)
        if len(parts) != 2:
            raise GithubStateError("Malformed OAuth state")
        signature, encoded = parts
        try:
            body = base64.urlsafe_b64decode(encoded.encode("ascii"))
        except Exception as exc:
            raise GithubStateError("Malformed OAuth state payload") from exc

        expected = hmac.new(self._state_secret(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise GithubStateError("OAuth state signature mismatch")

        try:
            payload = json.loads(body.decode("utf-8"))
            version = int(payload.get("v", 0))
            owner = str(payload.get("owner", "")).strip()
            expires_at = int(payload.get("exp", 0))
        except (ValueError, TypeError, KeyError) as exc:
            raise GithubStateError("OAuth state payload is invalid") from exc

        if version != _STATE_VERSION:
            raise GithubStateError("OAuth state version mismatch")
        if not owner:
            raise GithubStateError("OAuth state missing owner identity")
        if int(time.time()) > expires_at:
            raise GithubStateError("OAuth state has expired")

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
            raise GithubOAuthError("Failed to decrypt GitHub access token") from exc

    # --- Authorize URL ---

    async def build_authorize_url(
        self, owner_identity: str
    ) -> GithubIdentityInstallAuthorizeResponse:
        self._require_configured()
        owner = (owner_identity or "").strip()
        if not owner:
            raise ValidationError("owner_identity is required for GitHub install")

        state, _ttl = self.issue_state(owner)
        params = {
            "client_id": self._settings.github_oauth_client_id,
            "scope": _OAUTH_SCOPE,
            "state": state,
            "redirect_uri": self._settings.github_oauth_redirect_uri,
        }
        url = f"{_GITHUB_AUTHORIZE_URL}?{urlencode(params)}"
        return GithubIdentityInstallAuthorizeResponse(authorize_url=url)

    # --- OAuth code exchange ---

    async def exchange_code(self, code: str) -> dict[str, Any]:
        self._require_configured()
        if not code:
            raise GithubOAuthError("Missing OAuth code")

        form = {
            "client_id": self._settings.github_oauth_client_id,
            "client_secret": self._settings.github_oauth_client_secret.get_secret_value(),  # type: ignore[union-attr]
            "code": code,
            "redirect_uri": self._settings.github_oauth_redirect_uri,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(
                    _GITHUB_TOKEN_URL,
                    data=form,
                    headers={"Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise GithubOAuthError(
                    f"GitHub OAuth exchange failed at network layer: {exc}"
                ) from exc

        if resp.status_code >= 400:
            raise GithubOAuthError(
                f"GitHub OAuth exchange failed with HTTP {resp.status_code}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise GithubOAuthError("GitHub OAuth exchange returned invalid JSON") from exc

        if data.get("error"):
            raise GithubOAuthError(
                f"GitHub OAuth exchange failed: {data.get('error')} "
                f"({data.get('error_description', '')})"
            )

        access_token = str(data.get("access_token", "")).strip()
        scope = str(data.get("scope", "")).strip()
        if not access_token:
            raise GithubOAuthError(
                "GitHub OAuth response did not include an access_token"
            )

        # Fetch the identity this token actually belongs to — the whole
        # point of this integration. A bad/expired token surfaces here as a
        # 401 from GitHub, not silently stored.
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                user_resp = await client.get(
                    _GITHUB_USER_URL,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                    },
                )
            except httpx.HTTPError as exc:
                raise GithubOAuthError(
                    f"GitHub user lookup failed at network layer: {exc}"
                ) from exc

        if user_resp.status_code >= 400:
            raise GithubOAuthError(
                f"GitHub user lookup failed with HTTP {user_resp.status_code}"
            )

        try:
            user = user_resp.json()
        except ValueError as exc:
            raise GithubOAuthError("GitHub user lookup returned invalid JSON") from exc

        github_user_id = user.get("id")
        github_login = str(user.get("login", "")).strip()
        if not github_user_id or not github_login:
            raise GithubOAuthError("GitHub user lookup response missing id/login")

        return {
            "access_token": access_token,
            "scope": scope,
            "github_user_id": int(github_user_id),
            "github_login": github_login,
            "avatar_url": user.get("avatar_url"),
        }

    # --- Install (upsert) ---

    async def install(
        self,
        *,
        owner_identity: str,
        code: str,
        state: str,
    ) -> GithubIdentity:
        owner = self.verify_state(state)
        if owner != (owner_identity or "").strip():
            raise GithubStateError(
                "OAuth state owner does not match the authenticated user"
            )

        token_data = await self.exchange_code(code)

        async def _commit() -> tuple[GithubIdentity, bool]:
            existing = await self._repository.get_by_owner(owner)
            now = datetime.now(UTC)
            encrypted = self.encrypt_token(token_data["access_token"])

            if existing is not None:
                existing.github_user_id = token_data["github_user_id"]
                existing.github_login = token_data["github_login"]
                existing.avatar_url = token_data["avatar_url"]
                existing.access_token = encrypted
                existing.scope = token_data["scope"]
                existing.connected_at = now
                updated = await self._repository.update(existing)
            else:
                updated = GithubIdentity(
                    owner_identity=owner,
                    github_user_id=token_data["github_user_id"],
                    github_login=token_data["github_login"],
                    avatar_url=token_data["avatar_url"],
                    access_token=encrypted,
                    scope=token_data["scope"],
                    connected_at=now,
                )
                updated = await self._repository.create(updated)

            await self._session.commit()
            await self._session.refresh(updated)
            return updated, existing is not None

        identity, had_existing = await with_txn_retry(
            _commit, on_retry=self._session.rollback
        )
        logger.info(
            "GitHub identity upserted",
            extra={
                "owner_identity": owner,
                "github_login": token_data["github_login"],
                "had_existing": had_existing,
            },
        )
        return identity

    # --- Lookup / disconnect ---

    async def get_identity(self, owner_identity: str) -> GithubIdentity | None:
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
            logger.info("GitHub identity disconnected", extra={"owner_identity": owner})
        return deleted


__all__ = ["GithubIdentityOAuthService"]
