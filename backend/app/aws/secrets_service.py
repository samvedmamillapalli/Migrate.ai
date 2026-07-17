"""Cached Secrets Manager access for customer and temporary secrets.

Never logs secret values — only names/ARNs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from app.aws.clients import AwsClientFactory
from app.aws.config import AwsSettings
from app.aws.exceptions import AwsConfigurationError, AwsError
from app.core.logging import get_logger
from app.schema_analysis.database_connection import DatabaseConnection

logger = get_logger(__name__)


class SecretsServiceError(AwsError):
    """Raised when Secrets Manager operations fail."""


@dataclass(frozen=True)
class CachedSecret:
    value: str
    fetched_at: float
    version_id: str | None = None


class SecretsService:
    """Store/retrieve secrets with in-process TTL cache and idempotent creates."""

    def __init__(
        self,
        factory: AwsClientFactory,
        settings: AwsSettings | None = None,
        *,
        cache_ttl_seconds: float = 300.0,
    ) -> None:
        self._factory = factory
        self._settings = settings or factory.settings
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, CachedSecret] = {}
        self._lock = threading.Lock()

    def _client(self):
        return self._factory.secretsmanager()

    def connection_secret_name(self, connection_id: str) -> str:
        prefix = self._settings.user_database_secret_prefix.rstrip("/")
        return f"{prefix}/{connection_id}"

    def shadow_secret_name(self, run_id: str) -> str:
        return f"migration-oracle/shadow/{run_id}"

    def _cache_get(self, secret_id: str) -> str | None:
        with self._lock:
            entry = self._cache.get(secret_id)
            if entry is None:
                return None
            if time.monotonic() - entry.fetched_at > self._cache_ttl_seconds:
                del self._cache[secret_id]
                return None
            return entry.value

    def _cache_put(
        self,
        secret_id: str,
        value: str,
        *,
        version_id: str | None = None,
    ) -> None:
        with self._lock:
            self._cache[secret_id] = CachedSecret(
                value=value,
                fetched_at=time.monotonic(),
                version_id=version_id,
            )

    def _cache_invalidate(self, secret_id: str) -> None:
        with self._lock:
            self._cache.pop(secret_id, None)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def _describe(self, secret_id: str) -> dict[str, Any] | None:
        try:
            return self._client().describe_secret(SecretId=secret_id)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"ResourceNotFoundException", "ResourceNotFound"}:
                return None
            raise

    def _get_secret_string_sync(self, secret_id: str) -> tuple[str, str | None]:
        response = self._client().get_secret_value(SecretId=secret_id)
        value = response.get("SecretString")
        if value is None:
            raise SecretsServiceError(f"Secret {secret_id!r} has no SecretString")
        return str(value), response.get("VersionId")

    def _content_fingerprint(self, secret_value: str) -> str:
        return hashlib.sha256(secret_value.encode("utf-8")).hexdigest()

    def get_string_sync(self, secret_id: str, *, use_cache: bool = True) -> str:
        if use_cache:
            cached = self._cache_get(secret_id)
            if cached is not None:
                logger.info(
                    "Secrets Manager cache hit",
                    extra={"secret_id": secret_id},
                )
                return cached
        try:
            value, version_id = self._get_secret_string_sync(secret_id)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            raise SecretsServiceError(
                f"Unable to read secret {secret_id!r} ({code})"
            ) from exc
        except (BotoCoreError, OSError) as exc:
            raise SecretsServiceError(f"Unable to read secret {secret_id!r}") from exc

        self._cache_put(secret_id, value, version_id=version_id)
        logger.info(
            "Retrieved secret from Secrets Manager",
            extra={"secret_id": secret_id},
        )
        return value

    async def get_string(self, secret_id: str, *, use_cache: bool = True) -> str:
        return await asyncio.to_thread(
            self.get_string_sync,
            secret_id,
            use_cache=use_cache,
        )

    async def get_json(self, secret_id: str, *, use_cache: bool = True) -> dict[str, Any]:
        raw = await self.get_string(secret_id, use_cache=use_cache)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SecretsServiceError(
                f"Secret {secret_id!r} is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise SecretsServiceError(f"Secret {secret_id!r} must be a JSON object")
        return payload

    def put_string_sync(
        self,
        name: str,
        secret_value: str,
        *,
        description: str | None = None,
    ) -> str:
        """Create or update a secret without duplicate create calls.

        If the secret already exists with the same content fingerprint, skips
        the write and returns the existing ARN.
        """
        client = self._client()
        existing = self._describe(name)
        fingerprint = self._content_fingerprint(secret_value)

        if existing is not None:
            arn = str(existing["ARN"])
            try:
                current, _ = self._get_secret_string_sync(arn)
            except SecretsServiceError:
                current = None
            if current is not None and self._content_fingerprint(current) == fingerprint:
                logger.info(
                    "Secret unchanged; skipping write",
                    extra={"secret_name": name, "secret_arn": arn},
                )
                self._cache_put(arn, secret_value)
                self._cache_put(name, secret_value)
                return arn

            try:
                response = client.put_secret_value(
                    SecretId=arn,
                    SecretString=secret_value,
                )
            except (BotoCoreError, ClientError, OSError) as exc:
                raise SecretsServiceError(
                    f"Unable to update secret {name!r}"
                ) from exc
            arn = str(response.get("ARN") or arn)
            self._cache_put(arn, secret_value, version_id=response.get("VersionId"))
            self._cache_put(name, secret_value)
            logger.info(
                "Updated existing secret",
                extra={"secret_name": name, "secret_arn": arn},
            )
            return arn

        kwargs: dict[str, Any] = {"Name": name, "SecretString": secret_value}
        if description:
            kwargs["Description"] = description
        try:
            response = client.create_secret(**kwargs)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code != "ResourceExistsException":
                raise SecretsServiceError(
                    f"Unable to create secret {name!r} ({code})"
                ) from exc
            # Race: another writer created it; update instead.
            return self.put_string_sync(name, secret_value, description=description)
        except (BotoCoreError, OSError) as exc:
            raise SecretsServiceError(f"Unable to create secret {name!r}") from exc

        arn = str(response["ARN"])
        self._cache_put(arn, secret_value, version_id=response.get("VersionId"))
        self._cache_put(name, secret_value)
        logger.info(
            "Created secret",
            extra={"secret_name": name, "secret_arn": arn},
        )
        return arn

    async def put_string(
        self,
        name: str,
        secret_value: str,
        *,
        description: str | None = None,
    ) -> str:
        return await asyncio.to_thread(
            self.put_string_sync,
            name,
            secret_value,
            description=description,
        )

    async def put_json(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        description: str | None = None,
    ) -> str:
        return await self.put_string(
            name,
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
            description=description,
        )

    async def store_customer_connection(
        self,
        connection_id: str,
        connection: DatabaseConnection,
    ) -> str:
        """Persist customer DB credentials. Returns secret ARN (never logs password)."""
        if not connection_id.strip():
            raise AwsConfigurationError("connection_id must not be empty")
        name = self.connection_secret_name(connection_id.strip())
        payload = {
            "host": connection.host,
            "port": connection.port,
            "database": connection.database,
            "username": connection.username,
            "password": connection.password.get_secret_value(),
            "ssl_mode": connection.ssl_mode.value,
        }
        arn = await self.put_json(
            name,
            payload,
            description="Migration Oracle customer database credentials",
        )
        logger.info(
            "Stored customer database credentials",
            extra={
                "connection_id": connection_id,
                "secret_name": name,
                "secret_arn": arn,
                **connection.safe_log_fields(),
            },
        )
        return arn

    async def get_customer_connection(
        self,
        secret_id: str,
    ) -> DatabaseConnection:
        payload = await self.get_json(secret_id)
        return DatabaseConnection.model_validate(payload)

    async def delete(self, secret_id: str) -> None:
        def _delete() -> None:
            self._client().delete_secret(
                SecretId=secret_id,
                ForceDeleteWithoutRecovery=True,
            )

        try:
            await asyncio.to_thread(_delete)
            self._cache_invalidate(secret_id)
            logger.info("Deleted secret", extra={"secret_id": secret_id})
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"ResourceNotFoundException", "InvalidRequestException"}:
                self._cache_invalidate(secret_id)
                return
            raise SecretsServiceError(
                f"Unable to delete secret {secret_id!r} ({code})"
            ) from exc
        except (BotoCoreError, OSError) as exc:
            raise SecretsServiceError(f"Unable to delete secret {secret_id!r}") from exc
