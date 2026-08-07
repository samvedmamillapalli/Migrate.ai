"""GitHub App setup/status helpers shared by the workspace routes and the
integration-status endpoint — docs/GITHUB_APP_SETUP.md.

The point of this module is to turn the two silent-failure modes of the PR
integration into things a user is actually told about, at the moment they'd
act on them:

1. The backend has no GitHub App configured at all (no env vars) — linking
   a repo can never work, so say so instead of accepting the input.
2. The App is configured, but the user has not installed it on the repo they
   just typed — GitHub will never send a webhook for it. Without this check
   the repo saves cleanly and then nothing ever happens, with no error
   anywhere the user can see.
"""

from __future__ import annotations

from app.config import Settings, get_settings
from app.core.exceptions import GithubApiError, ValidationError
from app.core.logging import get_logger
from app.services.github_app_client import GithubAppClient

logger = get_logger(__name__)


def github_app_configured(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    private_key = (
        s.github_app_private_key.get_secret_value()
        if s.github_app_private_key
        else ""
    )
    return bool((s.github_app_id or "").strip() and private_key.strip())


def build_github_client(settings: Settings | None = None) -> GithubAppClient | None:
    s = settings or get_settings()
    if not github_app_configured(s):
        return None
    return GithubAppClient(
        app_id=(s.github_app_id or "").strip(),
        private_key_pem=s.github_app_private_key.get_secret_value(),  # type: ignore[union-attr]
        api_base_url=s.github_api_base_url,
    )


def install_url(app_slug: str | None) -> str | None:
    """Public "install this App on your repos" page. ``None`` when the slug
    isn't known (App not configured, or the lookup failed)."""
    if not app_slug:
        return None
    return f"https://github.com/apps/{app_slug}/installations/new"


async def assert_repo_installed(repo_full_name: str) -> None:
    """Reject a repo link when the GitHub App can't actually see the repo.

    Raises ``ValidationError`` with a message that tells the user exactly
    what to do next (including the install link when we can build one).

    GitHub returns 404 both for "no such repo" and "App not installed here"
    and deliberately doesn't distinguish them, so the message covers both.
    A transient GitHub outage is deliberately *not* fatal — we let the link
    save rather than blocking a user on GitHub being briefly unreachable,
    since the webhook path re-resolves the installation on every event
    anyway.
    """
    client = build_github_client()
    if client is None:
        raise ValidationError(
            "This server has no GitHub App configured, so a repository "
            "cannot be linked yet. Set GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY "
            "and GITHUB_WEBHOOK_SECRET — see docs/GITHUB_APP_SETUP.md."
        )

    try:
        installation_id = await client.get_repo_installation_id(repo_full_name)
    except GithubApiError:
        logger.warning(
            "Could not verify GitHub App installation; allowing the link anyway",
            extra={"repo_full_name": repo_full_name},
            exc_info=True,
        )
        return

    if installation_id is None:
        slug = await client.get_app_slug()
        url = install_url(slug)
        hint = f" Install it here: {url}" if url else ""
        raise ValidationError(
            f"The Migration Oracle GitHub App is not installed on "
            f"{repo_full_name!r} (or that repository doesn't exist). Install "
            f"the App on that repository, then link it here.{hint}"
        )


__all__ = [
    "assert_repo_installed",
    "build_github_client",
    "github_app_configured",
    "install_url",
]
