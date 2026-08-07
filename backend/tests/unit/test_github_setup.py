"""GitHub App setup/validation helpers — app/services/github_setup.py.

The behavior under test is the thing that turns the PR integration's two
silent-failure modes into visible, actionable errors: linking a repo the
App can't see, and linking a repo when no App is configured at all.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import GithubApiError, ValidationError
from app.services.github_setup import (
    assert_repo_installed,
    github_app_configured,
    install_url,
)


def _settings(*, app_id="123", private_key="key") -> MagicMock:
    s = MagicMock()
    s.github_app_id = app_id
    s.github_app_private_key = (
        MagicMock(get_secret_value=MagicMock(return_value=private_key))
        if private_key is not None
        else None
    )
    s.github_api_base_url = "https://api.github.com"
    return s


# ------------------------------------------------------------ configured


def test_github_app_configured_true_when_both_set() -> None:
    assert github_app_configured(_settings()) is True


def test_github_app_configured_false_when_app_id_missing() -> None:
    assert github_app_configured(_settings(app_id="")) is False


def test_github_app_configured_false_when_private_key_missing() -> None:
    assert github_app_configured(_settings(private_key=None)) is False


def test_github_app_configured_false_when_private_key_blank() -> None:
    assert github_app_configured(_settings(private_key="   ")) is False


# ------------------------------------------------------------ install url


def test_install_url_builds_public_link() -> None:
    assert install_url("migration-oracle") == (
        "https://github.com/apps/migration-oracle/installations/new"
    )


def test_install_url_none_when_slug_unknown() -> None:
    assert install_url(None) is None


# ------------------------------------------------- assert_repo_installed


@pytest.mark.asyncio
async def test_assert_repo_installed_rejects_when_app_not_configured() -> None:
    with patch(
        "app.services.github_setup.build_github_client", return_value=None
    ):
        with pytest.raises(ValidationError) as exc:
            await assert_repo_installed("acme/widgets")
    assert "no GitHub App configured" in str(exc.value.message)


@pytest.mark.asyncio
async def test_assert_repo_installed_passes_when_installation_found() -> None:
    client = MagicMock()
    client.get_repo_installation_id = AsyncMock(return_value=42)
    with patch(
        "app.services.github_setup.build_github_client", return_value=client
    ):
        await assert_repo_installed("acme/widgets")  # must not raise


@pytest.mark.asyncio
async def test_assert_repo_installed_rejects_with_install_link_when_not_installed() -> None:
    """The whole point of the check: a repo the App can't see must fail
    loudly at link time, and the error must tell the user where to go."""
    client = MagicMock()
    client.get_repo_installation_id = AsyncMock(return_value=None)
    client.get_app_slug = AsyncMock(return_value="migration-oracle")
    with patch(
        "app.services.github_setup.build_github_client", return_value=client
    ):
        with pytest.raises(ValidationError) as exc:
            await assert_repo_installed("acme/widgets")
    message = str(exc.value.message)
    assert "not installed" in message
    assert "acme/widgets" in message
    assert "https://github.com/apps/migration-oracle/installations/new" in message


@pytest.mark.asyncio
async def test_assert_repo_installed_still_errors_without_slug() -> None:
    """A failed slug lookup must not swallow the real 'not installed'
    error — the user still needs to be told, just without the link."""
    client = MagicMock()
    client.get_repo_installation_id = AsyncMock(return_value=None)
    client.get_app_slug = AsyncMock(return_value=None)
    with patch(
        "app.services.github_setup.build_github_client", return_value=client
    ):
        with pytest.raises(ValidationError) as exc:
            await assert_repo_installed("acme/widgets")
    assert "not installed" in str(exc.value.message)


@pytest.mark.asyncio
async def test_assert_repo_installed_allows_link_when_github_is_unreachable() -> None:
    """A transient GitHub outage must not block a user from saving a link —
    the webhook path re-resolves the installation on every event anyway."""
    client = MagicMock()
    client.get_repo_installation_id = AsyncMock(
        side_effect=GithubApiError("GitHub is down")
    )
    with patch(
        "app.services.github_setup.build_github_client", return_value=client
    ):
        await assert_repo_installed("acme/widgets")  # must not raise
