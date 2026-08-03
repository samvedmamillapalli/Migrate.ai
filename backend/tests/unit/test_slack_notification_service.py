"""SlackNotificationService — channel resolution and best-effort posting.

Replaces `backend/_verify_slack_thorough.py` (truncated/unrunnable on the
`samrita` branch — see test_slack_oauth_service.py's module docstring).
Also covers the DM-first channel resolution added on top of the merged
branch: explicit channel -> installation.authed_user_id ->
SLACK_DEFAULT_CHANNEL -> skip. The original branch's design used a single
hardcoded channel with chat:write-only scope, which fails with
not_in_channel for any channel the bot hasn't joined — every notification
would have failed silently. These tests exist specifically to pin the fix.

No live network — httpx calls are patched.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.config import Settings
from app.core.exceptions import SlackOAuthError
from app.database.models import SlackInstallation
from app.services.slack_notification_service import SlackNotificationService


def make_settings(**overrides: object) -> Settings:
    """See test_slack_oauth_service.py's make_settings for why the alias
    casing matters here (SLACK_DEFAULT_CHANNEL is aliased; unrelated fields
    are not)."""
    defaults: dict[str, object] = dict(
        SLACK_DEFAULT_CHANNEL="general",
        FRONTEND_URL="http://localhost:3000",
        DATABASE_URL="postgresql://root@localhost:26257/migration_oracle?sslmode=disable",
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def make_installation(
    *, authed_user_id: str | None = "U789", bot_access_token: str = "cipher"
) -> SlackInstallation:
    return SlackInstallation(
        id=uuid.uuid4(),
        owner_identity="alice@example.com",
        team_id="T123",
        team_name="Acme",
        bot_user_id="B123",
        authed_user_id=authed_user_id,
        bot_access_token=bot_access_token,
        scope="chat:write",
        installed_at=datetime.now(UTC),
    )


class FakeRepo:
    def __init__(self, installation: SlackInstallation | None) -> None:
        self._installation = installation

    async def get_by_owner(self, owner: str) -> SlackInstallation | None:
        return self._installation


class FakeOAuthService:
    """Stub for token decryption only — no real Fernet involved."""

    def __init__(self, decrypted: str = "xoxb-token", *, raise_on_decrypt: bool = False) -> None:
        self._decrypted = decrypted
        self._raise = raise_on_decrypt

    def decrypt_token(self, ciphertext: str) -> str:
        if self._raise:
            raise SlackOAuthError("Failed to decrypt Slack bot token")
        return self._decrypted


def make_service(
    *,
    installation: SlackInstallation | None,
    settings: Settings | None = None,
    oauth: FakeOAuthService | None = None,
) -> SlackNotificationService:
    service = SlackNotificationService(
        repository=FakeRepo(installation),  # type: ignore[arg-type]
        session=AsyncMock(),
        oauth_service=oauth or FakeOAuthService(),  # type: ignore[arg-type]
    )
    service._settings = settings or make_settings()  # type: ignore[attr-defined]
    return service


def mock_ok_response() -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


# ------------------------------------------------------ channel resolution --


@pytest.mark.asyncio
async def test_explicit_channel_wins_over_authed_user_id() -> None:
    service = make_service(installation=make_installation(authed_user_id="U789"))
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_ok_response())) as post:
        ok = await service.send_message("alice@example.com", "#explicit-channel", [])
    assert ok is True
    sent_channel = post.call_args.kwargs["json"]["channel"]
    assert sent_channel == "#explicit-channel"


@pytest.mark.asyncio
async def test_falls_back_to_authed_user_id_when_no_explicit_channel() -> None:
    service = make_service(installation=make_installation(authed_user_id="U789"))
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_ok_response())) as post:
        ok = await service.send_message("alice@example.com", None, [])
    assert ok is True
    assert post.call_args.kwargs["json"]["channel"] == "U789"


@pytest.mark.asyncio
async def test_falls_back_to_default_channel_when_no_authed_user_id() -> None:
    """Installation predates migration q2l8i5d9e6a7 — authed_user_id is None."""
    service = make_service(
        installation=make_installation(authed_user_id=None),
        settings=make_settings(SLACK_DEFAULT_CHANNEL="general"),
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_ok_response())) as post:
        ok = await service.send_message("alice@example.com", None, [])
    assert ok is True
    assert post.call_args.kwargs["json"]["channel"] == "general"


@pytest.mark.asyncio
async def test_skips_when_nothing_resolves() -> None:
    """No explicit channel, no authed_user_id, empty default -> logged skip,
    never a not_in_channel failure against Slack."""
    service = make_service(
        installation=make_installation(authed_user_id=None),
        settings=make_settings(SLACK_DEFAULT_CHANNEL=""),
    )
    with patch("httpx.AsyncClient.post", new=AsyncMock()) as post:
        ok = await service.send_message("alice@example.com", None, [])
    assert ok is False
    post.assert_not_called()


# ----------------------------------------------------------- failure modes --


@pytest.mark.asyncio
async def test_missing_installation_returns_false() -> None:
    service = make_service(installation=None)
    with patch("httpx.AsyncClient.post", new=AsyncMock()) as post:
        ok = await service.send_message("alice@example.com", "general", [])
    assert ok is False
    post.assert_not_called()


@pytest.mark.asyncio
async def test_empty_owner_identity_returns_false() -> None:
    service = make_service(installation=make_installation())
    with patch("httpx.AsyncClient.post", new=AsyncMock()) as post:
        ok = await service.send_message("", "general", [])
    assert ok is False
    post.assert_not_called()


@pytest.mark.asyncio
async def test_decrypt_failure_returns_false_never_raises() -> None:
    service = make_service(
        installation=make_installation(),
        oauth=FakeOAuthService(raise_on_decrypt=True),
    )
    ok = await service.send_message("alice@example.com", "general", [])
    assert ok is False


@pytest.mark.asyncio
async def test_slack_http_4xx_returns_false() -> None:
    service = make_service(installation=make_installation())
    resp = httpx.Response(403, text="Forbidden")
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)):
        ok = await service.send_message("alice@example.com", "general", [])
    assert ok is False


@pytest.mark.asyncio
async def test_slack_ok_false_returns_false() -> None:
    service = make_service(installation=make_installation())
    resp = httpx.Response(200, json={"ok": False, "error": "not_in_channel"})
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)):
        ok = await service.send_message("alice@example.com", "#some-channel", [])
    assert ok is False


@pytest.mark.asyncio
async def test_slack_invalid_json_returns_false() -> None:
    service = make_service(installation=make_installation())
    resp = httpx.Response(200, content=b"not json")
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)):
        ok = await service.send_message("alice@example.com", "general", [])
    assert ok is False


@pytest.mark.asyncio
async def test_network_error_returns_false_never_raises() -> None:
    service = make_service(installation=make_installation())
    with patch(
        "httpx.AsyncClient.post",
        new=AsyncMock(side_effect=httpx.ConnectError("connection refused")),
    ):
        ok = await service.send_message("alice@example.com", "general", [])
    assert ok is False


# --------------------------------------------------------- public dispatch --


@pytest.mark.asyncio
async def test_send_shadow_started_dispatches_with_no_explicit_channel() -> None:
    """Public dispatch methods default channel=None — resolution happens in
    send_message, DMing the installer rather than posting to a hardcoded
    channel."""
    service = make_service(installation=make_installation(authed_user_id="U789"))
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_ok_response())) as post:
        ok = await service.send_shadow_started(
            owner_identity="alice@example.com",
            run_id=uuid.uuid4(),
            migration_name="ADD COLUMN demo_flag",
            status="running",
            timestamp=datetime.now(UTC),
            description="Step Functions execution started.",
        )
    assert ok is True
    assert post.call_args.kwargs["json"]["channel"] == "U789"
