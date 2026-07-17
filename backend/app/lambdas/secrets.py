"""Secret backends for Lambda handlers.

AWS path delegates to ``SecretsService`` (cached, idempotent).
Customer passwords and shadow connection URLs are never logged.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from app.aws.secrets_service import SecretsService
from app.core.logging import get_logger
from app.lambdas.errors import LambdaHandlerError, LambdaValidationError

logger = get_logger(__name__)


class SecretStore(Protocol):
    async def get_json(self, secret_id: str) -> dict[str, Any]: ...

    async def get_string(self, secret_id: str) -> str: ...

    async def put_string(self, name: str, secret_value: str) -> str: ...

    async def put_json(self, name: str, payload: dict[str, Any]) -> str: ...

    async def delete(self, secret_id: str) -> None: ...


class LocalSecretStore:
    """File-backed secret store for local Lambda execution."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or (
            Path(os.environ.get("LAMBDA_LOCAL_SECRETS_DIR", ".local_secrets"))
        )
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, secret_id: str) -> Path:
        safe = secret_id.replace(":", "_").replace("/", "__")
        return self._root / f"{safe}.json"

    async def get_json(self, secret_id: str) -> dict[str, Any]:
        raw = await self.get_string(secret_id)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LambdaValidationError(
                f"Secret {secret_id!r} is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise LambdaValidationError(f"Secret {secret_id!r} must be a JSON object")
        return payload

    async def get_string(self, secret_id: str) -> str:
        path = self._path_for(secret_id)
        if not path.is_file():
            raise LambdaHandlerError(f"Secret not found: {secret_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get("value")
        if not isinstance(value, str):
            raise LambdaValidationError(f"Secret {secret_id!r} missing string value")
        return value

    async def put_string(self, name: str, secret_value: str) -> str:
        secret_id = name if name.startswith("local:") else f"local:{name}"
        path = self._path_for(secret_id)
        if path.is_file():
            existing = json.loads(path.read_text(encoding="utf-8")).get("value")
            if existing == secret_value:
                logger.info(
                    "Local secret unchanged; skipping write",
                    extra={"secret_id": secret_id},
                )
                return secret_id
        path.write_text(
            json.dumps({"value": secret_value}, separators=(",", ":")),
            encoding="utf-8",
        )
        logger.info("Stored local secret", extra={"secret_id": secret_id})
        return secret_id

    async def put_json(self, name: str, payload: dict[str, Any]) -> str:
        return await self.put_string(
            name,
            json.dumps(payload, separators=(",", ":"), sort_keys=True),
        )

    async def delete(self, secret_id: str) -> None:
        path = self._path_for(secret_id)
        if path.is_file():
            path.unlink()
            logger.info("Deleted local secret", extra={"secret_id": secret_id})


class AwsSecretStore:
    """AWS Secrets Manager-backed store with TTL cache and idempotent writes."""

    def __init__(self, service: SecretsService) -> None:
        self._service = service

    async def get_json(self, secret_id: str) -> dict[str, Any]:
        try:
            return await self._service.get_json(secret_id)
        except Exception as exc:  # noqa: BLE001
            raise LambdaHandlerError(str(exc)) from exc

    async def get_string(self, secret_id: str) -> str:
        try:
            return await self._service.get_string(secret_id)
        except Exception as exc:  # noqa: BLE001
            raise LambdaHandlerError(str(exc)) from exc

    async def put_string(self, name: str, secret_value: str) -> str:
        try:
            return await self._service.put_string(name, secret_value)
        except Exception as exc:  # noqa: BLE001
            raise LambdaHandlerError(str(exc)) from exc

    async def put_json(self, name: str, payload: dict[str, Any]) -> str:
        try:
            return await self._service.put_json(name, payload)
        except Exception as exc:  # noqa: BLE001
            raise LambdaHandlerError(str(exc)) from exc

    async def delete(self, secret_id: str) -> None:
        try:
            await self._service.delete(secret_id)
        except Exception as exc:  # noqa: BLE001
            raise LambdaHandlerError(str(exc)) from exc
