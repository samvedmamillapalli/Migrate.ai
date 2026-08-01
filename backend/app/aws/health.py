"""AWS connectivity health checks.

All boto3 calls run in a worker thread so FastAPI's event loop stays free.
Never log credentials or secret values.
"""

from __future__ import annotations

import asyncio
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from app.aws.clients import AwsClientFactory
from app.aws.config import AwsSettings
from app.aws.exceptions import AwsConnectivityError
from app.core.logging import get_logger

logger = get_logger(__name__)


def _sts_get_caller_identity(factory: AwsClientFactory) -> dict[str, str]:
    response = factory.sts().get_caller_identity()
    return {
        "account": str(response.get("Account", "")),
        "arn": str(response.get("Arn", "")),
        "user_id": str(response.get("UserId", "")),
    }


def _optional_s3_probe(factory: AwsClientFactory, bucket: str) -> None:
    factory.s3().head_bucket(Bucket=bucket)


async def check_aws_connectivity(
    factory: AwsClientFactory,
    *,
    probe_configured_resources: bool = False,
) -> dict[str, Any]:
    """Verify STS reachability and optionally configured resource handles.

    Returns a dict safe for health payloads (no secrets).
    """
    settings = factory.settings
    try:
        identity = await asyncio.to_thread(_sts_get_caller_identity, factory)
    except (BotoCoreError, ClientError, OSError) as exc:
        logger.warning(
            "AWS STS health check failed",
            extra={
                "aws_region": settings.region,
                "aws_auth_mode": settings.auth_mode,
                "error_type": type(exc).__name__,
            },
        )
        raise AwsConnectivityError(
            f"Unable to reach AWS STS in {settings.region}"
        ) from exc

    result: dict[str, Any] = {
        "status": "healthy",
        "region": settings.region,
        "auth_mode": settings.auth_mode,
        "account": identity["account"],
        # ARN is an identity locator, not a credential — safe to expose in health.
        "caller_arn": identity["arn"],
    }

    if probe_configured_resources and settings.run_artifacts_bucket:
        try:
            await asyncio.to_thread(
                _optional_s3_probe,
                factory,
                settings.run_artifacts_bucket,
            )
            result["s3_bucket"] = "reachable"
        except (BotoCoreError, ClientError, OSError) as exc:
            logger.warning(
                "AWS S3 health probe failed",
                extra={
                    "aws_region": settings.region,
                    "run_artifacts_bucket": settings.run_artifacts_bucket,
                    "error_type": type(exc).__name__,
                },
            )
            raise AwsConnectivityError(
                f"Unable to reach S3 bucket {settings.run_artifacts_bucket}"
            ) from exc

    logger.info(
        "AWS health check succeeded",
        extra={
            "aws_region": settings.region,
            "aws_auth_mode": settings.auth_mode,
            "aws_account": identity["account"],
        },
    )
    return result


async def aws_health_snapshot(
    settings: AwsSettings,
    factory: AwsClientFactory | None,
) -> dict[str, Any]:
    """Build the ``aws`` section of the /health response."""
    if not settings.aws_enabled:
        return {"status": "disabled", "region": settings.region}

    if factory is None:
        return {
            "status": "unhealthy",
            "region": settings.region,
            "detail": "AWS client factory not initialized",
        }

    try:
        details = await check_aws_connectivity(factory)
        return {
            "status": details["status"],
            "region": details["region"],
            "auth_mode": details["auth_mode"],
            "account": details["account"],
        }
    except AwsConnectivityError as exc:
        return {
            "status": "unhealthy",
            "region": settings.region,
            "auth_mode": settings.auth_mode,
            "detail": exc.message,
        }
