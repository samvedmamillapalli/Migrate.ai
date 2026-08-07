"""GitHub webhook receiver — docs/FUTURE_GITHUB_INTEGRATION_PLAN.md.

Public route (no Bearer token — GitHub authenticates itself via
``X-Hub-Signature-256``, see ``_PUBLIC_PREFIXES`` in
``app/api/middleware_auth.py``). Processes synchronously, same posture as
``POST /runs/{id}/predict`` elsewhere in this app (also a direct Bedrock
call with no background task queue) — a webhook response can take a few
seconds while discover + predict run; GitHub tolerates this well under its
webhook timeout for a single migration file.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Request, Response, status
from pydantic import BaseModel

from app.config import get_settings
from app.core.exceptions import GithubWebhookError
from app.core.logging import get_logger
from app.services.github_setup import build_github_client, github_app_configured, install_url
from app.services.github_webhook_service import verify_webhook_signature

router = APIRouter(prefix="/webhooks/github", tags=["github"])
logger = get_logger(__name__)


class GithubIntegrationStatus(BaseModel):
    """Drives the workspace-settings panel's GitHub section, so the UI can
    tell a user to install the App instead of silently accepting a repo
    name that will never produce a webhook."""

    configured: bool
    webhook_secret_set: bool
    app_slug: str | None = None
    install_url: str | None = None


@router.get("/status", response_model=GithubIntegrationStatus)
async def github_integration_status() -> GithubIntegrationStatus:
    """Whether this server can do GitHub PR integration at all, plus the
    App's public install link. Public-safe: exposes no credentials, only
    whether they are present and the App's already-public slug."""
    settings = get_settings()
    configured = github_app_configured(settings)
    slug: str | None = None
    if configured:
        client = build_github_client(settings)
        if client is not None:
            slug = await client.get_app_slug()
    return GithubIntegrationStatus(
        configured=configured,
        webhook_secret_set=bool(settings.github_webhook_secret),
        app_slug=slug,
        install_url=install_url(slug),
    )


async def _process_pull_request_event(request: Request, payload: dict) -> None:
    """Run the real pipeline after the webhook response has already been sent.

    Opens its own database session: the request-scoped one from
    ``get_db_session`` is closed as soon as the response is returned, which
    is precisely what happens before this runs.

    Swallows everything. There is nobody left to return an error to — the
    HTTP response went out long ago — so a failure here must surface in
    logs, never as an unhandled task exception.
    """
    import contextlib

    from app.database.session import DatabaseSessionManager
    from app.dependencies import build_github_webhook_service_for_session

    repo = (payload.get("repository") or {}).get("full_name")
    pr_number = (payload.get("pull_request") or {}).get("number")
    try:
        database: DatabaseSessionManager = request.app.state.database
        async with contextlib.aclosing(database.session()) as gen:
            session = await gen.__anext__()
            service = build_github_webhook_service_for_session(request, session)
            run = await service.handle_pull_request_event(request, payload)
        logger.info(
            "GitHub webhook processed",
            extra={
                "repo_full_name": repo,
                "pr_number": pr_number,
                "run_id": str(run.id) if run is not None else None,
                "outcome": "run_created" if run is not None else "no_op",
            },
        )
    except Exception:  # noqa: BLE001 - background task must never raise
        logger.exception(
            "GitHub webhook background processing failed",
            extra={"repo_full_name": repo, "pr_number": pr_number},
        )


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def receive_github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """Verify and acknowledge fast; do the real work afterwards.

    GitHub's webhook delivery timeout is **10 seconds**, and this pipeline
    (schema discovery against a real database, then two Bedrock calls)
    routinely takes much longer. Processing inline made GitHub record the
    delivery as failed — "context deadline exceeded" after 10s — even though
    the run was created correctly, which risks GitHub disabling the webhook
    and turns any redelivery into a duplicate run. So: verify the signature
    (cheap, and the security boundary), then hand off and return 202.

    ``GithubWebhookService`` is deliberately *not* injected here — the
    background task builds its own against a fresh session, since the
    request-scoped session is closed by the time it runs.
    """
    body = await request.body()
    settings = get_settings()
    webhook_secret = (
        settings.github_webhook_secret.get_secret_value()
        if settings.github_webhook_secret
        else ""
    )

    try:
        verify_webhook_signature(
            body, request.headers.get("X-Hub-Signature-256"), webhook_secret
        )
    except GithubWebhookError as exc:
        logger.warning("GitHub webhook signature check failed", extra={"error": str(exc)})
        return Response(status_code=status.HTTP_401_UNAUTHORIZED, content=str(exc.message))

    event = request.headers.get("X-GitHub-Event", "")
    if event != "pull_request":
        # `ping` (sent once at App installation) and any other subscribed
        # event this App doesn't act on yet — acknowledge, do nothing.
        logger.info("Ignoring non-pull_request GitHub event", extra={"event": event})
        return Response(status_code=status.HTTP_200_OK, content="ignored")

    try:
        payload = json.loads(body)
    except ValueError:
        return Response(
            status_code=status.HTTP_400_BAD_REQUEST, content="invalid JSON payload"
        )

    background_tasks.add_task(_process_pull_request_event, request, payload)
    return Response(status_code=status.HTTP_202_ACCEPTED, content="accepted")
