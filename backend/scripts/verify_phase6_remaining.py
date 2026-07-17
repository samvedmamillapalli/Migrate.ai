"""Verify remaining Phase 6 application functionality.

Covers DatabaseConnection, read-only write probe, snapshot persistence, timeouts.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
import traceback
import uuid
from urllib.parse import parse_qs, unquote, urlparse

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text

from app.config import get_settings
from app.core.exceptions import ReadWriteCredentialsError
from app.database import DatabaseSessionManager
from app.database.models import SchemaDiscoveryStatus
from app.repositories.migration_run_repository import MigrationRunRepository
from app.schema_analysis import (
    DatabaseConnection,
    SchemaAnalysisConnection,
    SslMode,
    assert_read_only_connection,
)
from app.services.migration_run_service import MigrationRunService
from app.services.schema_discovery_service import SchemaDiscoveryService


def _parse_app_url(database_url: str) -> DatabaseConnection:
    parsed = urlparse(database_url)
    query = parse_qs(parsed.query)
    sslmode = (query.get("sslmode", ["require"])[0] or "require").lower()
    try:
        ssl_mode = SslMode(sslmode)
    except ValueError:
        ssl_mode = SslMode.REQUIRE
    return DatabaseConnection(
        host=parsed.hostname or "localhost",
        port=parsed.port or 26257,
        database=(parsed.path or "/").lstrip("/") or "defaultdb",
        username=unquote(parsed.username or "root"),
        password=unquote(parsed.password or ""),
        ssl_mode=ssl_mode,
    )


async def _ensure_readonly_user(
    admin_url: str,
    *,
    username: str,
    password: str,
    database: str,
    admin_username: str,
) -> None:
    async with SchemaAnalysisConnection(admin_url) as admin:
        async with admin.connection() as conn:
            await conn.execute(
                text(f"CREATE USER IF NOT EXISTS {username} WITH PASSWORD :password"),
                {"password": password},
            )
            await conn.execute(
                text(f"ALTER USER {username} WITH PASSWORD :password"),
                {"password": password},
            )
            # PUBLIC CREATE on schema public makes every role write-capable.
            # Revoke it for the duration of this verification and restore later.
            await conn.execute(text("REVOKE CREATE ON SCHEMA public FROM public"))
            await conn.execute(
                text(f"GRANT CREATE ON SCHEMA public TO {admin_username}")
            )
            statements = (
                f"REVOKE ALL ON DATABASE {database} FROM {username}",
                f"REVOKE ALL ON SCHEMA public FROM {username}",
                f"GRANT CONNECT ON DATABASE {database} TO {username}",
                f"GRANT USAGE ON SCHEMA public TO {username}",
                f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {username}",
            )
            for stmt in statements:
                try:
                    await conn.execute(text(stmt))
                except Exception:
                    await conn.rollback()
            await conn.commit()


async def _restore_public_create(admin_url: str) -> None:
    async with SchemaAnalysisConnection(admin_url) as admin:
        async with admin.connection() as conn:
            await conn.execute(text("GRANT CREATE ON SCHEMA public TO public"))
            await conn.commit()


async def _drop_user_if_exists(admin_url: str, username: str) -> None:
    async with SchemaAnalysisConnection(admin_url) as admin:
        async with admin.connection() as conn:
            try:
                await conn.execute(text(f"DROP USER IF EXISTS {username}"))
                await conn.commit()
            except Exception:
                await conn.rollback()


async def main() -> None:
    report: dict = {"ok": False}
    settings = get_settings()
    admin_url = settings.database_url.get_secret_value()
    admin_conn = _parse_app_url(admin_url)
    readonly_user = "mo_readonly_probe"
    created_run_id: uuid.UUID | None = None

    # --- DatabaseConnection URL builder / redaction ---
    built = admin_conn.to_database_url()
    assert "://" in built and admin_conn.host in built
    assert admin_conn.password.get_secret_value() not in admin_conn.redacted_label()
    assert "***" in repr(admin_conn)
    assert settings.schema_connection_timeout_seconds >= 1
    assert settings.schema_discovery_timeout_seconds >= 1
    report["database_connection"] = {
        "redacted_label": admin_conn.redacted_label(),
        "url_scheme": built.split("://", 1)[0],
        "password_in_repr": admin_conn.password.get_secret_value() in repr(admin_conn),
    }
    assert report["database_connection"]["password_in_repr"] is False

    # --- Write probe rejects writable credentials ---
    async with SchemaAnalysisConnection(admin_url) as writable:
        await writable.ping()
        async with writable.connection() as conn:
            try:
                await assert_read_only_connection(conn)
                raise AssertionError("expected ReadWriteCredentialsError for writable user")
            except ReadWriteCredentialsError:
                pass
    report["write_probe_rejects_writable"] = True

    # --- Read-only user discovery + persistence ---
    readonly_password = secrets.token_urlsafe(24)
    await _ensure_readonly_user(
        admin_url,
        username=readonly_user,
        password=readonly_password,
        database=admin_conn.database,
        admin_username=admin_conn.username,
    )

    readonly = DatabaseConnection(
        host=admin_conn.host,
        port=admin_conn.port,
        database=admin_conn.database,
        username=readonly_user,
        password=readonly_password,
        ssl_mode=admin_conn.ssl_mode,
    )

    database = DatabaseSessionManager(admin_url)
    try:
        async for session in database.session():
            repo = MigrationRunRepository(session)
            run_service = MigrationRunService(repository=repo, session=session)
            discovery = SchemaDiscoveryService(
                repository=repo,
                session=session,
                settings=settings,
            )

            run = await run_service.create_migration_run(
                "ALTER TABLE migration_runs ADD COLUMN IF NOT EXISTS probe INT"
            )
            created_run_id = run.id

            # Writable credentials through service must be rejected and marked rejected.
            try:
                await discovery.discover_and_persist(run.id, admin_conn)
                raise AssertionError("service should reject writable credentials")
            except ReadWriteCredentialsError:
                pass

            rejected = await repo.get_by_id_or_raise(run.id)
            assert rejected.schema_discovery_status == SchemaDiscoveryStatus.REJECTED
            assert rejected.schema_snapshot is None
            report["service_rejects_writable"] = True

            # Read-only path should succeed and persist JSONB snapshot.
            updated = await discovery.discover_and_persist(run.id, readonly)
            assert updated.schema_discovery_status == SchemaDiscoveryStatus.SUCCEEDED
            assert isinstance(updated.schema_snapshot, dict)
            assert updated.schema_snapshot.get("database_name")
            assert updated.schema_discovered_at is not None
            assert updated.schema_discovery_duration_ms is not None
            assert updated.schema_discovery_duration_ms >= 0
            assert updated.schema_database_engine in {"cockroachdb", "postgresql", "unknown"}
            assert updated.schema_database_version
            report["discovery_persisted"] = {
                "run_id": str(updated.id),
                "status": updated.schema_discovery_status.value,
                "engine": updated.schema_database_engine,
                "duration_ms": updated.schema_discovery_duration_ms,
                "table_count": updated.schema_snapshot.get("table_count"),
            }

            await run_service.delete_migration_run(run.id)
            created_run_id = None
            break
    finally:
        if created_run_id is not None:
            try:
                async for session in database.session():
                    service = MigrationRunService(
                        repository=MigrationRunRepository(session),
                        session=session,
                    )
                    await service.delete_migration_run(created_run_id)
                    break
            except Exception:
                pass
        await database.close()
        await _drop_user_if_exists(admin_url, readonly_user)
        await _restore_public_create(admin_url)

    report["ok"] = True
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(),
                },
                indent=2,
            )
        )
        raise SystemExit(1) from exc
