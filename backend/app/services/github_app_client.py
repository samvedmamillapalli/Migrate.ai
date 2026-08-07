"""GitHub App REST API client — docs/FUTURE_GITHUB_INTEGRATION_PLAN.md.

A GitHub App authenticates in two steps: sign a short-lived JWT with the
App's RSA private key (proves "I am App #N"), then exchange that JWT for a
per-installation access token (proves "I am specifically installed on this
repo, with these permissions"). Every REST call below uses the installation
token, never the JWT directly — the JWT is only ever used for the token
exchange itself.

No client-side retry/backoff: every caller here is either a webhook handler
(best-effort, matching the Slack notification posture) or the terminal-state
hook, both of which already log-and-swallow failures rather than blocking
the pipeline on GitHub's API being briefly unavailable.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import jwt

from app.core.exceptions import GithubApiError
from app.core.logging import get_logger

logger = get_logger(__name__)

_GITHUB_ACCEPT_HEADER = "application/vnd.github+json"
_API_VERSION_HEADER = "2022-11-28"
_HTTP_TIMEOUT_SECONDS = 20.0
# GitHub caps App JWTs at 10 minutes; stay comfortably under it to absorb
# clock skew between this host and GitHub's.
_APP_JWT_TTL_SECONDS = 540


def build_app_jwt(app_id: str, private_key_pem: str) -> str:
    """Sign a short-lived RS256 JWT identifying this GitHub App.

    ``iat`` is backdated by 60s, matching GitHub's own documented guidance,
    to tolerate the signing host's clock running slightly ahead of GitHub's.
    """
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + _APP_JWT_TTL_SECONDS,
        "iss": app_id,
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


class GithubAppClient:
    """Thin wrapper over the GitHub REST API for one App's installations.

    Constructed fresh per webhook / notification call (no shared connection
    pool), matching ``SlackNotificationService.send_message``'s per-call
    ``httpx.AsyncClient`` convention in this codebase.
    """

    def __init__(self, *, app_id: str, private_key_pem: str, api_base_url: str) -> None:
        self._app_id = app_id
        self._private_key_pem = private_key_pem
        self._api_base_url = api_base_url.rstrip("/")

    async def get_installation_token(self, installation_id: int) -> str:
        app_jwt = build_app_jwt(self._app_id, self._private_key_pem)
        url = f"{self._api_base_url}/app/installations/{installation_id}/access_tokens"
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, headers=self._app_headers(app_jwt))
        if resp.status_code >= 300:
            raise GithubApiError(
                f"Failed to mint installation token for installation "
                f"{installation_id}: HTTP {resp.status_code} {resp.text[:300]}"
            )
        data = resp.json()
        token = data.get("token")
        if not token:
            raise GithubApiError("Installation token response missing 'token'")
        return str(token)

    async def get_repo_installation_id(self, repo_full_name: str) -> int | None:
        """Which installation (if any) grants this App access to ``repo_full_name``.

        Returns ``None`` when the App is not installed on that repo — GitHub
        answers 404 both for "repo doesn't exist" and "App can't see it",
        and deliberately does not distinguish the two (revealing which
        private repos exist would be an information leak). Callers should
        surface both as "install the App on this repo."

        Used to validate a repo link the moment a user enters it, instead of
        letting a mistyped or un-installed repo save cleanly and then
        silently never fire a webhook.
        """
        app_jwt = build_app_jwt(self._app_id, self._private_key_pem)
        url = f"{self._api_base_url}/repos/{repo_full_name}/installation"
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, headers=self._app_headers(app_jwt))
        if resp.status_code == 404:
            return None
        if resp.status_code >= 300:
            raise GithubApiError(
                f"Failed to look up installation for {repo_full_name}: "
                f"HTTP {resp.status_code} {resp.text[:300]}"
            )
        return int(resp.json()["id"])

    async def get_app_slug(self) -> str | None:
        """The App's URL slug, used to build its public install link.

        Best-effort: returns ``None`` on any failure, since this only drives
        a convenience link in the UI and must never break a settings page.
        """
        app_jwt = build_app_jwt(self._app_id, self._private_key_pem)
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                resp = await client.get(
                    f"{self._api_base_url}/app", headers=self._app_headers(app_jwt)
                )
            if resp.status_code >= 300:
                return None
            return resp.json().get("slug")
        except Exception:  # noqa: BLE001 - convenience lookup only
            logger.warning("Could not fetch GitHub App slug", exc_info=True)
            return None

    async def list_pull_request_files(
        self, token: str, repo_full_name: str, pr_number: int
    ) -> list[str]:
        """Repo-relative paths of every file changed in the PR (all pages)."""
        paths: list[str] = []
        page = 1
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            while True:
                url = (
                    f"{self._api_base_url}/repos/{repo_full_name}/pulls/"
                    f"{pr_number}/files"
                )
                resp = await client.get(
                    url,
                    headers=self._installation_headers(token),
                    params={"per_page": 100, "page": page},
                )
                if resp.status_code >= 300:
                    raise GithubApiError(
                        f"Failed to list PR files for {repo_full_name}#{pr_number}: "
                        f"HTTP {resp.status_code} {resp.text[:300]}"
                    )
                batch = resp.json()
                if not batch:
                    break
                paths.extend(str(item["filename"]) for item in batch)
                if len(batch) < 100:
                    break
                page += 1
        return paths

    async def get_file_content(
        self, token: str, repo_full_name: str, path: str, ref: str
    ) -> str:
        """Fetch one file's text content at a given ref (base64-decoded)."""
        import base64

        url = f"{self._api_base_url}/repos/{repo_full_name}/contents/{path}"
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.get(
                url,
                headers=self._installation_headers(token),
                params={"ref": ref},
            )
        if resp.status_code >= 300:
            raise GithubApiError(
                f"Failed to fetch {path}@{ref} in {repo_full_name}: "
                f"HTTP {resp.status_code} {resp.text[:300]}"
            )
        data = resp.json()
        encoded = data.get("content")
        if not encoded or data.get("encoding") != "base64":
            raise GithubApiError(f"Unexpected content response shape for {path}")
        return base64.b64decode(encoded).decode("utf-8", errors="replace")

    async def post_issue_comment(
        self, token: str, repo_full_name: str, pr_number: int, body: str
    ) -> int:
        """PR comments live under the Issues API (a PR *is* an issue)."""
        url = f"{self._api_base_url}/repos/{repo_full_name}/issues/{pr_number}/comments"
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                url,
                headers=self._installation_headers(token),
                json={"body": body},
            )
        if resp.status_code >= 300:
            raise GithubApiError(
                f"Failed to post PR comment on {repo_full_name}#{pr_number}: "
                f"HTTP {resp.status_code} {resp.text[:300]}"
            )
        return int(resp.json()["id"])

    async def create_check_run(
        self,
        token: str,
        repo_full_name: str,
        *,
        name: str,
        head_sha: str,
        status: str,
        conclusion: str | None = None,
        title: str,
        summary: str,
    ) -> int:
        """Create a check run. ``conclusion`` is required when ``status='completed'``."""
        url = f"{self._api_base_url}/repos/{repo_full_name}/check-runs"
        payload: dict[str, Any] = {
            "name": name,
            "head_sha": head_sha,
            "status": status,
            "output": {"title": title, "summary": summary},
        }
        if conclusion is not None:
            payload["conclusion"] = conclusion
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                url, headers=self._installation_headers(token), json=payload
            )
        if resp.status_code >= 300:
            raise GithubApiError(
                f"Failed to create check run on {repo_full_name}@{head_sha}: "
                f"HTTP {resp.status_code} {resp.text[:300]}"
            )
        return int(resp.json()["id"])

    async def update_check_run(
        self,
        token: str,
        repo_full_name: str,
        check_run_id: int,
        *,
        status: str,
        conclusion: str | None,
        title: str,
        summary: str,
    ) -> None:
        url = f"{self._api_base_url}/repos/{repo_full_name}/check-runs/{check_run_id}"
        payload: dict[str, Any] = {
            "status": status,
            "output": {"title": title, "summary": summary},
        }
        if conclusion is not None:
            payload["conclusion"] = conclusion
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            resp = await client.patch(
                url, headers=self._installation_headers(token), json=payload
            )
        if resp.status_code >= 300:
            raise GithubApiError(
                f"Failed to update check run {check_run_id} on {repo_full_name}: "
                f"HTTP {resp.status_code} {resp.text[:300]}"
            )

    # --- headers -------------------------------------------------------

    def _app_headers(self, app_jwt: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {app_jwt}",
            "Accept": _GITHUB_ACCEPT_HEADER,
            "X-GitHub-Api-Version": _API_VERSION_HEADER,
        }

    def _installation_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": _GITHUB_ACCEPT_HEADER,
            "X-GitHub-Api-Version": _API_VERSION_HEADER,
        }


__all__ = ["GithubAppClient", "build_app_jwt"]
