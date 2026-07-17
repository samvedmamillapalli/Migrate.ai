"""Phase 5 REST API verification — not part of the application."""

from __future__ import annotations

import asyncio
import sys
import uuid

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import DatabaseSessionManager
from app.main import app
from app.repositories.migration_run_repository import MigrationRunRepository
from app.services.migration_run_service import MigrationRunService


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


def main() -> None:
    created_id: str | None = None
    try:
        with TestClient(app) as client:
            # invalid create -> 422
            bad = client.post("/runs", json={"migration_sql": "   "})
            assert bad.status_code == 422, bad.status_code

            # create -> 201
            created = client.post(
                "/runs",
                json={"migration_sql": "  ALTER TABLE t ADD COLUMN c INT  "},
            )
            assert created.status_code == 201, (created.status_code, created.text)
            body = created.json()
            created_id = body["id"]
            assert body["status"] == "pending"
            assert body["migration_sql"] == "ALTER TABLE t ADD COLUMN c INT"
            assert body["schema_discovery_status"] == "pending"

            # get -> 200
            got = client.get(f"/runs/{created_id}")
            assert got.status_code == 200
            assert got.json()["id"] == created_id

            # get missing -> 404
            missing = client.get("/runs/00000000-0000-0000-0000-000000000000")
            assert missing.status_code == 404, missing.status_code

            # list -> 200 with pagination envelope
            listed = client.get("/runs", params={"limit": 10, "offset": 0})
            assert listed.status_code == 200
            payload = listed.json()
            assert "items" in payload and "total" in payload
            assert payload["limit"] == 10 and payload["offset"] == 0
            assert any(item["id"] == created_id for item in payload["items"])
            listed_item = next(
                item for item in payload["items"] if item["id"] == created_id
            )
            assert "schema_snapshot" not in listed_item
            assert listed_item["has_schema_snapshot"] is False
            assert listed_item["schema_discovery_status"] == "pending"

            # list with status filter
            filtered = client.get("/runs", params={"status": "pending"})
            assert filtered.status_code == 200

            # invalid limit -> 422 (FastAPI query validation)
            bad_limit = client.get("/runs", params={"limit": 0})
            assert bad_limit.status_code == 422, bad_limit.status_code

            # patch valid transition -> 200
            patched = client.patch(
                f"/runs/{created_id}", json={"status": "predicting"}
            )
            assert patched.status_code == 200, patched.text
            assert patched.json()["status"] == "predicting"

            # patch invalid transition -> 409
            conflict = client.patch(
                f"/runs/{created_id}", json={"status": "completed"}
            )
            assert conflict.status_code == 409, conflict.status_code

            # patch invalid enum -> 422
            bad_enum = client.patch(f"/runs/{created_id}", json={"status": "nope"})
            assert bad_enum.status_code == 422, bad_enum.status_code
    finally:
        if created_id is not None:
            asyncio.run(_delete_run(uuid.UUID(created_id)))

    print("API_OK", created_id)


if __name__ == "__main__":
    main()
