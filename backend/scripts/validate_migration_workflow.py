"""Validate the Phase 8B migration Step Functions ASL definition.

Runs local structural checks, then AWS ValidateStateMachineDefinition when
AWS clients are available. Does not create the state machine or Lambdas.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow `python scripts/...` from repo root or backend/
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.aws import (  # noqa: E402
    AwsClientFactory,
    AwsConfigurationError,
    get_aws_settings,
    render_definition,
    validate_definition_structure,
    validate_workflow_definition,
)
from app.aws.health import check_aws_connectivity  # noqa: E402
from app.core.logging import get_logger, setup_logging  # noqa: E402

logger = get_logger(__name__)

_PLACEHOLDER_ACCOUNT = "000000000000"


async def _resolve_account_id(factory: AwsClientFactory, configured: str | None) -> str:
    if configured:
        return configured
    identity = await check_aws_connectivity(factory)
    account = str(identity.get("account") or "").strip()
    if account.isdigit() and len(account) == 12:
        return account
    return _PLACEHOLDER_ACCOUNT


async def main(*, aws_validate: bool) -> int:
    settings = get_aws_settings()
    setup_logging("INFO")

    if not settings.aws_enabled:
        # Still validate structure with placeholder ARNs.
        rendered = render_definition(settings, account_id=_PLACEHOLDER_ACCOUNT)
        validate_definition_structure(rendered)
        logger.info("ASL structural validation passed (AWS disabled)")
        print("OK: structural validation passed (AWS_ENABLED=false)")
        return 0

    factory = AwsClientFactory(settings)
    try:
        account_id = await _resolve_account_id(factory, settings.aws_account_id)
        rendered = render_definition(settings, account_id=account_id)
        validate_definition_structure(rendered)
        print("OK: structural validation passed")
        print(f"account_id={account_id}")
        print(f"task_states=DiscoverSchema..Cleanup rendered")

        if not aws_validate:
            return 0

        result = await validate_workflow_definition(
            factory,
            settings,
            account_id=account_id,
        )
        print(f"OK: AWS validation result={result['result']}")
        diagnostics = result.get("diagnostics") or []
        if diagnostics:
            print(f"diagnostics={diagnostics}")
        return 0
    except (AwsConfigurationError, Exception) as exc:
        logger.exception("Workflow validation failed")
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        factory.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Skip AWS ValidateStateMachineDefinition (structural checks only)",
    )
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(main(aws_validate=not args.local_only))
    )
