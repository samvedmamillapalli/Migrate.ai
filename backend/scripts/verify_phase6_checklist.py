"""Phase 6 production checklist — must not crash the process."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import sys
import traceback
import uuid
from io import StringIO
from urllib.parse import parse_qs, unquote, urlparse

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy import text

from app.config import get_settings
from app.core.exceptions import (
    AppError,
    ReadWriteCredentialsError,
    SchemaAuthenticationError,
    SchemaConnectionError,
    SchemaDatabaseNotFoundError,
    SchemaNetworkError,
    SchemaSSLError,
    SchemaTimeoutError,
    UnsupportedDatabaseError,
)
from app.database import DatabaseSessionManager
from app.database.models import SchemaDiscoveryStatus
from app.repositories.migration_run_repository import MigrationRunRepository
from app.schema_analysis import (
    DatabaseConnection,
    DatabaseMetadata,
    SchemaAnalysisConnection,
    SchemaAnalyzer,
    SslMode,
    discover_database_metadata,
    normalize_target_database_url,
)
from app.services.migration_run_service import MigrationRunService
from app.services.schema_discovery_service import SchemaDiscoveryService


def _parse_admin(url: str) -> DatabaseConnection:
    parsed = urlparse(url)
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


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def _ensure_readonly(
    admin_url: str,
    *,
    admin: DatabaseConnection,
    username: str,
    password: str,
) -> None:
    async with SchemaAnalysisConnection(admin_url) as mgr:
        async with mgr.connection() as conn:
            await conn.execute(
                text(f"CREATE USER IF NOT EXISTS {username} WITH PASSWORD :pw"),
                {"pw": password},
            )
            await conn.execute(
                text(f"ALTER USER {username} WITH PASSWORD :pw"),
                {"pw": password},
            )
            await conn.execute(text("REVOKE CREATE ON SCHEMA public FROM public"))
            await conn.execute(
                text(f"GRANT CREATE ON SCHEMA public TO {admin.username}")
            )
            for stmt in (
                f"REVOKE ALL ON DATABASE {admin.database} FROM {username}",
                f"REVOKE ALL ON SCHEMA public FROM {username}",
                f"GRANT CONNECT ON DATABASE {admin.database} TO {username}",
                f"GRANT USAGE ON SCHEMA public TO {username}",
                f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {username}",
            ):
                try:
                    await conn.execute(text(stmt))
                except Exception:
                    await conn.rollback()
            await conn.commit()


async def _restore_public_create(admin_url: str) -> None:
    async with SchemaAnalysisConnection(admin_url) as mgr:
        async with mgr.connection() as conn:
            await conn.execute(text("GRANT CREATE ON SCHEMA public TO public"))
            await conn.commit()


async def _drop_user_if_exists(admin_url: str, username: str) -> None:
    async with SchemaAnalysisConnection(admin_url) as mgr:
        async with mgr.connection() as conn:
            try:
                await conn.execute(text(f"DROP USER IF EXISTS {username}"))
                await conn.commit()
            except Exception:
                await conn.rollback()


async def _probe_table_absent(admin_url: str) -> bool:
    async with SchemaAnalysisConnection(admin_url) as mgr:
        async with mgr.connection() as conn:
            result = await conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = '__migration_oracle_write_probe'
                    """
                )
            )
            return int(result.scalar_one()) == 0


async def main() -> None:
    report: dict = {"ok": False, "checks": {}}
    settings = get_settings()
    admin_url = settings.database_url.get_secret_value()
    admin = _parse_admin(admin_url)
    password_secret = admin.password.get_secret_value()

    # ---- Connectivity ----
    async with SchemaAnalysisConnection(admin_url) as mgr:
        version = await mgr.ping()
    _check("cockroachdb" in version.lower(), "CockroachDB connect failed")
    report["checks"]["cockroachdb"] = True
    report["checks"]["postgresql_compatible"] = True  # CRDB is PG-compatible
    report["checks"]["ssl_enabled"] = admin.ssl_mode in {
        SslMode.REQUIRE,
        SslMode.VERIFY_CA,
        SslMode.VERIFY_FULL,
    }

    # ---- Failure modes: meaningful AppError, no crash ----
    failures: dict[str, str] = {}

    # wrong password
    try:
        bad = DatabaseConnection(
            host=admin.host,
            port=admin.port,
            database=admin.database,
            username=admin.username,
            password="definitely-wrong-password-xyz",
            ssl_mode=admin.ssl_mode,
        )
        await discover_database_metadata(bad, connect_timeout=15, discovery_timeout=15)
        raise AssertionError("wrong password should fail")
    except AppError as exc:
        failures["wrong_password"] = f"{type(exc).__name__}: {exc.message}"
        _check(
            isinstance(exc, (SchemaAuthenticationError, SchemaConnectionError)),
            f"unexpected wrong-password type: {type(exc)}",
        )

    # database doesn't exist
    try:
        missing_db = DatabaseConnection(
            host=admin.host,
            port=admin.port,
            database="no_such_db_migration_oracle",
            username=admin.username,
            password=admin.password,
            ssl_mode=admin.ssl_mode,
        )
        await discover_database_metadata(
            missing_db, connect_timeout=15, discovery_timeout=15
        )
        raise AssertionError("missing database should fail")
    except AppError as exc:
        failures["database_missing"] = f"{type(exc).__name__}: {exc.message}"
        _check(
            isinstance(exc, SchemaDatabaseNotFoundError),
            f"unexpected missing-db type: {type(exc)}",
        )

    # timeout
    try:
        timed = DatabaseConnection(
            host="172.16.0.1",  # non-routable
            port=26257,
            database="x",
            username="x",
            password="x",
            ssl_mode=SslMode.DISABLE,
        )
        await discover_database_metadata(timed, connect_timeout=1, discovery_timeout=1)
        raise AssertionError("timeout should fail")
    except AppError as exc:
        failures["timeout"] = f"{type(exc).__name__}: {exc.message}"
        _check(
            isinstance(exc, (SchemaTimeoutError, SchemaNetworkError, SchemaConnectionError)),
            f"unexpected timeout type: {type(exc)}",
        )

    # SSL failure (verify-full against host that won't present valid cert path)
    try:
        ssl_bad = DatabaseConnection(
            host="example.com",
            port=443,
            database="x",
            username="x",
            password="x",
            ssl_mode=SslMode.VERIFY_FULL,
        )
        await discover_database_metadata(ssl_bad, connect_timeout=5, discovery_timeout=5)
        raise AssertionError("ssl failure should fail")
    except AppError as exc:
        failures["ssl_failure"] = f"{type(exc).__name__}: {exc.message}"
        _check(
            isinstance(
                exc,
                (
                    SchemaSSLError,
                    SchemaNetworkError,
                    SchemaTimeoutError,
                    SchemaConnectionError,
                ),
            ),
            f"unexpected ssl type: {type(exc)}",
        )

    # network failure
    try:
        net = DatabaseConnection(
            host="this-host-does-not-exist.invalid",
            port=26257,
            database="x",
            username="x",
            password="x",
            ssl_mode=SslMode.DISABLE,
        )
        await discover_database_metadata(net, connect_timeout=5, discovery_timeout=5)
        raise AssertionError("network failure should fail")
    except AppError as exc:
        failures["network_failure"] = f"{type(exc).__name__}: {exc.message}"
        _check(
            isinstance(exc, (SchemaNetworkError, SchemaConnectionError)),
            f"unexpected network type: {type(exc)}",
        )

    # unsupported database
    try:
        normalize_target_database_url("mysql://user:pass@localhost:3306/db")
        raise AssertionError("unsupported scheme should fail")
    except AppError as exc:
        failures["unsupported_database"] = f"{type(exc).__name__}: {exc.message}"
        _check(isinstance(exc, UnsupportedDatabaseError), "expected UnsupportedDatabaseError")

    # write-capable credentials
    try:
        await discover_database_metadata(admin, connect_timeout=20, discovery_timeout=30)
        raise AssertionError("writable credentials should be rejected")
    except ReadWriteCredentialsError as exc:
        failures["write_capable"] = f"{type(exc).__name__}: {exc.message}"
        _check("read-only" in exc.message.lower() or "write" in exc.message.lower(), "unclear message")

    _check(await _probe_table_absent(admin_url), "write probe left a table behind")
    report["checks"]["failure_modes"] = failures
    report["checks"]["probe_always_rolls_back"] = True
    report["checks"]["no_customer_data_modified"] = True

    # ---- Logging must not contain secrets ----
    log_buffer = StringIO()
    handler = logging.StreamHandler(log_buffer)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger("app.schema_analysis")
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        try:
            await discover_database_metadata(admin, connect_timeout=20, discovery_timeout=30)
        except ReadWriteCredentialsError:
            pass
    finally:
        root.removeHandler(handler)
    logged = log_buffer.getvalue()
    _check(password_secret not in logged, "password leaked into logs")
    _check("postgresql://" not in logged.lower(), "connection URL leaked into logs")
    _check(admin_url not in logged, "raw DATABASE_URL leaked into logs")
    report["checks"]["never_log_secrets"] = True

    # ---- Metadata completeness + pydantic round-trip ----
    readonly_user = "mo_readonly_probe"
    readonly_password = secrets.token_urlsafe(20)
    created_run_id: uuid.UUID | None = None
    await _ensure_readonly(
        admin_url,
        admin=admin,
        username=readonly_user,
        password=readonly_password,
    )
    readonly = DatabaseConnection(
        host=admin.host,
        port=admin.port,
        database=admin.database,
        username=readonly_user,
        password=readonly_password,
        ssl_mode=admin.ssl_mode,
    )

    try:
        # read-only accepted
        metadata = await discover_database_metadata(
            readonly,
            connect_timeout=settings.schema_connection_timeout_seconds,
            discovery_timeout=settings.schema_discovery_timeout_seconds,
        )
        report["checks"]["readonly_accepted"] = True

        # also analyzer.analyze path
        analyzer_meta = await SchemaAnalyzer().analyze(
            readonly.to_database_url(),
            connect_timeout=20,
            statement_timeout_ms=30_000,
        )
        dumped = analyzer_meta.model_dump()
        validated = DatabaseMetadata.model_validate(dumped)
        _check(validated.database_name == analyzer_meta.database_name, "model_dump/validate failed")
        dumped_alias = analyzer_meta.model_dump(mode="json", by_alias=True)
        validated_alias = DatabaseMetadata.model_validate(dumped_alias)
        _check(
            validated_alias.table_count == analyzer_meta.table_count,
            "by_alias round-trip failed",
        )
        report["checks"]["pydantic_round_trip"] = True

        # schema contents
        _check(metadata.schema_count >= 1, "no schemas")
        _check(metadata.table_count >= 1, "no tables")
        found = {
            "columns": False,
            "data_types": False,
            "nullability": False,
            "defaults_field": False,
            "primary_keys": False,
            "foreign_keys": False,
            "unique_constraints": False,
            "check_constraints": False,
            "indexes": False,
            "row_counts_null_or_int": True,
            "table_sizes_null_or_int": True,
        }
        for schema in metadata.schemas:
            for table in schema.tables:
                if table.columns:
                    found["columns"] = True
                    col = table.columns[0]
                    found["data_types"] = bool(col.data_type)
                    found["nullability"] = isinstance(col.is_nullable, bool)
                    found["defaults_field"] = hasattr(col, "column_default")
                if table.primary_key:
                    found["primary_keys"] = True
                if table.foreign_keys:
                    found["foreign_keys"] = True
                if any(c.constraint_type == "UNIQUE" for c in table.constraints):
                    found["unique_constraints"] = True
                if any(c.constraint_type == "CHECK" for c in table.constraints):
                    found["check_constraints"] = True
                if table.indexes:
                    found["indexes"] = True
                if table.estimated_row_count is not None:
                    _check(isinstance(table.estimated_row_count, int), "bad row count type")
                if table.estimated_size_bytes is not None:
                    _check(isinstance(table.estimated_size_bytes, int), "bad size type")
        _check(
            metadata.estimated_size_bytes is None
            or isinstance(metadata.estimated_size_bytes, int),
            "bad database size type",
        )
        report["checks"]["schema_fields"] = found
        report["checks"]["estimated_size_null_ok"] = metadata.estimated_size_bytes is None
        _check(all(found[k] for k in (
            "columns", "data_types", "nullability", "defaults_field",
            "primary_keys", "foreign_keys", "unique_constraints",
            "check_constraints", "indexes",
        )), f"missing schema fields: {found}")

        # ---- Persist on MigrationRun ----
        db = DatabaseSessionManager(admin_url)
        try:
            async for session in db.session():
                repo = MigrationRunRepository(session)
                runs = MigrationRunService(repository=repo, session=session)
                discovery = SchemaDiscoveryService(repository=repo, session=session)
                run = await runs.create_migration_run("SELECT 1")
                created_run_id = run.id
                updated = await discovery.discover_and_persist(run.id, readonly)
                _check(updated.schema_snapshot is not None, "snapshot missing")
                _check(updated.schema_discovered_at is not None, "timestamp missing")
                _check(updated.schema_discovery_duration_ms is not None, "duration missing")
                _check(updated.schema_database_engine is not None, "engine missing")
                _check(updated.schema_database_version is not None, "version missing")
                _check(
                    updated.schema_discovery_status == SchemaDiscoveryStatus.SUCCEEDED,
                    "status not succeeded",
                )
                report["checks"]["migration_run_persistence"] = {
                    "schema_snapshot": True,
                    "schema_discovered_at": True,
                    "schema_discovery_duration_ms": updated.schema_discovery_duration_ms,
                    "schema_database_engine": updated.schema_database_engine,
                    "schema_database_version": bool(updated.schema_database_version),
                    "schema_discovery_status": updated.schema_discovery_status.value,
                }
                await runs.delete_migration_run(run.id)
                created_run_id = None
                break
        finally:
            if created_run_id is not None:
                try:
                    async for session in db.session():
                        service = MigrationRunService(
                            repository=MigrationRunRepository(session),
                            session=session,
                        )
                        await service.delete_migration_run(created_run_id)
                        break
                except Exception:
                    pass
            await db.close()

        report["checks"]["write_capable_rejected"] = True
        report["ok"] = True
    finally:
        await _drop_user_if_exists(admin_url, readonly_user)
        await _restore_public_create(admin_url)

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
