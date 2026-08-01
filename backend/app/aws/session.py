"""boto3 session construction.

Credentials are passed only into boto3 and never logged.
"""

from __future__ import annotations

import boto3
from botocore.config import Config

from app.aws.config import AwsSettings
from app.aws.exceptions import AwsConfigurationError
from app.core.logging import get_logger

logger = get_logger(__name__)


def build_botocore_config(settings: AwsSettings) -> Config:
    return Config(
        region_name=settings.region,
        connect_timeout=settings.connect_timeout_seconds,
        read_timeout=settings.read_timeout_seconds,
        retries={"max_attempts": settings.max_attempts, "mode": "standard"},
    )


def create_boto3_session(settings: AwsSettings) -> boto3.Session:
    """Build a boto3 Session from typed settings.

    Auth precedence:
    1. Explicit access key pair (optional session token)
    2. Named profile
    3. Default credential chain (env / shared config / IAM role)
    """
    if not settings.aws_enabled:
        raise AwsConfigurationError("AWS is disabled (AWS_ENABLED=false)")

    session_kwargs: dict[str, str] = {"region_name": settings.region}

    if settings.access_key_id is not None and settings.secret_access_key is not None:
        session_kwargs["aws_access_key_id"] = (
            settings.access_key_id.get_secret_value()
        )
        session_kwargs["aws_secret_access_key"] = (
            settings.secret_access_key.get_secret_value()
        )
        if settings.session_token is not None:
            session_kwargs["aws_session_token"] = (
                settings.session_token.get_secret_value()
            )
    elif settings.profile:
        session_kwargs["profile_name"] = settings.profile

    logger.info(
        "Creating AWS session",
        extra={
            "aws_region": settings.region,
            "aws_auth_mode": settings.auth_mode,
            "aws_profile": settings.profile,
        },
    )
    return boto3.Session(**session_kwargs)
