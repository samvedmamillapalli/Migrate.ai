"""SlackOAuthService — state sign/verify, token encryption, install upsert.

Replaces `backend/_verify_slack_thorough.py`, which shipped on the
`samrita` branch truncated mid-function (unclosed paren, fails
`ast.parse`) and was never runnable. These tests cover the same ground for
the OAuth half plus the `authed_user_id` persistence added in migration
`q2l8i5d9e6a7` (not covered by the original script, which predates it).

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
from app.core.exceptions import SlackOAuthError, SlackStateError
from app.database.models import SlackInstallation
from app.services.slack_oauth_service import SlackOAuthService


class FakeRepo:
    """Minimal SlackInstallationRepository stub — no real SQL."""

    def __init__(self, rows: dict[str, SlackInstallation] | None = None) -> None:
        self._rows = dict(rows or {})
        self.created: list[SlackInstallation] = []
        self.updated: list[SlackInstallation] = []

    async def get_by_owner(self, owner: str) -> SlackInstallation | None:
        return self._rows.get(owner)

    async def create(self, entity: SlackInstallation) -> SlackInstallation:
        entity.id = uuid.uuid4()
        entity.created_at = datetime.now(UTC)
        entity.updated_at = datetime.now(UTC)
        self._rows[entity.owner_identity] = entity
        self.created.append(entity)
        return entity

    async def update(self, entity: SlackInstallation) -> SlackInstallation:
        entity.updated_at = datetime.now(UTC)
        self.updated.append(entity)
        return entity


def make_settings(**overrides: object) -> Settings:
    """Settings with explicit Slack fields — isolated from the real .env.

    Most Slack fields declare a ``validation_alias`` (e.g. ``SLACK_CLIENT_ID``
    for ``slack_client_id``); the model has no ``populate_by_name=True``, so
    constructing with the snake_case field name is silently ignored
    (``extra="ignore"``) and falls through to whatever's in the real .env —
    a real bug caught while writing this fixture, initially causing every
    override here to be a no-op. Aliased fields need the SCREAMING_SNAKE_CASE
    alias; ``environment`` has no alias and takes its plain field name
    instead — the two conventions don't mix, so get this wrong per-field and
    the override is silently dropped rather than erroring.
    """
    defaults: dict[str, object] = dict(
        environment="development",
        SLACK_CLIENT_ID="test-client-id",
        SLACK_CLIENT_SECRET="test-client-secret",
        SLACK_REDIRECT_URI="http://localhost:8003/api/slack/oauth/callback",
        SLACK_STATE_SECRET="test-state-secret",
        SLACK_STATE_TTL_SECONDS=600,
        SLACK_BOT_SCOPE="chat:write",
        SLACK_TOKEN_ENCRYPTION_KEY=None,
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
) -> tuple[SlackOAuthService, FakeRepo]:
    repo = repo or FakeRepo()
    service = SlackOAuthService(repository=repo, session=session)
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
    with pytest.raises(SlackStateError):
        service.verify_state(tampered)


def test_verify_state_rejects_expired(session: AsyncMock) -> None:
    settings = make_settings(SLACK_STATE_TTL_SECONDS=60)
    service, _ = make_service(settings=settings, session=session)
    # Issue a state that expired one second ago by forging the payload
    # directly, rather than sleeping in a test.
    expired_state = service._sign_state(  # noqa: SLF001 - testing internal signing
        "alice@example.com", "nonce", int(time.time()) - 1
    )
    with pytest.raises(SlackStateError):
        service.verify_state(expired_state)


def test_verify_state_rejects_malformed(session: AsyncMock) -> None:
    service, _ = make_service(session=session)
    with pytest.raises(SlackStateError):
        service.verify_state("not-a-real-state")
    with pytest.raises(SlackStateError):
        service.verify_state("")


def test_state_secret_missing_raises(session: AsyncMock) -> None:
    settings = make_settings(SLACK_STATE_SECRET=None)
    service, _ = make_service(settings=settings, session=session)
    with pytest.raises(SlackOAuthError):
        service.issue_state("alice@example.com")


# ------------------------------------------------------- token encryption --


def test_encrypt_decrypt_roundtrip_with_explicit_key(session: AsyncMock) -> None:
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    settings = make_settings(SLACK_TOKEN_ENCRYPTION_KEY=key)
    service, _ = make_service(settings=settings, session=session)
    ciphertext = service.encrypt_token("xoxb-real-token")
    assert ciphertext != "xoxb-real-token"
    assert service.decrypt_token(ciphertext) == "xoxb-real-token"


def test_encrypt_decrypt_dev_fallback_without_key(session: AsyncMock) -> None:
    """No key + non-production derives an ephemeral key rather than raising."""
    settings = make_settings(
        SLACK_TOKEN_ENCRYPTION_KEY=None, environment="development"
    )
    service, _ = make_service(settings=settings, session=session)
    ciphertext = service.encrypt_token("xoxb-real-token")
    assert service.decrypt_token(ciphertext) == "xoxb-real-token"


def test_production_without_key_hard_errors(session: AsyncMock) -> None:
    settings = make_settings(SLACK_TOKEN_ENCRYPTION_KEY=None, environment="production")
    service, _ = make_service(settings=settings, session=session)
    with pytest.raises(SlackOAuthError):
        service.encrypt_token("xoxb-real-token")


# ------------------------------------------------------------- configured --


def test_configured_true_when_all_present(session: AsyncMock) -> None:
    service, _ = make_service(session=session)
    assert service.configured is True


def test_configured_false_when_client_secret_missing(session: AsyncMock) -> None:
    settings = make_settings(SLACK_CLIENT_SECRET=None)
    service, _ = make_service(settings=settings, session=session)
    assert service.configured is False


# --------------------------------------------------------- install upsert --


@pytest.mark.asyncio
async def test_install_persists_authed_user_id_on_create(session: AsyncMock) -> None:
    service, repo = make_service(session=session)
    state, _ = service.issue_state("alice@example.com")

    async def fake_exchange_code(code: str) -> dict[str, object]:
        return {
            "access_token": "xoxb-abc",
            "bot_user_id": "B123",
            "team_id": "T123",
            "team_name": "Acme",
            "scope": "chat:write",
            "authed_user_id": "U456",
        }

    service.exchange_code = fake_exchange_code  # type: ignore[assignment]
    installation = await service.install(
        owner_identity="alice@example.com", code="abc", state=state
    )
    assert installation.authed_user_id == "U456"
    assert len(repo.created) == 1
    assert repo.created[0].authed_user_id == "U456"


@pytest.mark.asyncio
async def test_install_persists_authed_user_id_on_update(session: AsyncMock) -> None:
    existing = SlackInstallation(
        owner_identity="alice@example.com",
        team_id="T_OLD",
        team_name="Old Team",
        bot_user_id="B_OLD",
        authed_user_id=None,
        bot_access_token="old-cipher",
        scope="chat:write",
        installed_at=datetime.now(UTC),
    )
    repo = FakeRepo({"alice@example.com": existing})
    service, repo = make_service(repo=repo, session=session)
    state, _ = service.issue_state("alice@example.com")

    async def fake_exchange_code(code: str) -> dict[str, object]:
        return {
            "access_token": "xoxb-new",
            "bot_user_id": "B_NEW",
            "team_id": "T_NEW",
            "team_name": "New Team",
            "scope": "chat:write",
            "authed_user_id": "U789",
        }

    service.exchange_code = fake_exchange_code  # type: ignore[assignment]
    installation = await service.install(
        owner_identity="alice@example.com", code="abc", state=state
    )
    assert installation.authed_user_id == "U789"
    assert len(repo.updated) == 1
    assert installation is existing


@pytest.mark.asyncio
async def test_install_normalizes_empty_authed_user_id_to_none(
    session: AsyncMock,
) -> None:
    """exchange_code returns "" (never None) when Slack omits authed_user —
    install() must not persist that empty string as a value."""
    service, repo = make_service(session=session)
    state, _ = service.issue_state("alice@example.com")

    async def fake_exchange_code(code: str) -> dict[str, object]:
        return {
            "access_token": "xoxb-abc",
            "bot_user_id": "B123",
            "team_id": "T123",
            "team_name": None,
            "scope": "chat:write",
            "authed_user_id": "",
        }

    service.exchange_code = fake_exchange_code  # type: ignore[assignment]
    installation = await service.install(
        owner_identity="alice@example.com", code="abc", state=state
    )
    assert installation.authed_user_id is None


@pytest.mark.asyncio
async def test_install_rejects_owner_mismatch(session: AsyncMock) -> None:
    service, _ = make_service(session=session)
    state, _ = service.issue_state("alice@example.com")
    with pytest.raises(SlackStateError):
        await service.install(
            owner_identity="mallory@example.com", code="abc", state=state
        )
