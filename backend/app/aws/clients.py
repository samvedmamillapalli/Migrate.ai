"""Reusable boto3 clients for AWS services used by Migration Oracle.

Clients are cached per service name on a single shared session. boto3 is
synchronous; callers that run under asyncio must use ``run_in_executor`` /
``asyncio.to_thread`` (see ``app.aws.health`` and ``app.aws.validation``).
"""

from __future__ import annotations

from typing import Any

import boto3
from botocore.client import BaseClient

from app.aws.config import AwsSettings
from app.aws.exceptions import AwsConfigurationError
from app.aws.session import build_botocore_config, create_boto3_session
from app.core.logging import get_logger

logger = get_logger(__name__)

# Services the control plane expects to talk to in later Phase 8 steps.
_KNOWN_SERVICES = frozenset(
    {
        "sts",
        "stepfunctions",
        "lambda",
        "s3",
        "secretsmanager",
        "logs",
        "cloudwatch",
    }
)


class AwsClientFactory:
    """Process-scoped factory that reuses boto3 clients."""

    def __init__(
        self,
        settings: AwsSettings,
        session: boto3.Session | None = None,
    ) -> None:
        if not settings.aws_enabled:
            raise AwsConfigurationError("Cannot create AWS clients while disabled")
        self._settings = settings
        self._session = session or create_boto3_session(settings)
        self._botocore_config = build_botocore_config(settings)
        self._clients: dict[str, BaseClient] = {}

    @property
    def settings(self) -> AwsSettings:
        return self._settings

    @property
    def session(self) -> boto3.Session:
        return self._session

    def _endpoint_url_for(self, service_name: str) -> str | None:
        mapping = {
            "stepfunctions": self._settings.step_functions_endpoint_url,
            "lambda": self._settings.lambda_endpoint_url,
            "s3": self._settings.s3_endpoint_url,
            "secretsmanager": self._settings.secrets_manager_endpoint_url,
            "logs": self._settings.cloudwatch_endpoint_url,
            "cloudwatch": self._settings.cloudwatch_endpoint_url,
        }
        return mapping.get(service_name)

    def client(self, service_name: str) -> BaseClient:
        if service_name not in _KNOWN_SERVICES:
            raise AwsConfigurationError(f"Unsupported AWS service: {service_name}")

        cached = self._clients.get(service_name)
        if cached is not None:
            return cached

        kwargs: dict[str, Any] = {
            "service_name": service_name,
            "region_name": self._settings.region,
            "config": self._botocore_config,
        }
        endpoint_url = self._endpoint_url_for(service_name)
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url

        client = self._session.client(**kwargs)
        self._clients[service_name] = client
        logger.info(
            "Created AWS client",
            extra={
                "aws_service": service_name,
                "aws_region": self._settings.region,
                "aws_custom_endpoint": bool(endpoint_url),
            },
        )
        return client

    def sts(self) -> BaseClient:
        return self.client("sts")

    def stepfunctions(self) -> BaseClient:
        return self.client("stepfunctions")

    def lambda_(self) -> BaseClient:
        return self.client("lambda")

    def s3(self) -> BaseClient:
        return self.client("s3")

    def secretsmanager(self) -> BaseClient:
        return self.client("secretsmanager")

    def logs(self) -> BaseClient:
        return self.client("logs")

    def cloudwatch(self) -> BaseClient:
        return self.client("cloudwatch")

    def close(self) -> None:
        """Drop cached clients. boto3 does not require explicit network teardown."""
        self._clients.clear()
        logger.info("Cleared cached AWS clients")
