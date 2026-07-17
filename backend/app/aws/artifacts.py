"""S3 artifact store for workflow outputs.

Keys are deterministic per run/artifact type so uploads are idempotent
(skip when the object already exists with the same content hash).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from app.aws.clients import AwsClientFactory
from app.aws.config import AwsSettings
from app.aws.exceptions import AwsConfigurationError, AwsError
from app.core.logging import get_logger

logger = get_logger(__name__)

_CONTENT_HASH_METADATA_KEY = "migration-oracle-content-sha256"


class ArtifactStoreError(AwsError):
    """Raised when S3 artifact operations fail."""


class ArtifactStore:
    """Upload/download workflow artifacts under ``runs/{run_id}/...``."""

    def __init__(
        self,
        factory: AwsClientFactory,
        settings: AwsSettings | None = None,
    ) -> None:
        self._factory = factory
        self._settings = settings or factory.settings

    @property
    def bucket(self) -> str:
        bucket = self._settings.run_artifacts_bucket
        if not bucket:
            raise AwsConfigurationError("RUN_ARTIFACTS_BUCKET is required for artifacts")
        return bucket

    def _client(self):
        return self._factory.s3()

    @staticmethod
    def schema_snapshot_key(run_id: str) -> str:
        return f"runs/{run_id}/schema_snapshot.json"

    @staticmethod
    def execution_report_key(run_id: str) -> str:
        return f"runs/{run_id}/execution_report.json"

    @staticmethod
    def step_output_key(run_id: str, step_name: str) -> str:
        safe = step_name.strip().replace("/", "-")
        return f"runs/{run_id}/steps/{safe}.json"

    @staticmethod
    def _fingerprint(body: bytes) -> str:
        return hashlib.sha256(body).hexdigest()

    def _head(self, key: str) -> dict[str, Any] | None:
        try:
            return self._client().head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise

    def put_bytes_sync(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
        run_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        fingerprint = self._fingerprint(body)
        existing = self._head(key)
        if existing is not None:
            existing_meta = {
                str(k).lower(): str(v)
                for k, v in (existing.get("Metadata") or {}).items()
            }
            if existing_meta.get(_CONTENT_HASH_METADATA_KEY) == fingerprint:
                logger.info(
                    "S3 artifact unchanged; skipping upload",
                    extra={
                        "bucket": self.bucket,
                        "key": key,
                        "run_id": run_id,
                        "bytes": len(body),
                    },
                )
                return {
                    "bucket": self.bucket,
                    "key": key,
                    "uri": f"s3://{self.bucket}/{key}",
                    "bytes": len(body),
                    "content_sha256": fingerprint,
                    "uploaded": False,
                }

        meta = {**(metadata or {}), _CONTENT_HASH_METADATA_KEY: fingerprint}
        if run_id:
            meta["run_id"] = run_id
        try:
            self._client().put_object(
                Bucket=self.bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                Metadata=meta,
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise ArtifactStoreError(
                f"Unable to upload s3://{self.bucket}/{key}"
            ) from exc

        logger.info(
            "Uploaded S3 artifact",
            extra={
                "bucket": self.bucket,
                "key": key,
                "run_id": run_id,
                "bytes": len(body),
                "uploaded": True,
            },
        )
        return {
            "bucket": self.bucket,
            "key": key,
            "uri": f"s3://{self.bucket}/{key}",
            "bytes": len(body),
            "content_sha256": fingerprint,
            "uploaded": True,
        }

    async def put_bytes(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
        run_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.put_bytes_sync,
            key,
            body,
            content_type=content_type,
            run_id=run_id,
            metadata=metadata,
        )

    async def put_json(
        self,
        key: str,
        payload: dict[str, Any] | list[Any],
        *,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        return await self.put_bytes(
            key,
            body,
            content_type="application/json",
            run_id=run_id,
        )

    def get_bytes_sync(self, key: str) -> bytes:
        try:
            response = self._client().get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            raise ArtifactStoreError(
                f"Unable to download s3://{self.bucket}/{key} ({code})"
            ) from exc
        except (BotoCoreError, OSError) as exc:
            raise ArtifactStoreError(
                f"Unable to download s3://{self.bucket}/{key}"
            ) from exc

    async def get_bytes(self, key: str) -> bytes:
        return await asyncio.to_thread(self.get_bytes_sync, key)

    async def get_json(self, key: str) -> Any:
        raw = await self.get_bytes(key)
        return json.loads(raw.decode("utf-8"))

    async def put_schema_snapshot(
        self,
        run_id: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.put_json(
            self.schema_snapshot_key(run_id),
            snapshot,
            run_id=run_id,
        )

    async def put_execution_report(
        self,
        run_id: str,
        report: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.put_json(
            self.execution_report_key(run_id),
            report,
            run_id=run_id,
        )

    async def put_step_output(
        self,
        run_id: str,
        step_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.put_json(
            self.step_output_key(run_id, step_name),
            payload,
            run_id=run_id,
        )
