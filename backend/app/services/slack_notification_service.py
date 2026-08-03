"""Best-effort Slack notifications for Migration Oracle lifecycle events.

Sends Slack messages via ``chat.postMessage`` using the authenticated
user's stored Slack installation. Every method is deliberately fire-and-forget:
any lookup, token-decryption, network, or Slack API failure is logged and
returned as ``False`` so notification issues never affect the caller.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.logging import get_logger
from app.repositories.slack_installation_repository import SlackInstallationRepository
from app.services.slack_oauth_service import SlackOAuthService

logger = get_logger(__name__)

_SLACK_CHAT_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
_HTTP_TIMEOUT_SECONDS = 30.0

# --- Centralized Slack Block Kit formatting ---------------------------------

# Slack emoji + header text for each notification type.
_NOTIFICATION_TITLES: dict[str, tuple[str, str]] = {
    "prediction_ready": (":sparkles:", "Prediction Ready"),
    "shadow_started": (":rocket:", "Shadow Migration Started"),
    "shadow_completed": (":white_check_mark:", "Shadow Migration Completed"),
    "shadow_failed": (":x:", "Shadow Migration Failed"),
}


class SlackNotificationService:
    """Send best-effort Slack notifications to the authenticated user's workspace.

    The service reuses the injected ``SlackOAuthService`` for token decryption
    so the Fernet key handling stays in one place. It does **not** own any
    transactions or database writes — the repository is read-only here.
    """

    def __init__(
        self,
        repository: SlackInstallationRepository,
        session: AsyncSession,
        oauth_service: SlackOAuthService,
    ) -> None:
        self._repository = repository
        self._session = session
        self._oauth_service = oauth_service
        self._settings = get_settings()

    # --- Public notification helpers ------------------------------------------

    async def send_prediction_ready(
        self,
        *,
        owner_identity: str,
        channel: str | None = None,
        run_id: uuid.UUID,
        migration_name: str,
        status: str,
        timestamp: datetime,
        description: str,
    ) -> bool:
        """Notify the user that the AI prediction for a migration is ready."""
        return await self._dispatch(
            owner_identity=owner_identity,
            channel=channel,
            notification_key="prediction_ready",
            run_id=run_id,
            migration_name=migration_name,
            status=status,
            timestamp=timestamp,
            description=description,
        )

    async def send_shadow_started(
        self,
        *,
        owner_identity: str,
        channel: str | None = None,
        run_id: uuid.UUID,
        migration_name: str,
        status: str,
        timestamp: datetime,
        description: str,
    ) -> bool:
        """Notify the user that a shadow migration has started."""
        return await self._dispatch(
            owner_identity=owner_identity,
            channel=channel,
            notification_key="shadow_started",
            run_id=run_id,
            migration_name=migration_name,
            status=status,
            timestamp=timestamp,
            description=description,
        )

    async def send_shadow_completed(
        self,
        *,
        owner_identity: str,
        channel: str | None = None,
        run_id: uuid.UUID,
        migration_name: str,
        status: str,
        timestamp: datetime,
        description: str,
    ) -> bool:
        """Notify the user that a shadow migration completed successfully."""
        return await self._dispatch(
            owner_identity=owner_identity,
            channel=channel,
            notification_key="shadow_completed",
            run_id=run_id,
            migration_name=migration_name,
            status=status,
            timestamp=timestamp,
            description=description,
        )

    async def send_shadow_failed(
        self,
        *,
        owner_identity: str,
        channel: str | None = None,
        run_id: uuid.UUID,
        migration_name: str,
        status: str,
        timestamp: datetime,
        description: str,
    ) -> bool:
        """Notify the user that a shadow migration failed."""
        return await self._dispatch(
            owner_identity=owner_identity,
            channel=channel,
            notification_key="shadow_failed",
            run_id=run_id,
            migration_name=migration_name,
            status=status,
            timestamp=timestamp,
            description=description,
        )

    # --- Shared dispatch -------------------------------------------------------

    async def send_message(
        self,
        owner_identity: str,
        channel: str | None,
        blocks: list[dict[str, Any]],
    ) -> bool:
        """Look up the installation, resolve a channel, decrypt the bot
        token, and post to Slack.

        Channel resolution, in order: an explicit ``channel`` argument; the
        Slack user ID of whoever completed the OAuth install
        (``installation.authed_user_id`` — a DM, requiring only the
        ``chat:write`` scope already requested); ``SLACK_DEFAULT_CHANNEL`` as
        a last resort for installations that predate the ``authed_user_id``
        column. A named channel the bot hasn't joined fails with
        ``not_in_channel`` — DMing the installer avoids that failure mode
        entirely, which is why it's preferred over the env-var default.

        Best-effort: never raises. Returns ``True`` when Slack acknowledged
        the message; ``False`` for any failure (missing installation, no
        resolvable channel, bad token, network error, Slack API error).
        """
        try:
            owner = (owner_identity or "").strip()
            if not owner:
                logger.warning("Slack notification skipped: owner_identity is empty")
                return False

            installation = await self._repository.get_by_owner(owner)
            if installation is None:
                logger.info(
                    "Slack notification skipped: no Slack installation for owner",
                    extra={"owner_identity": owner},
                )
                return False

            resolved_channel = (
                (channel or "").strip()
                or (installation.authed_user_id or "").strip()
                or (self._settings.slack_default_channel or "").strip()
            )
            if not resolved_channel:
                logger.warning(
                    "Slack notification skipped: no channel could be resolved "
                    "(no explicit channel, no authed_user_id on the "
                    "installation, no SLACK_DEFAULT_CHANNEL configured)",
                    extra={"owner_identity": owner, "team_id": installation.team_id},
                )
                return False

            token = self._oauth_service.decrypt_token(
                installation.bot_access_token
            )
            if not token:
                logger.warning(
                    "Slack notification skipped: decrypted bot token is empty",
                    extra={"owner_identity": owner, "team_id": installation.team_id},
                )
                return False

            payload = {
                "channel": resolved_channel,
                "blocks": blocks,
            }
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            }

            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    _SLACK_CHAT_POST_MESSAGE_URL,
                    json=payload,
                    headers=headers,
                )

            if resp.status_code >= 400:
                logger.warning(
                    "Slack chat.postMessage failed with HTTP status",
                    extra={
                        "owner_identity": owner,
                        "team_id": installation.team_id,
                        "http_status": resp.status_code,
                        "body": resp.text[:500],
                    },
                )
                return False

            try:
                data = resp.json()
            except ValueError:
                logger.warning(
                    "Slack chat.postMessage returned invalid JSON",
                    extra={
                        "owner_identity": owner,
                        "team_id": installation.team_id,
                        "body": resp.text[:500],
                    },
                )
                return False

            if not data.get("ok"):
                error = str(data.get("error") or "unknown_error")
                logger.warning(
                    "Slack chat.postMessage returned error",
                    extra={
                        "owner_identity": owner,
                        "team_id": installation.team_id,
                        "error": error,
                    },
                )
                return False

            logger.info(
                "Slack notification sent",
                extra={
                    "owner_identity": owner,
                    "team_id": installation.team_id,
                    "channel": resolved_channel,
                },
            )
            return True

        except Exception:  # noqa: BLE001 - best-effort notifications must not raise
            logger.warning(
                "Slack notification failed",
                extra={
                    "owner_identity": (owner_identity or "").strip(),
                    "channel": (channel or "").strip(),
                },
                exc_info=True,
            )
            return False

    # --- Private helpers ---------------------------------------------------------

    async def _dispatch(
        self,
        *,
        owner_identity: str,
        channel: str | None = None,
        notification_key: str,
        run_id: uuid.UUID,
        migration_name: str,
        status: str,
        timestamp: datetime,
        description: str,
    ) -> bool:
        """Build blocks from centralized formatting and delegate to send_message."""
        title_info = _NOTIFICATION_TITLES.get(notification_key)
        if title_info is None:
            logger.warning(
                "Unknown Slack notification type",
                extra={"notification_key": notification_key},
            )
            return False
        emoji, title = title_info

        blocks = self._build_message_blocks(
            emoji=emoji,
            title=title,
            run_id=run_id,
            migration_name=migration_name,
            status=status,
            timestamp=timestamp,
            description=description,
        )
        return await self.send_message(owner_identity, channel, blocks)

    def _build_message_blocks(
        self,
        *,
        emoji: str,
        title: str,
        run_id: uuid.UUID,
        migration_name: str,
        status: str,
        timestamp: datetime,
        description: str,
    ) -> list[dict[str, Any]]:
        """Build the canonical Slack Block Kit payload for a migration notification.

        Every notification uses this exact layout so formatting stays
        consistent and future notification types only need a title + emoji.
        """
        run_id_str = str(run_id)
        migration = (migration_name or "").strip() or "Untitled migration"
        safe_description = (description or "").strip() or "No details provided."

        frontend = (self._settings.frontend_url or "").rstrip("/")
        migration_url = (
            f"{frontend}/dashboard/migrations/{run_id_str}"
            if frontend
            else ""
        )

        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {title}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Migration:*\n{migration}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Run ID:*\n`{run_id_str}`",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Status:*\n{status or 'unknown'}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"*Timestamp:*\n"
                            f"{timestamp.isoformat() if hasattr(timestamp, 'isoformat') else timestamp}"
                        ),
                    },
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": safe_description,
                },
            },
        ]

        if migration_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Open in Migration Oracle",
                                "emoji": True,
                            },
                            "url": migration_url,
                            "action_id": f"open_migration_{run_id_str}",
                        }
                    ],
                }
            )

        return blocks


__all__ = ["SlackNotificationService"]
