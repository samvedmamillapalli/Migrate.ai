"""Injectable Titan embedding client (Bedrock InvokeModel)."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Sequence

from botocore.exceptions import BotoCoreError, ClientError

from app.aws.config import AwsSettings
from app.aws.exceptions import AwsConfigurationError, AwsError
from app.core.logging import get_logger
from app.memory.constants import EMBEDDING_DIMENSIONS

logger = get_logger(__name__)


class EmbeddingAccessError(AwsError):
    """Raised when Titan embedding access is missing or misconfigured."""


class EmbeddingInvocationError(AwsError):
    """Raised for non-access embedding invocation failures."""


class EmbeddingClient(ABC):
    """Abstract embedding client (injectable for tests)."""

    @abstractmethod
    def embed(self, text: str, *, model_id: str | None = None) -> list[float]:
        """Return a 1024-d embedding vector."""


def vector_to_literal(values: Sequence[float]) -> str:
    """Format a float sequence as a CockroachDB VECTOR literal."""
    return "[" + ",".join(f"{float(v):.8g}" for v in values) + "]"


def parse_vector_literal(value: object) -> list[float]:
    """Parse a VECTOR column value into floats."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [float(v) for v in value]
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if not text:
        return []
    return [float(part.strip()) for part in text.split(",") if part.strip()]


class AwsTitanEmbeddingClient(EmbeddingClient):
    """Live Amazon Titan embeddings via Bedrock InvokeModel."""

    def __init__(
        self,
        *,
        settings: AwsSettings,
        boto3_client: Any | None = None,
    ) -> None:
        self._settings = settings
        model = (settings.bedrock_embedding_model_id or "").strip()
        if not model:
            raise AwsConfigurationError(
                "BEDROCK_EMBEDDING_MODEL_ID is required for Titan embeddings "
                "(set in .env / Lambda env, e.g. amazon.titan-embed-text-v2:0)."
            )
        self._default_model_id = model
        if boto3_client is not None:
            self._client = boto3_client
        else:
            from botocore.config import Config

            from app.aws.session import create_boto3_session

            session = create_boto3_session(settings)
            config = Config(
                region_name=settings.bedrock_region,
                connect_timeout=settings.connect_timeout_seconds,
                read_timeout=max(60.0, settings.read_timeout_seconds),
                retries={"max_attempts": settings.max_attempts, "mode": "standard"},
            )
            self._client = session.client(
                "bedrock-runtime",
                region_name=settings.bedrock_region,
                config=config,
            )

    def embed(self, text: str, *, model_id: str | None = None) -> list[float]:
        mid = model_id or self._default_model_id
        body = {
            "inputText": text,
            "dimensions": EMBEDDING_DIMENSIONS,
            "normalize": True,
        }
        try:
            response = self._client.invoke_model(
                modelId=mid,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
            raw = response.get("body")
            if hasattr(raw, "read"):
                payload = json.loads(raw.read())
            else:
                payload = json.loads(raw)
        except ClientError as exc:
            code = (exc.response.get("Error") or {}).get("Code", "ClientError")
            message = (exc.response.get("Error") or {}).get("Message", str(exc))
            lowered = message.lower()
            if code == "AccessDeniedException" or "access" in lowered:
                raise EmbeddingAccessError(
                    f"Amazon Titan embedding access is not available for model "
                    f"'{mid}' in region '{self._settings.bedrock_region}'. "
                    f"Ensure Bedrock permissions allow InvokeModel on Titan "
                    f"embeddings and set BEDROCK_EMBEDDING_MODEL_ID in the "
                    f"environment (see .env.example)."
                ) from exc
            raise EmbeddingInvocationError(
                f"Titan embedding failed ({code}): {message}"
            ) from exc
        except (BotoCoreError, OSError, json.JSONDecodeError) as exc:
            raise EmbeddingInvocationError(
                f"Titan embedding transport/parse error: {exc}"
            ) from exc

        vector = payload.get("embedding")
        if not isinstance(vector, list) or len(vector) != EMBEDDING_DIMENSIONS:
            raise EmbeddingInvocationError(
                f"Titan returned unexpected embedding shape "
                f"(expected {EMBEDDING_DIMENSIONS} floats)"
            )
        return [float(v) for v in vector]


class MockEmbeddingClient(EmbeddingClient):
    """Deterministic fake embeddings for verification without live Bedrock."""

    def __init__(self, *, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions
        self.calls: list[str] = []

    def embed(self, text: str, *, model_id: str | None = None) -> list[float]:
        self.calls.append(text)
        # Stable pseudo-vector from text hash; similar texts get similar vectors.
        seed = sum(ord(c) for c in text) % 997
        vector = []
        for i in range(self.dimensions):
            # Simple deterministic pattern with text influence.
            val = ((seed + i * 13) % 1000) / 1000.0
            if "index" in text.lower():
                val = min(1.0, val + 0.05)
            vector.append(val)
        # L2-normalize lightly for cosine friendliness.
        norm = sum(v * v for v in vector) ** 0.5 or 1.0
        return [v / norm for v in vector]


def require_embedding_model_id(settings: AwsSettings) -> str:
    mid = (settings.bedrock_embedding_model_id or "").strip()
    if not mid:
        raise AwsConfigurationError(
            "BEDROCK_EMBEDDING_MODEL_ID is not set. Configure Titan embeddings "
            "in .env (see .env.example)."
        )
    return mid
