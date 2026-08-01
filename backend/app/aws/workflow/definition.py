"""Load, render, and structurally validate the migration workflow ASL."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.aws.config import AwsSettings
from app.aws.exceptions import AwsConfigurationError
from app.aws.workflow.models import (
    LAMBDA_SUBSTITUTIONS,
    WORKFLOW_CONTROL_STATES,
    WORKFLOW_TASK_STATES,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

# infra/stepfunctions/migration_workflow.asl.json relative to repo root
_ASL_PATH = (
    Path(__file__).resolve().parents[4]
    / "infra"
    / "stepfunctions"
    / "migration_workflow.asl.json"
)

_PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Za-z0-9_]+)\}")
_LAMBDA_ARN_PATTERN = re.compile(
    r"^arn:aws:lambda:[a-z0-9-]+:\d{12}:function:[A-Za-z0-9_-]+$"
)


def asl_template_path() -> Path:
    return _ASL_PATH


def load_asl_template(path: Path | None = None) -> str:
    template_path = path or asl_template_path()
    if not template_path.is_file():
        raise AwsConfigurationError(
            f"Step Functions ASL template not found: {template_path}"
        )
    return template_path.read_text(encoding="utf-8")


def build_lambda_arn(
    *,
    region: str,
    account_id: str,
    function_prefix: str,
    function_suffix: str,
    explicit_arn: str | None = None,
) -> str:
    if explicit_arn:
        return explicit_arn.strip()
    return (
        f"arn:aws:lambda:{region}:{account_id}:function:"
        f"{function_prefix}-{function_suffix}"
    )


def resolve_lambda_arns(
    settings: AwsSettings,
    *,
    account_id: str,
) -> dict[str, str]:
    """Map ASL substitution keys to concrete Lambda ARNs (placeholders until 8C)."""
    explicit = {
        "DiscoverSchemaFunctionArn": settings.lambda_discover_schema_arn,
        "ProvisionShadowClusterFunctionArn": settings.lambda_provision_shadow_cluster_arn,
        "LoadSchemaFunctionArn": settings.lambda_load_schema_arn,
        "ExecuteMigrationFunctionArn": settings.lambda_execute_migration_arn,
        "CollectMetricsFunctionArn": settings.lambda_collect_metrics_arn,
        "PersistResultsFunctionArn": settings.lambda_persist_results_arn,
        "CleanupFunctionArn": settings.lambda_cleanup_arn,
    }
    resolved: dict[str, str] = {}
    for key, suffix in LAMBDA_SUBSTITUTIONS.items():
        arn = build_lambda_arn(
            region=settings.region,
            account_id=account_id,
            function_prefix=settings.lambda_function_prefix,
            function_suffix=suffix,
            explicit_arn=explicit[key],
        )
        if not _LAMBDA_ARN_PATTERN.match(arn):
            raise AwsConfigurationError(f"Invalid Lambda ARN for {key}: {arn}")
        resolved[key] = arn
    return resolved


def render_definition(
    settings: AwsSettings,
    *,
    account_id: str,
    template: str | None = None,
) -> str:
    """Substitute Lambda ARNs into the ASL template and return JSON text."""
    raw = template if template is not None else load_asl_template()
    substitutions = resolve_lambda_arns(settings, account_id=account_id)
    rendered = raw
    for key, value in substitutions.items():
        rendered = rendered.replace(f"${{{key}}}", value)

    unresolved = sorted(set(_PLACEHOLDER_PATTERN.findall(rendered)))
    if unresolved:
        raise AwsConfigurationError(
            "Unresolved ASL placeholders: " + ", ".join(unresolved)
        )

    # Ensure rendered document is valid JSON before AWS validation.
    json.loads(rendered)
    logger.info(
        "Rendered migration workflow definition",
        extra={
            "aws_region": settings.region,
            "lambda_function_prefix": settings.lambda_function_prefix,
            "substitution_count": len(substitutions),
        },
    )
    return rendered


def validate_definition_structure(definition_json: str) -> dict[str, Any]:
    """Local structural checks before calling AWS ValidateStateMachineDefinition."""
    try:
        document = json.loads(definition_json)
    except json.JSONDecodeError as exc:
        raise AwsConfigurationError(f"ASL is not valid JSON: {exc}") from exc

    if not isinstance(document, dict):
        raise AwsConfigurationError("ASL root must be a JSON object")

    start_at = document.get("StartAt")
    states = document.get("States")
    if not isinstance(start_at, str) or not start_at:
        raise AwsConfigurationError("ASL StartAt must be a non-empty string")
    if not isinstance(states, dict) or not states:
        raise AwsConfigurationError("ASL States must be a non-empty object")
    if start_at not in states:
        raise AwsConfigurationError(f"ASL StartAt '{start_at}' is not defined in States")

    missing_tasks = [name for name in WORKFLOW_TASK_STATES if name not in states]
    if missing_tasks:
        raise AwsConfigurationError(
            "ASL missing required task states: " + ", ".join(missing_tasks)
        )

    missing_control = [name for name in WORKFLOW_CONTROL_STATES if name not in states]
    if missing_control:
        raise AwsConfigurationError(
            "ASL missing required control states: " + ", ".join(missing_control)
        )

    cleanup = states["Cleanup"]
    if not isinstance(cleanup, dict) or cleanup.get("Type") != "Task":
        raise AwsConfigurationError("Cleanup must be a Task state")

    # Guaranteed cleanup: every task except Cleanup itself must Catch → MarkFailed
    for name in WORKFLOW_TASK_STATES:
        if name == "Cleanup":
            continue
        state = states[name]
        catch = state.get("Catch") if isinstance(state, dict) else None
        if not isinstance(catch, list) or not catch:
            raise AwsConfigurationError(f"State {name} must define a Catch path")
        next_states = {entry.get("Next") for entry in catch if isinstance(entry, dict)}
        if "MarkFailed" not in next_states:
            raise AwsConfigurationError(
                f"State {name} Catch must route to MarkFailed for guaranteed cleanup"
            )

    mark_failed = states["MarkFailed"]
    if mark_failed.get("Next") != "Cleanup":
        raise AwsConfigurationError("MarkFailed must Next to Cleanup")

    mark_succeeded = states["MarkSucceeded"]
    if mark_succeeded.get("Next") != "Cleanup":
        raise AwsConfigurationError("MarkSucceeded must Next to Cleanup")

    # Each task state should declare Retry with backoff
    for name in WORKFLOW_TASK_STATES:
        state = states[name]
        retry = state.get("Retry") if isinstance(state, dict) else None
        if not isinstance(retry, list) or not retry:
            raise AwsConfigurationError(f"State {name} must define Retry policies")
        first = retry[0]
        if not isinstance(first, dict):
            raise AwsConfigurationError(f"State {name} Retry entry must be an object")
        if "BackoffRate" not in first or "IntervalSeconds" not in first:
            raise AwsConfigurationError(
                f"State {name} Retry must include IntervalSeconds and BackoffRate"
            )

    logger.info(
        "ASL structural validation passed",
        extra={
            "task_state_count": len(WORKFLOW_TASK_STATES),
            "total_state_count": len(states),
            "start_at": start_at,
        },
    )
    return document
