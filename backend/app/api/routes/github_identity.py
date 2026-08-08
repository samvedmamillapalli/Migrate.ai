"""GitHub OAuth identity HTTP routes — install, callback, status, disconnect.

Mirrors app/api/routes/slack.py's structure exactly. Distinct from
app/api/routes/github.py (the PR-integration webhook receiver) and
app/api/routes/invites.py — this is "who is this GitHub identity" only.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.auth.tenancy import require_session_owner
from app.config import get_settings
from app.core.exceptions import GithubOAuthError, GithubStateError, ValidationError
from app.core.logging import get_logger
from app.dependencies import DbSession
from app.repositories.github_identity_repository import GithubIdentityRepository
from app.schemas.github_identity import (
    GithubIdentityDisconnectResponse,
    GithubIdentityInstallAuthorizeResponse,
    GithubIdentityStatusResponse,
)
from app.services.github_identity_oauth_service import GithubIdentityOAuthService

router = APIRouter(prefix="/api/github", tags=["github-identity"])
logger = get_logger(__name__)


def _get_service(session: DbSession) -> GithubIdentityOAuthService:
    return GithubIdentityOAuthService(
        repository=GithubIdentityRepository(session),
        session=session,
    )


@router.get(
    "/install",
    response_model=GithubIdentityInstallAuthorizeResponse,
    summary="Start GitHub OAuth identity install",
)
async def github_install(
    request: Request,
    session: DbSession,
) -> GithubIdentityInstallAuthorizeResponse:
    """Generate the GitHub OAuth authorize URL for the authenticated user.

    Requires a valid Clerk bearer token. The returned ``authorize_url``
    embeds a signed, TTL-bounded state; the browser must be redirected
    there to begin the OAuth flow.
    """
    owner = require_session_owner(request)
    service = _get_service(session)
    return await service.build_authorize_url(owner)


@router.get(
    "/oauth/callback",
    summary="GitHub OAuth identity callback",
    include_in_schema=True,
)
async def github_oauth_callback(
    request: Request,
    session: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Handle GitHub's OAuth redirect back to the application.

    Public (the browser follows GitHub's redirect with no Authorization
    header) — the signed ``state`` is verified first, and the embedded
    owner identity is used to associate the identity with the correct
    Clerk user. On failure, redirects with ``?github=error``.
    """
    settings = get_settings()
    error_redirect = settings.github_oauth_install_error_redirect
    success_redirect = settings.github_oauth_install_success_redirect

    if error:
        logger.warning("GitHub OAuth returned an error", extra={"error": error})
        return RedirectResponse(url=error_redirect, status_code=302)

    if not code or not state:
        logger.warning("GitHub OAuth callback missing code or state")
        return RedirectResponse(url=error_redirect, status_code=302)

    service = _get_service(session)
    try:
        owner = service.verify_state(state)
    except GithubStateError as exc:
        logger.warning("GitHub OAuth state verification failed", extra={"error": str(exc)})
        return RedirectResponse(url=error_redirect, status_code=302)

    try:
        identity = await service.install(owner_identity=owner, code=code, state=state)
    except (GithubOAuthError, GithubStateError, ValidationError) as exc:
        logger.warning(
            "GitHub OAuth install failed",
            extra={"owner_identity": owner, "error": str(exc)},
        )
        return RedirectResponse(url=error_redirect, status_code=302)
    except Exception:
        logger.exception(
            "Unexpected GitHub OAuth install failure", extra={"owner_identity": owner}
        )
        return RedirectResponse(url=error_redirect, status_code=302)

    logger.info(
        "GitHub identity connected",
        extra={"owner_identity": owner, "github_login": identity.github_login},
    )
    return RedirectResponse(url=success_redirect, status_code=302)


@router.get("/status", response_model=GithubIdentityStatusResponse)
async def github_status(
    request: Request,
    session: DbSession,
) -> GithubIdentityStatusResponse:
    """Return whether GitHub identity is configured and connected for this user."""
    owner = require_session_owner(request)
    service = _get_service(session)
    identity = await service.get_identity(owner)
    return GithubIdentityStatusResponse(
        configured=service.configured,
        connected=identity is not None,
        username=identity.github_login if identity else None,
        avatar_url=identity.avatar_url if identity else None,
    )


@router.post("/disconnect", response_model=GithubIdentityDisconnectResponse)
async def github_disconnect(
    request: Request,
    session: DbSession,
) -> GithubIdentityDisconnectResponse:
    """Remove the GitHub identity for the current user."""
    owner = require_session_owner(request)
    service = _get_service(session)
    await service.disconnect(owner)
    return GithubIdentityDisconnectResponse(connected=False)
