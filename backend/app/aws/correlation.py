"""Request/workflow correlation fields for structured logs.

All workflow logs should include ``run_id``. Optional Lambda and Step Functions
identifiers enable cross-service tracing in CloudWatch.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_run_id: ContextVar[str | None] = ContextVar("correlation_run_id", default=None)
_lambda_request_id: ContextVar[str | None] = ContextVar(
    "correlation_lambda_request_id",
    default=None,
)
_lambda_function_name: ContextVar[str | None] = ContextVar(
    "correlation_lambda_function_name",
    default=None,
)
_sfn_execution_arn: ContextVar[str | None] = ContextVar(
    "correlation_sfn_execution_arn",
    default=None,
)


def get_correlation_fields() -> dict[str, str]:
    fields: dict[str, str] = {}
    run_id = _run_id.get()
    if run_id:
        fields["run_id"] = run_id
    lambda_request_id = _lambda_request_id.get()
    if lambda_request_id:
        fields["lambda_request_id"] = lambda_request_id
    lambda_function_name = _lambda_function_name.get()
    if lambda_function_name:
        fields["lambda_function_name"] = lambda_function_name
    sfn_execution_arn = _sfn_execution_arn.get()
    if sfn_execution_arn:
        fields["sfn_execution_arn"] = sfn_execution_arn
    return fields


@contextmanager
def correlation_context(
    *,
    run_id: str | None = None,
    lambda_request_id: str | None = None,
    lambda_function_name: str | None = None,
    sfn_execution_arn: str | None = None,
) -> Iterator[None]:
    tokens = []
    if run_id is not None:
        tokens.append((_run_id, _run_id.set(run_id)))
    if lambda_request_id is not None:
        tokens.append((_lambda_request_id, _lambda_request_id.set(lambda_request_id)))
    if lambda_function_name is not None:
        tokens.append(
            (_lambda_function_name, _lambda_function_name.set(lambda_function_name))
        )
    if sfn_execution_arn is not None:
        tokens.append((_sfn_execution_arn, _sfn_execution_arn.set(sfn_execution_arn)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
