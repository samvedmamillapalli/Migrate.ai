"""Phase 4 verification script — not part of the application."""

from __future__ import annotations

import asyncio
import inspect
import sys
import uuid
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.database.models import MigrationRunStatus
from app.database.session import DatabaseSessionManager
from app.dependencies import (
    get_db_session,
    get_migration_run_repository,
    get_migration_run_service,
)
from app.main import app
from app.repositories import BaseRepository, MigrationRunRepository
from app.services import MigrationRunService
from app.services import migration_run_service as svc_mod


def check_imports_and_boundaries() -> None:
    assert BaseRepository is not None
    assert MigrationRunRepository is not None
    assert MigrationRunService is not None
    assert get_db_session is not None
    assert get_migration_run_repository is not None
    assert get_migration_run_service is not None
    print("imports_ok")

    src = inspect.getsource(svc_mod)
    assert "select(" not in src
    assert "session.execute" not in src
    assert "text(" not in src
    assert "MigrationRunRepository" in src
    print("service_boundary_ok")

    for path in Path("app/api").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "from sqlalchemy" not in text and "import sqlalchemy" not in text
        assert "app.repositories" not in text
    print("api_boundary_ok")


def check_startup() -> None:
    with TestClient(app) as client:
        root = client.get("/")
        health = client.get("/health")
        print("root", root.status_code, root.json())
        print(
            "health",
            health.status_code,
            health.json().get("status"),
            "db",
            health.json().get("database"),
        )
        assert root.status_code == 200
        assert health.status_code == 200
        assert health.json()["database"] == "healthy"
        assert getattr(app.state, "database", None) is not None
    print("startup_ok")


async def check_repo_service_flow() -> None:
    # Use a dedicated session manager on this event loop (do not share
    # TestClient's engine across asyncio.run loops).
    db = DatabaseSessionManager(get_settings().database_url.get_secret_value())
    try:
        async for session in db.session():
            repo = MigrationRunRepository(session)
            svc = MigrationRunService(repo, session)

            run = await svc.create_migration_run(
                "  ALTER TABLE t ADD COLUMN x INT  "
            )
            assert run.status == MigrationRunStatus.PENDING
            assert run.migration_sql == "ALTER TABLE t ADD COLUMN x INT"
            run_id = run.id

            got = await svc.get_migration_run(run_id)
            assert got.id == run_id

            listed = await svc.list_migration_runs(
                limit=20,
                status=MigrationRunStatus.PENDING,
            )
            assert any(item.id == run_id for item in listed)

            again = await repo.get_by_id(run_id)
            assert again is not None
            again.migration_sql = "ALTER TABLE t ADD COLUMN y INT"
            updated_entity = await repo.update(again)
            await session.commit()
            assert updated_entity.migration_sql == "ALTER TABLE t ADD COLUMN y INT"

            await svc.update_status(run_id, MigrationRunStatus.PREDICTING)
            await svc.update_status(run_id, MigrationRunStatus.AWAITING_APPROVAL)
            await svc.update_status(run_id, MigrationRunStatus.RUNNING)
            await svc.update_status(run_id, MigrationRunStatus.COMPLETED)

            try:
                await svc.update_status(run_id, MigrationRunStatus.FAILED)
                raise AssertionError("expected ConflictError")
            except ConflictError:
                pass

            missing = uuid.uuid4()
            try:
                await svc.get_migration_run(missing)
                raise AssertionError("expected NotFoundError")
            except NotFoundError:
                pass

            try:
                await svc.create_migration_run("   ")
                raise AssertionError("expected ValidationError")
            except ValidationError:
                pass

            pending = await svc.create_migration_run("SELECT 1")
            pending_id = pending.id
            pending_loaded = await repo.get_by_id_or_raise(pending_id)
            pending_loaded.status = MigrationRunStatus.COMPLETED
            await repo.update(pending_loaded)
            await session.rollback()

            rolled_back = await repo.get_by_id(pending_id)
            assert rolled_back is not None
            assert rolled_back.status == MigrationRunStatus.PENDING
            print("transaction_rollback_ok")

            await svc.delete_migration_run(run_id)
            await svc.delete_migration_run(pending_id)
            assert await repo.get_by_id(run_id) is None
            assert await repo.get_by_id(pending_id) is None
            print("repo_service_flow_ok")
            break
    finally:
        await db.close()


def main() -> None:
    check_imports_and_boundaries()
    check_startup()
    asyncio.run(check_repo_service_flow())
    print("PHASE4_VERIFIED")


if __name__ == "__main__":
    main()
