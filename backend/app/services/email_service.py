"""Best-effort transactional email via SES — currently just workspace
invites. Mirrors SlackNotificationService's and GithubNotificationService's
posture exactly: every method is fire-and-forget, logs on failure, and
never raises, so a delivery problem can never undo or block the database
record (the invite itself) that already exists.

Requires ``AwsSettings.ses_sender_email`` to be a verified SES sender
identity. In SES sandbox mode (the default for a new AWS account) the
*recipient* must also be verified until the account is moved out of
sandbox — a real, common reason sending fails in dev, logged clearly
rather than surfacing as a generic error.
"""

from __future__ import annotations

import asyncio

from app.aws.clients import AwsClientFactory
from app.aws.config import AwsSettings
from app.core.logging import get_logger
from app.config import get_settings

logger = get_logger(__name__)

_SUBJECT_TEMPLATE = "{inviter} invited you to {workspace} on Migration Oracle"


def _invite_email_body(*, inviter_identity: str, workspace_name: str, accept_url: str) -> str:
    return (
        f"{inviter_identity} invited you to join the '{workspace_name}' "
        f"workspace on Migration Oracle.\n\n"
        f"Accept the invite: {accept_url}\n\n"
        f"This link expires in 14 days."
    )


class EmailService:
    def __init__(self, *, aws_clients: AwsClientFactory, aws_settings: AwsSettings) -> None:
        self._clients = aws_clients
        self._settings = aws_settings

    @property
    def configured(self) -> bool:
        return bool((self._settings.ses_sender_email or "").strip())

    async def send_workspace_invite(
        self,
        *,
        to_email: str,
        inviter_identity: str,
        workspace_name: str,
        token: str,
    ) -> bool:
        if not self.configured:
            logger.info(
                "Skipping invite email — SES_SENDER_EMAIL not configured",
                extra={"to_email": to_email, "workspace_name": workspace_name},
            )
            return False
        if not to_email:
            logger.warning("Skipping invite email — no recipient address")
            return False

        frontend = (get_settings().frontend_url or "").rstrip("/")
        accept_url = f"{frontend}/invite/{token}" if frontend else f"/invite/{token}"
        body = _invite_email_body(
            inviter_identity=inviter_identity,
            workspace_name=workspace_name,
            accept_url=accept_url,
        )
        subject = _SUBJECT_TEMPLATE.format(
            inviter=inviter_identity, workspace=workspace_name
        )

        def _send() -> None:
            client = self._clients.ses()
            client.send_email(
                Source=self._settings.ses_sender_email,  # type: ignore[arg-type]
                Destination={"ToAddresses": [to_email]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                },
            )

        try:
            await asyncio.to_thread(_send)
            logger.info(
                "Sent workspace invite email",
                extra={"to_email": to_email, "workspace_name": workspace_name},
            )
            return True
        except Exception:  # noqa: BLE001 - best-effort, must not raise
            logger.warning(
                "Failed to send workspace invite email (invite record still created)",
                extra={"to_email": to_email, "workspace_name": workspace_name},
                exc_info=True,
            )
            return False


__all__ = ["EmailService"]
