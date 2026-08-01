"""Startup validation for the AWS foundation.

Development: warn and continue when AWS is unreachable or incomplete.
Demo / staging / production (or AWS_REQUIRE_WORKFLOW_CONFIG=true): fail fast
with an actionable message when MIGRATION_WORKFLOW_ARN or RUN_ARTIFACTS_BUCKET
are missing while AWS is enabled.
"""

from __future__ import annotations

from app.aws.clients import AwsClientFactory
from app.aws.config import AwsSettings
from app.aws.exceptions import AwsConfigurationError, AwsConnectivityError
from app.aws.health import check_aws_connectivity
from app.core.logging import get_logger

logger = get_logger(__name__)

_MISSING_WORKFLOW_HELP = (
    "Durable verify cannot start without stack outputs. Deploy from infra/sam "
    "(see docs/DEPLOYMENT.md), then set in .env:\n"
    "  MIGRATION_WORKFLOW_ARN=<MigrationWorkflowArn output>\n"
    "  RUN_ARTIFACTS_BUCKET=<ArtifactsBucket output>\n"
    "Retrieve with:\n"
    "  aws cloudformation describe-stacks --stack-name migration-oracle "
    "--region us-east-1 "
    "--query \"Stacks[0].Outputs[?OutputKey=='MigrationWorkflowArn' || "
    "OutputKey=='ArtifactsBucket'].[OutputKey,OutputValue]\" --output table"
)


def _is_production(environment: str) -> bool:
    return environment.strip().lower() in {"production", "prod"}


async def validate_aws_startup(
    settings: AwsSettings,
    factory: AwsClientFactory | None,
    *,
    environment: str,
) -> None:
    """Validate AWS configuration and connectivity at application startup.

    Never logs credential values — only region, auth mode, and resource names.
    """
    if not settings.aws_enabled:
        logger.info(
            "AWS disabled at startup; skipping validation",
            extra={"environment": environment},
        )
        return

    if factory is None:
        message = "AWS is enabled but the client factory was not created"
        if _is_production(environment) or settings.workflow_config_required(environment):
            raise AwsConfigurationError(message)
        logger.warning(message, extra={"environment": environment})
        return

    logger.info(
        "Validating AWS configuration",
        extra={
            "environment": environment,
            "aws_region": settings.region,
            "aws_auth_mode": settings.auth_mode,
            "aws_profile": settings.profile,
            "has_migration_workflow_arn": bool(settings.migration_workflow_arn),
            "has_run_artifacts_bucket": bool(settings.run_artifacts_bucket),
            "has_bedrock_prediction_model_id": bool(
                settings.bedrock_prediction_model_id
            ),
            "bedrock_embedding_model_id": settings.bedrock_embedding_model_id,
            "user_database_secret_prefix": settings.user_database_secret_prefix,
            "lambda_function_prefix": settings.lambda_function_prefix,
            "cloudwatch_namespace": settings.cloudwatch_namespace,
        },
    )

    missing = settings.production_required_missing()
    if missing and settings.workflow_config_required(environment):
        raise AwsConfigurationError(
            "AWS workflow configuration incomplete; missing: "
            + ", ".join(missing)
            + ". "
            + _MISSING_WORKFLOW_HELP
        )
    if missing:
        logger.error(
            "AWS workflow settings incomplete — approve(proceed) cannot start "
            "Step Functions until deployed. "
            + _MISSING_WORKFLOW_HELP,
            extra={
                "environment": environment,
                "missing_settings": missing,
            },
        )

    try:
        identity = await check_aws_connectivity(
            factory,
            probe_configured_resources=_is_production(environment)
            or settings.workflow_config_required(environment),
        )
    except AwsConnectivityError:
        if _is_production(environment) or settings.workflow_config_required(
            environment
        ):
            raise
        logger.warning(
            "AWS connectivity check failed in non-production; continuing startup",
            extra={
                "environment": environment,
                "aws_region": settings.region,
                "aws_auth_mode": settings.auth_mode,
            },
        )
        return

    logger.info(
        "AWS startup validation succeeded",
        extra={
            "environment": environment,
            "aws_region": settings.region,
            "aws_auth_mode": settings.auth_mode,
            "aws_account": identity.get("account"),
            "migration_workflow_arn": settings.migration_workflow_arn,
            "run_artifacts_bucket": settings.run_artifacts_bucket,
        },
    )
