"""GithubIdentityOAuthService — state sign/verify, token encryption, install
upsert. Mirrors test_slack_oauth_service.py's structure exactly; the only
real differences are GitHub's field names (github_user_id/github_login/
avatar_url instead of team_id/team_name/bot_user_id).

No live DB, no network I/O — FakeRepo/FakeSession stand in for the real
repository and AsyncSession.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.core.exceptions import GithubOAuthError, GithubStateError
from app.database.models import GithubIdentity
from app.services.github_identity_oauth_service import GithubIdentityOAuthService


class FakeRepo:
    """Minimal GithubIdentityRepository stub — no real SQL."""

    def __init__(self, rows: dict[str, GithubIdentity] | None = None) -> None:
        self._rows = dict(rows or {})
        self.created: list[GithubIdentity] = []
        self.updated: list[GithubIdentity] = []

    async def get_by_owner(self, owner: str) -> GithubIdentity | None:
        return self._rows.get(owner)

    async def create(self, entity: GithubIdentity) -> GithubIdentity:
        entity.id = uuid.uuid4()
        entity.created_at = datetime.now(UTC)
        entity.updated_at = datetime.now(UTC)
        self._rows[entity.owner_identity] = entity
        self.created.append(entity)
        return entity

    async def update(self, entity: GithubIdentity) -> GithubIdentity:
        entity.updated_at = datetime.now(UTC)
        self.updated.append(entity)
        return entity

    async def delete_by_owner(self, owner: str) -> bool:
        if owner in self._rows:
            del self._rows[owner]
            return True
        return False


def make_settings(**overrides: object) -> Settings:
    """Settings with explicit GitHub OAuth fields — isolated from the real
    .env. Same aliasing gotcha as make_settings in
    test_slack_oauth_service.py: aliased fields need the SCREAMING_SNAKE_CASE
    validation_alias, not the snake_case field name."""
    defaults: dict[str, object] = dict(
        environment="development",
        GITHUB_OAUTH_CLIENT_ID="test-client-id",
        GITHUB_OAUTH_CLIENT_SECRET="test-client-secret",
        GITHUB_OAUTH_REDIRECT_URI="http://localhost:8003/api/github/oauth/callback",
        GITHUB_OAUTH_STATE_SECRET="test-state-secret",
        GITHUB_OAUTH_STATE_TTL_SECONDS=600,
        GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY=None,
        DATABASE_URL="postgresql://root@localhost:26257/migration_oracle?sslmode=disable",
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


@pytest.fixture
def session() -> AsyncMock:
    mock = AsyncMock()
    mock.commit = AsyncMock()
    mock.rollback = AsyncMock()
    mock.refresh = AsyncMock()
    return mock


def make_service(
    *, settings: Settings | None = None, repo: FakeRepo | None = None, session: AsyncMock
) -> tuple[GithubIdentityOAuthService, FakeRepo]:
    repo = repo or FakeRepo()
    service = GithubIdentityOAuthService(repository=repo, session=session)
    service._settings = settings or make_settings()  # type: ignore[attr-defined]
    return service, repo


# --------------------------------------------------------------- state --


def test_issue_and_verify_state_roundtrip(session: AsyncMock) -> None:
    service, _ = make_service(session=session)
    state, ttl = service.issue_state("alice@example.com")
    assert ttl == 600
    assert service.verify_state(state) == "alice@example.com"


def test_verify_state_rejects_tampered_signature(session: AsyncMock) -> None:
    service, _ = make_service(session=session)
    state, _ = service.issue_state("alice@example.com")
    signature, encoded = state.split(".", 1)
    tampered = f"{signature[:-1]}0.{encoded}"
    with pytest.raises(GithubStateError):
        service.verify_state(tampered)


def test_verify_state_rejects_expired(session: AsyncMock) -> None:
    settings = make_settings(GITHUB_OAUTH_STATE_TTL_SECONDS=60)
    service, _ = make_service(settings=settings, session=session)
    expired_state = service._sign_state(  # noqa: SLF001 - testing internal signing
        "alice@example.com", "nonce", int(time.time()) - 1
    )
    with pytest.raises(GithubStateError):
        service.verify_state(expired_state)


def test_verify_state_rejects_malformed(session: AsyncMock) -> None:
    service, _ = make_service(session=session)
    with pytest.raises(GithubStateError):
        service.verify_state("not-a-real-state")
    with pytest.raises(GithubStateError):
        service.verify_state("")


def test_state_secret_missing_raises(session: AsyncMock) -> None:
    settings = make_settings(GITHUB_OAUTH_STATE_SECRET=None)
    service, _ = make_service(settings=settings, session=session)
    with pytest.raises(GithubOAuthError):
        service.issue_state("alice@example.com")


# ------------------------------------------------------- token encryption --


def test_encrypt_decrypt_roundtrip_with_explicit_key(session: AsyncMock) -> None:
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    settings = make_settings(GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY=key)
    service, _ = make_service(settings=settings, session=session)
    ciphertext = service.encrypt_token("gho_realtoken")
    assert ciphertext != "gho_realtoken"
    assert service.decrypt_token(ciphertext) == "gho_realtoken"


def test_encrypt_decrypt_dev_fallback_without_key(session: AsyncMock) -> None:
    """No key + non-production derives an ephemeral key rather than raising."""
    settings = make_settings(
        GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY=None, environment="development"
    )
    service, _ = make_service(settings=settings, session=session)
    ciphertext = service.encrypt_token("gho_realtoken")
    assert service.decrypt_token(ciphertext) == "gho_realtoken"


def test_production_without_key_hard_errors(session: AsyncMock) -> None:
    settings = make_settings(
        GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY=None, environment="production"
    )
    service, _ = make_service(settings=settings, session=session)
    with pytest.raises(GithubOAuthError):
        service.encrypt_token("gho_realtoken")


# ------------------------------------------------------------- configured --


def test_configured_true_when_all_present(session: AsyncMock) -> None:
    service, _ = make_service(session=session)
    assert service.configured is True


def test_configured_false_when_client_secret_missing(session: AsyncMock) -> None:
    settings = make_settings(GITHUB_OAUTH_CLIENT_SECRET=None)
    service, _ = make_service(settings=settings, session=session)
    assert service.configured is False


# --------------------------------------------------------- install upsert --


@pytest.mark.asyncio
async def test_install_persists_identity_on_create(session: AsyncMock) -> None:
    service, repo = make_service(session=session)
    state, _ = service.issue_state("alice@example.com")

    async def fake_exchange_code(code: str) -> dict[str, object]:
        return {
            "access_token": "gho_abc",
            "scope": "read:user",
            "github_user_id": 42,
            "github_login": "alice-gh",
            "avatar_url": "https://avatars.githubusercontent.com/u/42",
        }

    service.exchange_code = fake_exchange_code  # type: ignore[assignment]
    identity = await service.install(
        owner_identity="alice@example.com", code="abc", state=state
    )
    assert identity.github_login == "alice-gh"
    assert identity.github_user_id == 42
    assert len(repo.created) == 1
    assert repo.created[0].github_login == "alice-gh"


@pytest.mark.asyncio
async def test_install_updates_identity_on_reconnect(session: AsyncMock) -> None:
    existing = GithubIdentity(
        owner_identity="alice@example.com",
        github_user_id=1,
        github_login="old-login",
        avatar_url=None,
        access_token="old-cipher",
        scope="read:user",
        connected_at=datetime.now(UTC),
    )
    repo = FakeRepo({"alice@example.com": existing})
    service, repo = make_service(repo=repo, session=session)
    state, _ = service.issue_state("alice@example.com")

    async def fake_exchange_code(code: str) -> dict[str, object]:
        return {
            "access_token": "gho_new",
            "scope": "read:user",
            "github_user_id": 99,
            "github_login": "new-login",
            "avatar_url": "https://avatars.githubusercontent.com/u/99",
        }

    service.exchange_code = fake_exchange_code  # type: ignore[assignment]
    identity = await service.install(
        owner_identity="alice@example.com", code="abc", state=state
    )
    assert identity.github_login == "new-login"
    assert identity.github_user_id == 99
    assert len(repo.updated) == 1
    assert identity is existing


@pytest.mark.asyncio
async def test_install_rejects_owner_mismatch(session: AsyncMock) -> None:
    service, _ = make_service(session=session)
    state, _ = service.issue_state("alice@example.com")
    with pytest.raises(GithubStateError):
        await service.install(
            owner_identity="mallory@example.com", code="abc", state=state
        )


@pytest.mark.asyncio
async def test_exchange_code_rejects_missing_access_token(session: AsyncMock) -> None:
    """A GitHub OAuth response with no access_token must not be silently
    treated as success."""
    import httpx

    service, _ = make_service(session=session)

    async def fake_post(self, url, **kwargs):  # noqa: ANN001
        return httpx.Response(200, json={"scope": "read:user"}, request=httpx.Request("POST", url))

    import unittest.mock as mock

    with mock.patch("httpx.AsyncClient.post", fake_post):
        with pytest.raises(GithubOAuthError):
            await service.exchange_code("some-code")


# --------------------------------------------------------- disconnect --


@pytest.mark.asyncio
async def test_disconnect_removes_existing_identity(session: AsyncMock) -> None:
    existing = GithubIdentity(
        owner_identity="alice@example.com",
        github_user_id=1,
        github_login="alice-gh",
        avatar_url=None,
        access_token="cipher",
        scope="read:user",
        connected_at=datetime.now(UTC),
    )
    repo = FakeRepo({"alice@example.com": existing})
    service, repo = make_service(repo=repo, session=session)

    deleted = await service.disconnect("alice@example.com")
    assert deleted is True
    assert await repo.get_by_owner("alice@example.com") is None


@pytest.mark.asyncio
async def test_disconnect_no_identity_returns_false(session: AsyncMock) -> None:
    service, _ = make_service(session=session)
    deleted = await service.disconnect("nobody@example.com")
    assert deleted is False
