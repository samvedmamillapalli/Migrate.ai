"""AWS infrastructure foundation + workflow + Phase 8D service integrations.

Isolated from business logic. Provides typed settings, reusable boto3 clients,
Secrets Manager, S3 artifacts, CloudWatch observability, and Step Functions
helpers.
"""

from app.aws.artifacts import ArtifactStore, ArtifactStoreError
from app.aws.clients import AwsClientFactory
from app.aws.config import AwsSettings, get_aws_settings
from app.aws.correlation import correlation_context, get_correlation_fields
from app.aws.exceptions import (
    AwsConfigurationError,
    AwsConnectivityError,
    AwsError,
)
from app.aws.health import aws_health_snapshot, check_aws_connectivity
from app.aws.observability import CloudWatchObservability, ObservabilityError
from app.aws.secrets_service import SecretsService, SecretsServiceError
from app.aws.session import create_boto3_session
from app.aws.validation import validate_aws_startup
from app.aws.workflow import (
    WorkflowExecutionError,
    WorkflowExecutionRef,
    WorkflowStartInput,
    WorkflowStatus,
    describe_workflow_execution,
    render_definition,
    start_workflow_execution,
    validate_definition_structure,
    validate_workflow_definition,
)

__all__ = [
    "ArtifactStore",
    "ArtifactStoreError",
    "AwsClientFactory",
    "AwsConfigurationError",
    "AwsConnectivityError",
    "AwsError",
    "AwsSettings",
    "CloudWatchObservability",
    "ObservabilityError",
    "SecretsService",
    "SecretsServiceError",
    "WorkflowExecutionError",
    "WorkflowExecutionRef",
    "WorkflowStartInput",
    "WorkflowStatus",
    "aws_health_snapshot",
    "check_aws_connectivity",
    "correlation_context",
    "create_boto3_session",
    "describe_workflow_execution",
    "get_aws_settings",
    "get_correlation_fields",
    "render_definition",
    "start_workflow_execution",
    "validate_aws_startup",
    "validate_definition_structure",
    "validate_workflow_definition",
]
