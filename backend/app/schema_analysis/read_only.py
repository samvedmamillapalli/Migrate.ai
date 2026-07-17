from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.exceptions import ReadWriteCredentialsError
from app.core.logging import get_logger

logger = get_logger(__name__)

_PROBE_TABLE = "__migration_oracle_write_probe"

# PostgreSQL / CockroachDB SQLSTATEs that indicate the user cannot write.
_READONLY_SQLSTATES = frozenset(
    {
        "42501",  # insufficient_privilege
        "25006",  # read_only_sql_transaction
        "0A000",  # feature_not_supported (some read-only replicas)
    }
)

_READONLY_MESSAGE_MARKERS = (
    "read-only",
    "readonly",
    "read only",
    "permission denied",
    "not authorized",
    "insufficient privilege",
    "insufficient_privilege",
    "must be owner",
)


async def assert_read_only_connection(connection: AsyncConnection) -> None:
    """Reject credentials that can perform writes.

    Checks:
    1. Active ``CREATE TABLE`` probe inside a transaction that is always rolled back.
    2. Privilege scan for INSERT/UPDATE/DELETE/TRUNCATE (includes role/PUBLIC grants).
    3. Database-level CREATE privilege.

    If any write capability is detected, raises ``ReadWriteCredentialsError``.
    """
    if connection.in_transaction():
        await connection.rollback()

    await _assert_no_ddl_capability(connection)
    await _assert_no_write_privileges(connection)


async def enforce_session_read_only(connection: AsyncConnection) -> None:
    """Force the session into read-only mode for subsequent discovery queries."""
    try:
        await connection.execute(text("SET default_transaction_read_only = on"))
        await connection.commit()
    except Exception:
        await connection.rollback()
        logger.warning(
            "Unable to set default_transaction_read_only; continuing without it"
        )


async def _assert_no_ddl_capability(connection: AsyncConnection) -> None:
    write_succeeded = False
    transaction = await connection.begin()
    try:
        await connection.execute(
            text(
                f'CREATE TABLE "{_PROBE_TABLE}" ('
                "id INT PRIMARY KEY"
                ")"
            )
        )
        write_succeeded = True
    except Exception as exc:
        if _is_read_only_rejection(exc):
            logger.info(
                "Write probe rejected write access (credentials appear read-only)"
            )
        else:
            raise
    finally:
        await transaction.rollback()

    if write_succeeded:
        await _drop_probe_table_if_present(connection)
        raise ReadWriteCredentialsError(
            "Database credentials allow writes; provide a read-only user"
        )


async def _assert_no_write_privileges(connection: AsyncConnection) -> None:
    """Reject users that hold write privileges even when CREATE is denied."""
    try:
        has_db_create = (
            await connection.execute(
                text(
                    "SELECT has_database_privilege("
                    "current_user, current_database(), 'CREATE')"
                )
            )
        ).scalar_one()
        if bool(has_db_create):
            raise ReadWriteCredentialsError(
                "Database credentials allow writes; provide a read-only user"
            )
    except ReadWriteCredentialsError:
        raise
    except Exception as exc:
        await connection.rollback()
        if not _is_read_only_rejection(exc):
            logger.info(
                "Unable to inspect database CREATE privilege; continuing with table scan"
            )

    # Single set-based scan with quote_ident so mixed-case / reserved names work
    # and a failure cannot silently skip remaining tables.
    try:
        has_write = (
            await connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.tables AS t
                        WHERE t.table_type = 'BASE TABLE'
                          AND t.table_schema NOT IN (
                              'pg_catalog',
                              'information_schema',
                              'crdb_internal',
                              'pg_extension'
                          )
                          AND (
                              has_table_privilege(
                                  current_user,
                                  quote_ident(t.table_schema)
                                      || '.'
                                      || quote_ident(t.table_name),
                                  'INSERT'
                              )
                              OR has_table_privilege(
                                  current_user,
                                  quote_ident(t.table_schema)
                                      || '.'
                                      || quote_ident(t.table_name),
                                  'UPDATE'
                              )
                              OR has_table_privilege(
                                  current_user,
                                  quote_ident(t.table_schema)
                                      || '.'
                                      || quote_ident(t.table_name),
                                  'DELETE'
                              )
                              OR has_table_privilege(
                                  current_user,
                                  quote_ident(t.table_schema)
                                      || '.'
                                      || quote_ident(t.table_name),
                                  'TRUNCATE'
                              )
                          )
                    )
                    """
                )
            )
        ).scalar_one()
    except Exception as exc:
        await connection.rollback()
        logger.info(
            "Unable to inspect table write privileges; relying on DDL probe",
            extra={"error": type(exc).__name__},
        )
        return

    if bool(has_write):
        raise ReadWriteCredentialsError(
            "Database credentials allow writes; provide a read-only user"
        )


def _is_read_only_rejection(exc: BaseException) -> bool:
    sqlstate = _extract_sqlstate(exc)
    if sqlstate in _READONLY_SQLSTATES:
        return True

    message = str(exc).lower()
    return any(marker in message for marker in _READONLY_MESSAGE_MARKERS)


def _extract_sqlstate(exc: BaseException) -> str | None:
    if isinstance(exc, DBAPIError) and exc.orig is not None:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate:
            return str(sqlstate)
        pgcode = getattr(exc.orig, "pgcode", None)
        if pgcode:
            return str(pgcode)
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate:
        return str(sqlstate)
    return None


async def _drop_probe_table_if_present(connection: AsyncConnection) -> None:
    """Best-effort cleanup if transactional DDL did not roll back the probe table."""
    try:
        await connection.execute(text(f'DROP TABLE IF EXISTS "{_PROBE_TABLE}"'))
        await connection.commit()
    except Exception:
        await connection.rollback()
        logger.warning("Unable to drop leftover write-probe table")
