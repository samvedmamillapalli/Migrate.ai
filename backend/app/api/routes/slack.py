"""Slack OAuth HTTP routes — install, callback, status, disconnect."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.auth.tenancy import require_session_owner
from app.config import get_settings
from app.core.exceptions import SlackOAuthError, SlackStateError, ValidationError
from app.core.logging import get_logger
from app.dependencies import DbSession
from app.repositories.slack_installation_repository import SlackInstallationRepository
from app.schemas.slack import (
    SlackDisconnectResponse,
    SlackInstallAuthorizeResponse,
    SlackStatusResponse,
)
from app.services.slack_oauth_service import SlackOAuthService

router = APIRouter(prefix="/api/slack", tags=["slack"])
logger = get_logger(__name__)


def _get_slack_service(session: DbSession) -> SlackOAuthService:
    return SlackOAuthService(
        repository=SlackInstallationRepository(session),
        session=session,
    )


@router.get(
    "/install",
    response_model=SlackInstallAuthorizeResponse,
    summary="Start Slack OAuth installation",
)
async def slack_install(
    request: Request,
    session: DbSession,
) -> SlackInstallAuthorizeResponse:
    """Generate the Slack OAuth authorize URL for the authenticated user.

    Requires a valid Clerk bearer token. The returned ``state`` is signed and
    TTL-bounded; the browser must be redirected to ``authorize_url`` to begin
    the OAuth flow.
    """
    owner = require_session_owner(request)
    service = _get_slack_service(session)
    return await service.build_authorize_url(owner)


@router.get(
    "/oauth/callback",
    summary="Slack OAuth callback",
    include_in_schema=True,
)
async def slack_oauth_callback(
    request: Request,
    session: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """Handle Slack's OAuth redirect back to the application.

    This route is public (the browser follows Slack's redirect with no
    Authorization header). The signed ``state`` is verified first, and the
    embedded owner identity is used to associate the installation with the
    correct Clerk user. On failure, the browser is redirected to the
    configured error URL with ``?slack=error``.
    """
    settings = get_settings()
    error_redirect = settings.slack_install_error_redirect
    success_redirect = settings.slack_install_success_redirect

    if error:
        logger.warning(
            "Slack authorization returned an error",
            extra={"error": error},
        )
        return RedirectResponse(url=error_redirect, status_code=302)

    if not code or not state:
        logger.warning("Slack OAuth callback missing code or state")
        return RedirectResponse(url=error_redirect, status_code=302)

    service = _get_slack_service(session)
    try:
        owner = service.verify_state(state)
    except SlackStateError as exc:
        logger.warning(
            "Slack OAuth state verification failed",
            extra={"error": str(exc)},
        )
        return RedirectResponse(url=error_redirect, status_code=302)

    try:
        installation = await service.install(
            owner_identity=owner,
            code=code,
            state=state,
        )
    except (SlackOAuthError, SlackStateError, ValidationError) as exc:
        logger.warning(
            "Slack OAuth install failed",
            extra={
                "owner_identity": owner,
                "error": str(exc),
            },
        )
        return RedirectResponse(url=error_redirect, status_code=302)
    except Exception:
        logger.exception(
            "Unexpected Slack OAuth install failure",
            extra={"owner_identity": owner},
        )
        return RedirectResponse(url=error_redirect, status_code=302)

    logger.info(
        "Slack workspace connected",
        extra={
            "owner_identity": owner,
            "team_id": installation.team_id,
        },
    )
    return RedirectResponse(url=success_redirect, status_code=302)


@router.get("/status", response_model=SlackStatusResponse)
async def slack_status(
    request: Request,
    session: DbSession,
) -> SlackStatusResponse:
    """Return whether Slack is configured and connected for this user."""
    owner = require_session_owner(request)
    service = _get_slack_service(session)
    installation = await service.get_installation(owner)
    return SlackStatusResponse(
        configured=service.configured,
        connected=installation is not None,
        team_id=installation.team_id if installation else None,
        team_name=installation.team_name if installation else None,
        scope=installation.scope if installation else None,
    )


@router.post("/disconnect", response_model=SlackDisconnectResponse)
async def slack_disconnect(
    request: Request,
    session: DbSession,
) -> SlackDisconnectResponse:
    """Remove the Slack installation for the current user."""
    owner = require_session_owner(request)
    service = _get_slack_service(session)
    deleted = await service.disconnect(owner)
    return SlackDisconnectResponse(
        disconnected=deleted,
        owner_identity=owner,
    )
