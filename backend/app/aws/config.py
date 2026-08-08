"""Typed AWS settings for the control-plane foundation.

Credentials are loaded via pydantic SecretStr and must never be logged.
Resource identifiers (ARNs, buckets, prefixes) are safe to log.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config import PROJECT_ROOT


class AwsSettings(BaseSettings):
    """Environment-backed AWS configuration.

    Development may omit resource ARNs and rely on the default credential
    chain (profile / env keys / instance role). Production requires the
    workflow and artifact settings used by later Phase 8 steps.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Master switch. When false, clients are not created and health reports
    # aws=disabled. Useful for local work that does not touch AWS.
    aws_enabled: bool = Field(default=True, validation_alias="AWS_ENABLED")

    # Region and authentication. Prefer AWS_PROFILE locally and an IAM role in
    # deployed environments. Explicit access keys are a last resort.
    region: str = Field(default="us-east-1", validation_alias="AWS_DEFAULT_REGION")
    profile: str | None = Field(default=None, validation_alias="AWS_PROFILE")
    access_key_id: SecretStr | None = Field(
        default=None,
        validation_alias="AWS_ACCESS_KEY_ID",
    )
    secret_access_key: SecretStr | None = Field(
        default=None,
        validation_alias="AWS_SECRET_ACCESS_KEY",
    )
    session_token: SecretStr | None = Field(
        default=None,
        validation_alias="AWS_SESSION_TOKEN",
    )

    # Step Functions (Phase 8B+ will start executions; foundation only stores ARN)
    migration_workflow_arn: str | None = Field(
        default=None,
        validation_alias="MIGRATION_WORKFLOW_ARN",
    )
    step_functions_endpoint_url: str | None = Field(
        default=None,
        validation_alias="AWS_STEP_FUNCTIONS_ENDPOINT_URL",
    )

    # Lambda naming / endpoint (functions implemented in Phase 8C+; ARNs used
    # only to render/validate the Step Functions definition in Phase 8B)
    lambda_function_prefix: str = Field(
        default="migration-oracle",
        validation_alias="AWS_LAMBDA_FUNCTION_PREFIX",
    )
    lambda_endpoint_url: str | None = Field(
        default=None,
        validation_alias="AWS_LAMBDA_ENDPOINT_URL",
    )
    lambda_discover_schema_arn: str | None = Field(
        default=None,
        validation_alias="AWS_LAMBDA_DISCOVER_SCHEMA_ARN",
    )
    lambda_provision_shadow_cluster_arn: str | None = Field(
        default=None,
        validation_alias="AWS_LAMBDA_PROVISION_SHADOW_CLUSTER_ARN",
    )
    lambda_load_schema_arn: str | None = Field(
        default=None,
        validation_alias="AWS_LAMBDA_LOAD_SCHEMA_ARN",
    )
    lambda_execute_migration_arn: str | None = Field(
        default=None,
        validation_alias="AWS_LAMBDA_EXECUTE_MIGRATION_ARN",
    )
    lambda_collect_metrics_arn: str | None = Field(
        default=None,
        validation_alias="AWS_LAMBDA_COLLECT_METRICS_ARN",
    )
    lambda_persist_results_arn: str | None = Field(
        default=None,
        validation_alias="AWS_LAMBDA_PERSIST_RESULTS_ARN",
    )
    lambda_cleanup_arn: str | None = Field(
        default=None,
        validation_alias="AWS_LAMBDA_CLEANUP_ARN",
    )
    # Optional AWS account id used when synthesizing placeholder Lambda ARNs
    # for ASL validation before functions exist.
    aws_account_id: str | None = Field(
        default=None,
        validation_alias="AWS_ACCOUNT_ID",
    )

    # S3 run artifacts
    run_artifacts_bucket: str | None = Field(
        default=None,
        validation_alias="RUN_ARTIFACTS_BUCKET",
    )
    s3_endpoint_url: str | None = Field(
        default=None,
        validation_alias="AWS_S3_ENDPOINT_URL",
    )

    # SES (workspace invite emails — app/services/email_service.py). Must be
    # a verified sender identity in the SES console; SES sandbox mode also
    # requires the recipient to be verified until the account is out of
    # sandbox. Unset means email sending is skipped (logged, not fatal).
    ses_sender_email: str | None = Field(
        default=None,
        validation_alias="SES_SENDER_EMAIL",
    )

    # Secrets Manager
    user_database_secret_prefix: str = Field(
        default="migration-oracle/connections",
        validation_alias="USER_DATABASE_SECRET_PREFIX",
    )
    ccloud_api_key_secret_arn: str | None = Field(
        default=None,
        validation_alias="CCLOUD_API_KEY_SECRET_ARN",
    )
    secrets_manager_endpoint_url: str | None = Field(
        default=None,
        validation_alias="AWS_SECRETS_MANAGER_ENDPOINT_URL",
    )

    # CloudWatch
    cloudwatch_namespace: str = Field(
        default="MigrationOracle",
        validation_alias="AWS_CLOUDWATCH_NAMESPACE",
    )
    cloudwatch_log_group: str | None = Field(
        default=None,
        validation_alias="AWS_CLOUDWATCH_LOG_GROUP",
    )
    cloudwatch_endpoint_url: str | None = Field(
        default=None,
        validation_alias="AWS_CLOUDWATCH_ENDPOINT_URL",
    )
    cloudwatch_log_retention_days: int = Field(
        default=14,
        ge=1,
        le=3653,
        validation_alias="AWS_CLOUDWATCH_LOG_RETENTION_DAYS",
    )
    secrets_cache_ttl_seconds: float = Field(
        default=300.0,
        ge=0.0,
        le=3600.0,
        validation_alias="AWS_SECRETS_CACHE_TTL_SECONDS",
    )

    # --- Phase 9: Amazon Bedrock (prediction + recommendation) ---
    # Model access must be requested in the Bedrock console for this region
    # before live invocations succeed. Leave blank until access is granted.
    bedrock_prediction_model_id: str | None = Field(
        default=None,
        validation_alias="BEDROCK_PREDICTION_MODEL_ID",
    )
    bedrock_recommendation_model_id: str | None = Field(
        default=None,
        validation_alias="BEDROCK_RECOMMENDATION_MODEL_ID",
    )
    # Defaults to AWS_DEFAULT_REGION; override only if Bedrock is enabled elsewhere.
    bedrock_region: str = Field(
        default="us-east-1",
        validation_alias="BEDROCK_REGION",
    )
    bedrock_embedding_model_id: str = Field(
        default="amazon.titan-embed-text-v2:0",
        validation_alias="BEDROCK_EMBEDDING_MODEL_ID",
        description="Set via BEDROCK_EMBEDDING_MODEL_ID (never omit in deploy)",
    )

    # When true (or environment is production/demo/staging), refuse startup if
    # MIGRATION_WORKFLOW_ARN / RUN_ARTIFACTS_BUCKET are missing while AWS is on.
    require_workflow_config: bool = Field(
        default=False,
        validation_alias="AWS_REQUIRE_WORKFLOW_CONFIG",
    )

    @field_validator("bedrock_embedding_model_id", mode="before")
    @classmethod
    def embedding_model_id_default(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return "amazon.titan-embed-text-v2:0"
        return value

    # Alarms — any cleanup failure; orphaned cluster count >= 1
    alarm_cleanup_failed_threshold: int = Field(
        default=1,
        ge=1,
        validation_alias="AWS_ALARM_CLEANUP_FAILED_THRESHOLD",
    )
    alarm_cleanup_failed_period_seconds: int = Field(
        default=60,
        ge=60,
        validation_alias="AWS_ALARM_CLEANUP_FAILED_PERIOD_SECONDS",
    )
    alarm_cleanup_failed_evaluation_periods: int = Field(
        default=5,
        ge=1,
        validation_alias="AWS_ALARM_CLEANUP_FAILED_EVALUATION_PERIODS",
    )
    alarm_orphaned_clusters_threshold: int = Field(
        default=1,
        ge=1,
        validation_alias="AWS_ALARM_ORPHANED_CLUSTERS_THRESHOLD",
    )
    alarm_orphaned_clusters_period_seconds: int = Field(
        default=300,
        ge=60,
        validation_alias="AWS_ALARM_ORPHANED_CLUSTERS_PERIOD_SECONDS",
    )
    alarm_orphaned_clusters_evaluation_periods: int = Field(
        default=2,
        ge=1,
        validation_alias="AWS_ALARM_ORPHANED_CLUSTERS_EVALUATION_PERIODS",
    )

    # Client behavior
    connect_timeout_seconds: float = Field(
        default=5.0,
        ge=0.5,
        le=60.0,
        validation_alias="AWS_CONNECT_TIMEOUT_SECONDS",
    )
    read_timeout_seconds: float = Field(
        default=10.0,
        ge=0.5,
        le=120.0,
        validation_alias="AWS_READ_TIMEOUT_SECONDS",
    )
    max_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias="AWS_MAX_ATTEMPTS",
    )

    @field_validator(
        "profile",
        "migration_workflow_arn",
        "step_functions_endpoint_url",
        "lambda_endpoint_url",
        "lambda_discover_schema_arn",
        "lambda_provision_shadow_cluster_arn",
        "lambda_load_schema_arn",
        "lambda_execute_migration_arn",
        "lambda_collect_metrics_arn",
        "lambda_persist_results_arn",
        "lambda_cleanup_arn",
        "aws_account_id",
        "run_artifacts_bucket",
        "s3_endpoint_url",
        "ccloud_api_key_secret_arn",
        "secrets_manager_endpoint_url",
        "cloudwatch_log_group",
        "cloudwatch_endpoint_url",
        "bedrock_prediction_model_id",
        "bedrock_recommendation_model_id",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("aws_account_id")
    @classmethod
    def validate_account_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.isdigit() or len(value) != 12:
            raise ValueError("AWS_ACCOUNT_ID must be a 12-digit account id")
        return value

    @field_validator("region", "bedrock_region")
    @classmethod
    def validate_region(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("AWS region settings must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_explicit_credentials(self) -> AwsSettings:
        has_key = self.access_key_id is not None
        has_secret = self.secret_access_key is not None
        if has_key != has_secret:
            raise ValueError(
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set together"
            )
        if self.session_token is not None and not has_key:
            raise ValueError(
                "AWS_SESSION_TOKEN requires AWS_ACCESS_KEY_ID and "
                "AWS_SECRET_ACCESS_KEY"
            )
        return self

    @property
    def auth_mode(self) -> str:
        """Safe label for logging — never includes credential material."""
        if not self.aws_enabled:
            return "disabled"
        if self.profile:
            return "profile"
        if self.access_key_id is not None:
            return "access_key"
        return "default_chain"

    def production_required_missing(self) -> list[str]:
        """Names of resource settings required before durable workflows."""
        missing: list[str] = []
        if not self.migration_workflow_arn:
            missing.append("MIGRATION_WORKFLOW_ARN")
        if not self.run_artifacts_bucket:
            missing.append("RUN_ARTIFACTS_BUCKET")
        return missing

    def workflow_config_required(self, environment: str) -> bool:
        if self.require_workflow_config:
            return True
        return environment.strip().lower() in {
            "production",
            "prod",
            "demo",
            "staging",
        }


@lru_cache
def get_aws_settings() -> AwsSettings:
    return AwsSettings()
