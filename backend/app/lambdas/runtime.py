"""Dependency injection and async runtime for Lambda handlers."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.aws import AwsClientFactory, AwsSettings, get_aws_settings
from app.aws.artifacts import ArtifactStore
from app.aws.correlation import correlation_context
from app.aws.observability import CloudWatchObservability
from app.aws.secrets_service import SecretsService
from app.config import Settings, get_settings
from app.core.logging import get_logger, setup_logging
from app.database import DatabaseSessionManager
from app.lambdas.secrets import AwsSecretStore, LocalSecretStore, SecretStore
from app.shadow.factory import create_shadow_provider
from app.shadow.provider import ShadowClusterProvider

logger = get_logger(__name__)

T = TypeVar("T")

_LOCAL_MODE_ENV = "LAMBDA_LOCAL_MODE"


def is_local_mode() -> bool:
    return os.environ.get(_LOCAL_MODE_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass
class LambdaRuntime:
    """Process-scoped dependencies shared across handler invocations."""

    settings: Settings
    aws_settings: AwsSettings
    database: DatabaseSessionManager
    secrets: SecretStore
    aws_clients: AwsClientFactory | None = None
    secrets_service: SecretsService | None = None
    artifacts: ArtifactStore | None = None
    observability: CloudWatchObservability | None = None

    def create_provider(self) -> ShadowClusterProvider:
        return create_shadow_provider(self.settings)

    async def close(self) -> None:
        if self.aws_clients is not None:
            self.aws_clients.close()
        await self.database.close()


_RUNTIME: LambdaRuntime | None = None


def get_runtime() -> LambdaRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = build_runtime()
    return _RUNTIME


def reset_runtime() -> None:
    """Clear cached runtime (used by the local runner between process setups)."""
    global _RUNTIME
    _RUNTIME = None
    get_settings.cache_clear()
    get_aws_settings.cache_clear()


def build_runtime() -> LambdaRuntime:
    settings = get_settings()
    aws_settings = get_aws_settings()
    setup_logging(settings.log_level)

    database = DatabaseSessionManager(settings.database_url.get_secret_value())
    aws_clients: AwsClientFactory | None = None
    secrets_service: SecretsService | None = None
    artifacts: ArtifactStore | None = None
    observability: CloudWatchObservability | None = None
    secrets: SecretStore

    if is_local_mode() or not aws_settings.aws_enabled:
        secrets = LocalSecretStore()
        logger.info(
            "Lambda runtime using local secret store",
            extra={"environment": settings.environment},
        )
    else:
        aws_clients = AwsClientFactory(aws_settings)
        secrets_service = SecretsService(
            aws_clients,
            aws_settings,
            cache_ttl_seconds=aws_settings.secrets_cache_ttl_seconds,
        )
        secrets = AwsSecretStore(secrets_service)
        artifacts = ArtifactStore(aws_clients, aws_settings)
        observability = CloudWatchObservability(aws_clients, aws_settings)
        logger.info(
            "Lambda runtime using AWS Secrets Manager / S3 / CloudWatch",
            extra={
                "environment": settings.environment,
                "aws_region": aws_settings.region,
                "aws_auth_mode": aws_settings.auth_mode,
                "run_artifacts_bucket": aws_settings.run_artifacts_bucket,
            },
        )

    return LambdaRuntime(
        settings=settings,
        aws_settings=aws_settings,
        database=database,
        secrets=secrets,
        aws_clients=aws_clients,
        secrets_service=secrets_service,
        artifacts=artifacts,
        observability=observability,
    )


async def with_session(
    runtime: LambdaRuntime,
    fn: Callable[[AsyncSession], Awaitable[T]],
) -> T:
    async for session in runtime.database.session():
        return await fn(session)
    raise RuntimeError("Database session factory yielded no session")


def run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run an async handler body from a sync Lambda entrypoint."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def require_run_id(event: dict[str, Any]) -> str:
    run_id = event.get("run_id")
    if not run_id or not isinstance(run_id, str):
        from app.lambdas.errors import LambdaValidationError

        raise LambdaValidationError("event.run_id is required")
    return run_id


@contextmanager
def handler_correlation(
    event: dict[str, Any],
    context: Any = None,
    *,
    function_name: str | None = None,
) -> Iterator[str]:
    """Bind run_id / Lambda / SFN correlation for the duration of a handler."""
    run_id = require_run_id(event)
    lambda_request_id = getattr(context, "aws_request_id", None) if context else None
    lambda_function_name = function_name or getattr(
        context,
        "function_name",
        None,
    )
    sfn_execution_arn = event.get("sfn_execution_arn") or event.get(
        "execution_arn"
    )
    with correlation_context(
        run_id=run_id,
        lambda_request_id=str(lambda_request_id) if lambda_request_id else None,
        lambda_function_name=(
            str(lambda_function_name) if lambda_function_name else None
        ),
        sfn_execution_arn=str(sfn_execution_arn) if sfn_execution_arn else None,
    ):
        yield run_id
