"""HTTP end-to-end verification for phases 5–10 (mock Bedrock + mock shadow).

Exercises the operator path via FastAPI TestClient:
  fake migration → predict → approve → local lambda chain → grade + memory

Requires DATABASE_URL and ``alembic upgrade head``.

Usage (from backend/):
  python scripts/verify_e2e_http.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ.setdefault("LAMBDA_LOCAL_MODE", "1")
os.environ.setdefault("SHADOW_PROVIDER", "mock")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import DatabaseSessionManager  # noqa: E402
from app.lambdas import HANDLERS  # noqa: E402
from app.lambdas.helpers import connection_from_database_url  # noqa: E402
from app.lambdas.runtime import get_runtime, reset_runtime  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories.migration_run_repository import MigrationRunRepository  # noqa: E402
from app.services.migration_run_service import MigrationRunService  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _delete_run(run_id: uuid.UUID) -> None:
    settings = get_settings()
    database = DatabaseSessionManager(settings.database_url.get_secret_value())
    try:
        async for session in database.session():
            service = MigrationRunService(
                repository=MigrationRunRepository(session),
                session=session,
            )
            await service.delete_migration_run(run_id)
            break
    finally:
        await database.close()


def _run_lambda_chain(run_id: str) -> None:
    settings = get_settings()
    reset_runtime()
    runtime = get_runtime()
    connection = connection_from_database_url(
        settings.database_url.get_secret_value()
    )
    secret_payload = {
        "host": connection.host,
        "port": connection.port,
        "database": connection.database,
        "username": connection.username,
        "password": connection.password.get_secret_value(),
        "ssl_mode": connection.ssl_mode.value,
    }
    secret_arn = asyncio.run(
        runtime.secrets.put_json(
            f"migration-oracle/connections/{run_id}", secret_payload
        )
    )
    base = {
        "run_id": run_id,
        "connection_secret_arn": secret_arn,
        "artifacts_bucket": runtime.settings.shadow_app_tag,
    }
    sr: dict = {}
    sr["discover_schema"] = HANDLERS["discover-schema"]({**base}, None)
    sr["provision_shadow_cluster"] = HANDLERS["provision-shadow-cluster"](
        {**base, "discover_schema": sr["discover_schema"]}, None
    )
    sr["load_schema"] = HANDLERS["load-schema"](
        {**base, "provision_shadow_cluster": sr["provision_shadow_cluster"]},
        None,
    )
    sr["execute_migration"] = HANDLERS["execute-migration"](
        {
            **base,
            "provision_shadow_cluster": sr["provision_shadow_cluster"],
            "load_schema": sr["load_schema"],
        },
        None,
    )
    sr["collect_metrics"] = HANDLERS["collect-metrics"](
        {**base, "execute_migration": sr["execute_migration"]}, None
    )
    sr["persist_results"] = HANDLERS["persist-results"](
        {**base, "step_results": sr}, None
    )
    sr["cleanup"] = HANDLERS["cleanup"](
        {**base, "outcome": {"workflow_failed": False}, "step_results": sr},
        None,
    )
    check(sr["discover_schema"]["status"] == "succeeded", "discover_schema failed")
    check(sr["execute_migration"]["success"] is True, "execute_migration failed")
    check("execution_result_id" in sr["persist_results"], "persist_results missing id")
    check(sr["cleanup"]["destroyed"] is True, "cleanup failed")


def main() -> None:
    run_id: str | None = None
    try:
        with TestClient(app) as client:
            created = client.post(
                "/runs/debug/fake-migration",
                params={"owner_identity": "e2e-verify"},
            )
            check(created.status_code == 201, f"fake-migration: {created.status_code}")
            body = created.json()
            run_id = body["id"]
            check(body["status"] == "pending", "expected pending")
            snap = body.get("schema_snapshot") or {}
            check(snap.get("database_name"), "schema_snapshot missing database_name")

            predicted = client.post(f"/runs/{run_id}/predict")
            check(
                predicted.status_code == 200,
                f"predict: {predicted.status_code} {predicted.text}",
            )
            pred_body = predicted.json()
            check(pred_body["status"] == "awaiting_approval", pred_body["status"])
            expl = pred_body.get("explainability") or {}
            check(expl.get("prediction") is not None, "explainability.prediction missing")

            approved = client.post(
                f"/runs/{run_id}/approve",
                json={
                    "decision": "proceed",
                    "approver_identity": "e2e-verify",
                    "start_workflow": False,
                },
            )
            check(
                approved.status_code == 200,
                f"approve: {approved.status_code} {approved.text}",
            )
            check(approved.json()["status"] == "running", "expected running after proceed")

            _run_lambda_chain(run_id)

            graded = client.get(f"/runs/{run_id}/grade")
            check(graded.status_code == 200, f"grade: {graded.status_code}")
            check(graded.json().get("scalar_accuracy_score") is not None, "grade missing")

            memory = client.get(f"/runs/{run_id}/memory")
            check(memory.status_code == 200, f"memory: {memory.status_code}")
            check(memory.json().get("id"), "memory id missing")

            final = client.get(f"/runs/{run_id}")
            check(final.status_code == 200, "get run failed")
            # Status remains running until workflow finalization/sync marks terminal.
            check(final.json()["status"] in {"running", "completed"}, final.json()["status"])

        print("E2E_HTTP_OK", run_id)
    finally:
        if run_id is not None:
            asyncio.run(_delete_run(uuid.UUID(run_id)))


if __name__ == "__main__":
    main()
