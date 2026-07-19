"""Injectable Bedrock client for prediction and recommendation calls."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from app.aws.config import AwsSettings
from app.aws.exceptions import AwsConfigurationError, AwsError
from app.core.logging import get_logger

logger = get_logger(__name__)


class BedrockAccessError(AwsError):
    """Raised when Bedrock model access is missing or misconfigured.

    Message is actionable: request Anthropic model access in the Bedrock
    console for the configured region.
    """


class BedrockInvocationError(AwsError):
    """Raised for non-access Bedrock invocation failures."""


class BedrockClient(ABC):
    """Abstract Bedrock text generation client (injectable for tests)."""

    @abstractmethod
    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model_id: str | None = None,
    ) -> str:
        """Return model text expected to contain a JSON object."""


_ACCESS_ERROR_CODES = frozenset(
    {
        "AccessDeniedException",
        "UnrecognizedClientException",
        "ResourceNotFoundException",
        "ValidationException",
    }
)

_ACCESS_MESSAGE_HINTS = (
    "you don't have access",
    "not authorized",
    "access denied",
    "is not authorized to perform",
    "model access",
    "hasn't been granted",
)


def _is_access_error(exc: ClientError) -> bool:
    code = (exc.response.get("Error") or {}).get("Code", "")
    message = ((exc.response.get("Error") or {}).get("Message") or "").lower()
    if code in _ACCESS_ERROR_CODES and any(h in message for h in _ACCESS_MESSAGE_HINTS):
        return True
    if any(h in message for h in _ACCESS_MESSAGE_HINTS):
        return True
    if code == "AccessDeniedException":
        return True
    return False


def _inference_profile_candidates(model_id: str, region: str) -> list[str]:
    """Return model ids to try, preferring inference profiles for Claude.

    Newer Anthropic models on Bedrock reject bare foundation-model ids for
    on-demand invoke and require a regional inference profile
    (e.g. ``us.anthropic.claude-sonnet-4-6``).
    """
    candidates = [model_id]
    if model_id.startswith("anthropic."):
        # Map AWS_DEFAULT_REGION / BEDROCK_REGION to common profile prefixes.
        prefix = "us"
        lowered = region.lower()
        if lowered.startswith("eu"):
            prefix = "eu"
        elif lowered.startswith("ap"):
            prefix = "apac"
        profile = f"{prefix}.{model_id}"
        if profile not in candidates:
            candidates.append(profile)
    return candidates


def _is_inference_profile_required(exc: ClientError) -> bool:
    message = ((exc.response.get("Error") or {}).get("Message") or "").lower()
    return "inference profile" in message or (
        "on-demand" in message and "isn't supported" in message
    ) or ("on-demand" in message and "not supported" in message)


def _access_error_message(model_id: str, region: str) -> str:
    return (
        f"Amazon Bedrock model access is not available for model "
        f"'{model_id}' in region '{region}'. Open the AWS Bedrock console, "
        f"request access to the Anthropic Claude models in {region}, wait "
        f"until the status is Access granted, then set "
        f"BEDROCK_PREDICTION_MODEL_ID to an inference profile id such as "
        f"us.anthropic.claude-sonnet-4-6 (and optionally "
        f"BEDROCK_RECOMMENDATION_MODEL_ID). "
        f"See docs/PHASE_9_AI_PREDICTION.md."
    )


class AwsBedrockClient(BedrockClient):
    """Live Bedrock Runtime client using the Converse API."""

    def __init__(
        self,
        *,
        settings: AwsSettings,
        boto3_client: Any | None = None,
    ) -> None:
        self._settings = settings
        if not settings.bedrock_prediction_model_id:
            raise AwsConfigurationError(
                "BEDROCK_PREDICTION_MODEL_ID is not set. Add the Bedrock model "
                "identifier to your environment after requesting model access "
                "in the Bedrock console (region "
                f"{settings.bedrock_region})."
            )
        if boto3_client is not None:
            self._client = boto3_client
        else:
            from botocore.config import Config

            from app.aws.session import create_boto3_session

            session = create_boto3_session(settings)
            # LLM calls need a longer read timeout than generic AWS clients.
            bedrock_config = Config(
                region_name=settings.bedrock_region,
                connect_timeout=settings.connect_timeout_seconds,
                read_timeout=max(120.0, settings.read_timeout_seconds),
                retries={"max_attempts": settings.max_attempts, "mode": "standard"},
            )
            self._client = session.client(
                "bedrock-runtime",
                region_name=settings.bedrock_region,
                config=bedrock_config,
            )

    @property
    def model_id(self) -> str:
        assert self._settings.bedrock_prediction_model_id is not None
        return self._settings.bedrock_prediction_model_id

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model_id: str | None = None,
    ) -> str:
        requested = model_id or self.model_id
        candidates = _inference_profile_candidates(
            requested,
            self._settings.bedrock_region,
        )
        last_error: Exception | None = None

        for mid in candidates:
            try:
                response = self._client.converse(
                    modelId=mid,
                    system=[{"text": system_prompt}],
                    messages=[
                        {
                            "role": "user",
                            "content": [{"text": user_prompt}],
                        }
                    ],
                    inferenceConfig={
                        "temperature": 0.0,
                        "maxTokens": 4096,
                    },
                )
                if mid != requested:
                    logger.info(
                        "Bedrock used inference profile after foundation model reject",
                        extra={
                            "requested_model_id": requested,
                            "resolved_model_id": mid,
                        },
                    )
                text = _extract_converse_text(response)
                if not text.strip():
                    raise BedrockInvocationError("Bedrock returned an empty response")
                return text
            except ClientError as exc:
                last_error = exc
                if _is_inference_profile_required(exc) and mid != candidates[-1]:
                    logger.warning(
                        "Bedrock rejected model id; trying inference profile",
                        extra={"model_id": mid},
                    )
                    continue
                if _is_access_error(exc):
                    raise BedrockAccessError(
                        _access_error_message(
                            requested,
                            self._settings.bedrock_region,
                        )
                    ) from exc
                code = (exc.response.get("Error") or {}).get("Code", "ClientError")
                message = (exc.response.get("Error") or {}).get("Message", str(exc))
                raise BedrockInvocationError(
                    f"Bedrock invocation failed ({code}): {message}"
                ) from exc
            except BotoCoreError as exc:
                raise BedrockInvocationError(
                    f"Bedrock transport error: {exc}"
                ) from exc

        assert last_error is not None
        raise BedrockInvocationError(str(last_error)) from last_error


class MockBedrockClient(BedrockClient):
    """Deterministic fake for verification scripts and unit tests."""

    def __init__(
        self,
        *,
        prediction_payload: dict[str, Any] | None = None,
        recommendation_payload: dict[str, Any] | None = None,
        fail_times: int = 0,
        malformed_then_valid: bool = False,
        always_malformed: bool = False,
    ) -> None:
        self.prediction_payload = prediction_payload or {
            "estimated_duration_seconds": 42.0,
            "estimated_storage_mb": 128.0,
            "rollback_risk": "medium",
            "confidence_score": 0.82,
            "risk_explanation": (
                "Shadow-tier index backfill on a medium table; storage growth "
                "from the secondary index is the main cost."
            ),
            "key_assumptions": [
                "Shadow scale tier matches seeded row caps",
                "No concurrent heavy schema jobs on the shadow cluster",
            ],
            "uncertainty_notes": [
                "No historical memories retrieved yet",
            ],
        }
        self.recommendation_payload = recommendation_payload or {
            "recommended_strategy": "expand_backfill_contract",
            "rollout_steps": [
                "Add the new index in a backward-compatible migration",
                "Monitor the schema change job on the shadow cluster",
                "Deploy application code that depends on the index",
            ],
            "suggested_deployment_window": "Off-peak; schema jobs still consume CPU/IO",
            "rollback_guidance": (
                "DROP INDEX if the index is unused; destructive drops need a "
                "separate reviewed change."
            ),
            "monitoring_checklist": [
                "Watch schema change job status",
                "Watch storage growth on the shadow cluster",
                "Watch CPU/IO saturation during backfill",
            ],
            "safer_alternative_plan": (
                "If this were a destructive change, split into expand → "
                "backfill → contract with separate migrations."
            ),
            "rationale": (
                "Additive index creation is safer than rewrite patterns; "
                "still monitor backfill duration and storage growth."
            ),
        }
        self._fail_times = fail_times
        self._malformed_then_valid = malformed_then_valid
        self._always_malformed = always_malformed
        self._call_count = 0
        self.calls: list[dict[str, str]] = []

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model_id: str | None = None,
    ) -> str:
        self._call_count += 1
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "model_id": model_id or "mock",
            }
        )
        if self._fail_times > 0:
            self._fail_times -= 1
            raise BedrockInvocationError("mock Bedrock failure")

        if self._always_malformed:
            return "this is not json {"

        # Heuristic: recommendation prompts mention recommended_strategy fields
        is_recommendation = (
            "recommended_strategy" in system_prompt
            or "recommended_strategy" in user_prompt
            or "Recommendation Engine" in system_prompt
        )
        is_surprise = (
            "surprise_notes" in system_prompt
            or "lessons_learned" in system_prompt
            or "postmortem" in system_prompt.lower()
        )

        if self._malformed_then_valid and self._call_count == 1:
            return "this is not json {"

        if is_surprise:
            payload = {
                "surprise_notes": (
                    "Expected faster backfill; storage growth matched but "
                    "duration missed the tier band — likely underestimated "
                    "index build cost."
                ),
                "lessons_learned": (
                    "Index creation at this tier can miss duration bands; "
                    "weight storage and backfill duration together."
                ),
            }
            return json.dumps(payload)

        payload = (
            self.recommendation_payload if is_recommendation else self.prediction_payload
        )
        return json.dumps(payload)


def _extract_converse_text(response: dict[str, Any]) -> str:
    output = response.get("output") or {}
    message = output.get("message") or {}
    parts = message.get("content") or []
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict) and "text" in part:
            texts.append(str(part["text"]))
    return "\n".join(texts)


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from model text (allows surrounding prose)."""
    stripped = text.strip()
    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    match = _JSON_OBJECT_RE.search(stripped)
    if not match:
        raise ValueError("No JSON object found in model response")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Model JSON was not an object")
    return value
