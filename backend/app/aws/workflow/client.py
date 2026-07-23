"""Step Functions client helpers — start, describe, validate (no Lambda logic)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from app.aws.clients import AwsClientFactory
from app.aws.config import AwsSettings
from app.aws.exceptions import AwsConfigurationError, AwsConnectivityError, AwsError
from app.aws.workflow.definition import (
    render_definition,
    validate_definition_structure,
)
from app.aws.workflow.models import (
    SFN_STATUS_TO_WORKFLOW,
    WorkflowExecutionRef,
    WorkflowStartInput,
    WorkflowStatus,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class WorkflowExecutionError(AwsError):
    """Raised when starting or describing a workflow execution fails."""


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _map_status(raw: str) -> WorkflowStatus:
    try:
        return SFN_STATUS_TO_WORKFLOW[raw]
    except KeyError as exc:
        raise WorkflowExecutionError(f"Unknown Step Functions status: {raw}") from exc


def _start_execution_sync(
    factory: AwsClientFactory,
    *,
    state_machine_arn: str,
    execution_name: str,
    execution_input: dict[str, Any],
) -> dict[str, Any]:
    client = factory.stepfunctions()
    return client.start_execution(
        stateMachineArn=state_machine_arn,
        name=execution_name,
        input=json.dumps(execution_input, separators=(",", ":")),
    )


def _describe_execution_sync(
    factory: AwsClientFactory,
    *,
    execution_arn: str,
) -> dict[str, Any]:
    return factory.stepfunctions().describe_execution(executionArn=execution_arn)


def _validate_definition_sync(
    factory: AwsClientFactory,
    *,
    definition: str,
) -> dict[str, Any]:
    return factory.stepfunctions().validate_state_machine_definition(
        definition=definition,
        type="STANDARD",
    )


async def validate_workflow_definition(
    factory: AwsClientFactory,
    settings: AwsSettings,
    *,
    account_id: str,
) -> dict[str, Any]:
    """Render ASL, run local structural checks, then AWS ValidateStateMachineDefinition."""
    rendered = render_definition(settings, account_id=account_id)
    validate_definition_structure(rendered)

    try:
        response = await asyncio.to_thread(
            _validate_definition_sync,
            factory,
            definition=rendered,
        )
    except (BotoCoreError, ClientError, OSError) as exc:
        logger.warning(
            "AWS ASL validation API call failed",
            extra={
                "aws_region": settings.region,
                "error_type": type(exc).__name__,
            },
        )
        raise AwsConnectivityError(
            "Unable to validate state machine definition via AWS"
        ) from exc

    result = str(response.get("result", "")).upper()
    diagnostics = response.get("diagnostics") or []
    if result and result not in {"OK", "VALID"}:
        raise AwsConfigurationError(
            f"ASL validation failed: result={result}, diagnostics={diagnostics}"
        )

    # Some API versions return result=OK with warning diagnostics only.
    errors = [
        item
        for item in diagnostics
        if isinstance(item, dict) and str(item.get("severity", "")).upper() == "ERROR"
    ]
    if errors:
        raise AwsConfigurationError(f"ASL validation errors: {errors}")

    logger.info(
        "AWS validated migration workflow definition",
        extra={
            "aws_region": settings.region,
            "validation_result": result or "OK",
            "diagnostic_count": len(diagnostics),
        },
    )
    return {
        "result": result or "OK",
        "diagnostics": diagnostics,
        "definition": rendered,
    }


async def start_workflow_execution(
    factory: AwsClientFactory,
    settings: AwsSettings,
    start_input: WorkflowStartInput,
) -> WorkflowExecutionRef:
    """Start a Standard execution named by run_id (idempotent).

    If an execution with the same name already exists, describe and return it.
    """
    if not settings.migration_workflow_arn:
        raise AwsConfigurationError(
            "MIGRATION_WORKFLOW_ARN is required to start workflow executions"
        )

    execution_name = start_input.run_id
    payload = start_input.to_execution_input()

    logger.info(
        "Starting migration workflow execution",
        extra={
            "run_id": start_input.run_id,
            "state_machine_arn": settings.migration_workflow_arn,
            "execution_name": execution_name,
            "artifacts_bucket": start_input.artifacts_bucket,
            # secret ARN is a pointer, not a credential — safe to log
            "connection_secret_arn": start_input.connection_secret_arn,
        },
    )

    try:
        response = await asyncio.to_thread(
            _start_execution_sync,
            factory,
            state_machine_arn=settings.migration_workflow_arn,
            execution_name=execution_name,
            execution_input=payload,
        )
        execution_arn = str(response["executionArn"])
        return WorkflowExecutionRef(
            execution_arn=execution_arn,
            execution_name=execution_name,
            status=WorkflowStatus.RUNNING,
            state_machine_arn=settings.migration_workflow_arn,
            start_date=_iso(response.get("startDate")),
        )
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ExecutionAlreadyExists":
            # Deterministic name = run_id → safe to attach to the existing run.
            existing_arn = (
                settings.migration_workflow_arn.replace(
                    ":stateMachine:",
                    ":execution:",
                )
                + f":{execution_name}"
            )
            # Prefer DescribeExecution when possible; fall back to constructed ARN.
            try:
                return await describe_workflow_execution(factory, existing_arn)
            except WorkflowExecutionError:
                return WorkflowExecutionRef(
                    execution_arn=existing_arn,
                    execution_name=execution_name,
                    status=WorkflowStatus.RUNNING,
                    state_machine_arn=settings.migration_workflow_arn,
                )
        logger.warning(
            "Failed to start workflow execution",
            extra={
                "run_id": start_input.run_id,
                "error_type": type(exc).__name__,
                "error_code": code,
            },
        )
        raise WorkflowExecutionError(
            f"Unable to start workflow for run_id={start_input.run_id}"
        ) from exc
    except (BotoCoreError, OSError) as exc:
        raise WorkflowExecutionError(
            f"Unable to start workflow for run_id={start_input.run_id}"
        ) from exc


async def describe_workflow_execution(
    factory: AwsClientFactory,
    execution_arn: str,
) -> WorkflowExecutionRef:
    try:
        response = await asyncio.to_thread(
            _describe_execution_sync,
            factory,
            execution_arn=execution_arn,
        )
    except (BotoCoreError, ClientError, OSError) as exc:
        raise WorkflowExecutionError(
            f"Unable to describe execution {execution_arn}"
        ) from exc

    name = str(response.get("name") or execution_arn.rsplit(":", 1)[-1])
    return WorkflowExecutionRef(
        execution_arn=str(response["executionArn"]),
        execution_name=name,
        status=_map_status(str(response["status"])),
        state_machine_arn=str(response.get("stateMachineArn") or "") or None,
        start_date=_iso(response.get("startDate")),
        stop_date=_iso(response.get("stopDate")),
        error=str(response["error"]) if response.get("error") else None,
        cause=str(response["cause"]) if response.get("cause") else None,
    )
