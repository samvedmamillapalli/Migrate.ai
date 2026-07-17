"""Run Phase 8C Lambda handlers locally end-to-end (mock shadow provider).

Usage (from backend/):

    $env:LAMBDA_LOCAL_MODE=1
    $env:SHADOW_PROVIDER="mock"
    python scripts/run_lambdas_local.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

os.environ["LAMBDA_LOCAL_MODE"] = "1"
os.environ["SHADOW_PROVIDER"] = "mock"

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.config import get_settings  # noqa: E402
from app.core.logging import get_logger, setup_logging  # noqa: E402
from app.database import DatabaseSessionManager  # noqa: E402
from app.lambdas import HANDLERS  # noqa: E402
from app.lambdas.helpers import connection_from_database_url  # noqa: E402
from app.lambdas.runtime import get_runtime, reset_runtime  # noqa: E402
from app.repositories.migration_run_repository import MigrationRunRepository  # noqa: E402
from app.services.migration_run_service import MigrationRunService  # noqa: E402

logger = get_logger(__name__)

LOCAL_MIGRATION_SQL = (
    "ALTER TABLE public.items ADD COLUMN IF NOT EXISTS note TEXT;"
)


async def _create_run(database_url: str) -> str:
    database = DatabaseSessionManager(database_url)
    try:
        async for session in database.session():
            service = MigrationRunService(
                repository=MigrationRunRepository(session),
                session=session,
            )
            run = await service.create_migration_run(LOCAL_MIGRATION_SQL)
            return str(run.id)
    finally:
        await database.close()
    raise RuntimeError("failed to create migration run")


async def _amain() -> int:
    reset_runtime()
    settings = get_settings()
    setup_logging(settings.log_level)

    if settings.shadow_provider.strip().lower() != "mock":
        print(
            "FAIL: set SHADOW_PROVIDER=mock for local Lambda execution",
            file=sys.stderr,
        )
        return 1

    runtime = get_runtime()
    connection = connection_from_database_url(
        settings.database_url.get_secret_value()
    )
    connection_secret = {
        "host": connection.host,
        "port": connection.port,
        "database": connection.database,
        "username": connection.username,
        "password": connection.password.get_secret_value(),
        "ssl_mode": connection.ssl_mode.value,
    }

    run_id = await _create_run(settings.database_url.get_secret_value())
    connection_secret_arn = await runtime.secrets.put_json(
        f"migration-oracle/connections/{run_id}",
        connection_secret,
    )

    print(f"run_id={run_id}")
    print(f"connection_secret_arn={connection_secret_arn}")

    step_results: dict = {}
    base = {
        "run_id": run_id,
        "connection_secret_arn": connection_secret_arn,
        "artifacts_bucket": settings.shadow_app_tag,
    }

    try:
        # Discover
        print("\n==> discover-schema")
        step_results["discover_schema"] = HANDLERS["discover-schema"](
            {**base},
            None,
        )
        print(f"OK discover-schema: {step_results['discover_schema']}")

        # Provision
        print("\n==> provision-shadow-cluster")
        step_results["provision_shadow_cluster"] = HANDLERS[
            "provision-shadow-cluster"
        ](
            {**base, "discover_schema": step_results["discover_schema"]},
            None,
        )
        print(
            "OK provision-shadow-cluster: "
            f"{step_results['provision_shadow_cluster']}"
        )

        # Load
        print("\n==> load-schema")
        step_results["load_schema"] = HANDLERS["load-schema"](
            {
                **base,
                "discover_schema": step_results["discover_schema"],
                "provision_shadow_cluster": step_results["provision_shadow_cluster"],
            },
            None,
        )
        print(f"OK load-schema: {step_results['load_schema']}")

        # Execute
        print("\n==> execute-migration")
        step_results["execute_migration"] = HANDLERS["execute-migration"](
            {
                **base,
                "provision_shadow_cluster": step_results["provision_shadow_cluster"],
                "load_schema": step_results["load_schema"],
            },
            None,
        )
        print(f"OK execute-migration: {step_results['execute_migration']}")

        # Collect
        print("\n==> collect-metrics")
        step_results["collect_metrics"] = HANDLERS["collect-metrics"](
            {
                **base,
                "execute_migration": step_results["execute_migration"],
            },
            None,
        )
        print(f"OK collect-metrics: {step_results['collect_metrics']}")

        # Persist
        print("\n==> persist-results")
        step_results["persist_results"] = HANDLERS["persist-results"](
            {**base, "step_results": step_results},
            None,
        )
        print(f"OK persist-results: {step_results['persist_results']}")

        # Cleanup
        print("\n==> cleanup")
        step_results["cleanup"] = HANDLERS["cleanup"](
            {
                **base,
                "outcome": {"workflow_failed": False},
                "error": None,
                "step_results": step_results,
            },
            None,
        )
        print(f"OK cleanup: {step_results['cleanup']}")

        print("\nAll Phase 8C Lambdas executed locally.")
        return 0
    except Exception as exc:
        logger.exception("Local Lambda run failed")
        print(f"FAIL: {exc}", file=sys.stderr)
        try:
            HANDLERS["cleanup"](
                {
                    "run_id": run_id,
                    "outcome": {"workflow_failed": True},
                    "error": {"Error": type(exc).__name__},
                    "step_results": step_results,
                    "artifacts_bucket": settings.shadow_app_tag,
                },
                None,
            )
        except Exception:  # noqa: BLE001
            pass
        return 1
    finally:
        await runtime.close()
        reset_runtime()


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
