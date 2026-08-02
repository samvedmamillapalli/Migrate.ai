"""Thorough Slack OAuth verification — items 1-4.

Covers:
1. Alembic migration sanity (import, revision-chain head, model alignment)
2. FastAPI route behavior via TestClient (/api/slack/install, /oauth/callback,
   /status, /disconnect) with the real router + DI dependency resolution
3. SlackOAuthService edge cases (state sign/verify, code exchange error paths,
   Fernet encrypt/decrypt roundtrip, production-without-key hard error,
   install upsert / reinstall-updates)
4. SlackNotificationService edge cases (missing installation, empty owner/
   channel, Slack 4xx/5xx, ok:false, invalid JSON, decrypt failure) — all
   return False and never raise.

Uses only mocks/fakes — no live DB, no network I/O.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import importlib
import json
import time
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import errors as errors_module
from app.api.routes import slack as slack_module
from app.config import Settings
from app.core.exceptions import SlackOAuthError, SlackStateError
from app.database.models import SlackInstallation
from app.schemas.slack import SlackInstallAuthorizeResponse
from app.services import slack_oauth_service as sos_module
from app.services.slack_notification_service import SlackNotificationService
from app.services.slack_oauth_service import SlackOAuthService

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(name)


# ------------------------------------------------------------------- fakes --

class FakeRepo:
    """Minimal SlackInstallationRepository stub for service-level tests."""

    def __init__(self, rows: dict[str, SlackInstallation] | None = None) -> None:
        self._rows = dict(rows or {})
        self.created: list[SlackInstallation] = []
        self.updated: list[SlackInstallation] = []

    async def get_by_owner(self, owner: str):
        return self._rows.get(owner)

    async def delete_by_owner(self, owner: str) -> bool:
        if owner in self._rows:
            del self._rows[owner]
            return True
        return False

    async def create(self, entity):
        self.created.append(entity)
        self._rows[entity.owner_identity] = entity
        entity.id = uuid.uuid4()
        entity.created_at = datetime.now(UTC)
        entity.updated_at = datetime.now(UTC)
        return entity

    async def update(self, entity):
        self.updated.append(entity)
        entity.updated_at = datetime.now(UTC)
        return entity


class FakeSession:
    """Stub AsyncSession: commit/rollback/refresh only (no real SQL)."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, entity) -> None:
        pass


class FakeDatabaseManager:
    """Yield a fixed FakeSession for FastAPI's get_db_session dependency."""

    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def session(self):
        yield self._session


class FakeOAuthService:
    """Stub SlackOAuthService for NotificationService tests (decrypt only)."""

    def __init__(self, decrypted: str = "xoxb-token") -> None:
        self._decrypted = decrypted
        self.should_raise = False

    def decrypt_token(self, ciphertext: str) -> str:
        if self.should_raise:
            raise SlackOAuthError("Failed to decrypt Slack bot token")
        return self._decrypted


def make_settings(**overrides) -> Settings:
    """Build Settings with explicit Slack overrides (isolated from real .env)."""
    defaults = dict(
        environment="development",
        slack_client_id="test-client-id",
        slack_client_secret="test-client-secret",
        slack_redirect_uri="http://localhost:3000/api/slack/oauth/callback",
        slack_state_secret="test-state-secret",
        slack_state_ttl_seconds=600,
        slack_bot_scope="chat:write",
        slack_install_success_redirect="/dashboard/settings?slack=connected",
        slack_install_error_redirect="/dashboard/settings?slack=error",
        slack_token_encryption_key=None,
        database_url="postgresql://root@localhost:26257/migration_oracle?sslmode=disable",
        def __init__(self):
            self.values = dict(state_data)

        def __getattr__(self, item):
            return self.values.get(item)

