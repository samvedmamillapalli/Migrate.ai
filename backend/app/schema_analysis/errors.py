from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError, SQLAlchemyError

from app.core.exceptions import (
    SchemaAuthenticationError,
    SchemaConnectionError,
    SchemaDatabaseNotFoundError,
    SchemaNetworkError,
    SchemaSSLError,
    SchemaTimeoutError,
    UnsupportedDatabaseError,
)


def safe_log_target(host: str, database: str) -> dict[str, str]:
    """Fields that are safe to include in structured logs."""
    return {"host": host, "database": database}


def host_and_database_from_url(database_url: str) -> tuple[str, str]:
    parsed = urlparse(database_url)
    host = parsed.hostname or "unknown"
    database = (parsed.path or "/").lstrip("/") or "unknown"
    return host, database


def is_cockroach_version_parse_error(exc: BaseException) -> bool:
    """Detect SQLAlchemy AssertionError from vanilla PG dialect + CockroachDB."""
    if isinstance(exc, AssertionError) and "Could not determine version" in str(exc):
        return True
    cause = exc.__cause__
    if cause is not None and cause is not exc:
        return is_cockroach_version_parse_error(cause)
    context = exc.__context__
    if context is not None and context is not exc:
        return is_cockroach_version_parse_error(context)
    return False


def translate_schema_error(exc: BaseException) -> SchemaConnectionError | None:
    """Map low-level DB/driver errors to meaningful schema-analysis exceptions.

    Returns ``None`` when the exception is not a connectivity/driver failure.
    """
    if isinstance(exc, SchemaConnectionError):
        return exc

    if isinstance(exc, TimeoutError | asyncio.TimeoutError):
        return SchemaTimeoutError("Schema discovery timed out")

    if isinstance(exc, UnsupportedDatabaseError):
        return exc

    if is_cockroach_version_parse_error(exc):
        # Caller should retry with force_cockroach=True before translating.
        return None

    if isinstance(exc, ValueError):
        message = str(exc)
        lowered = message.lower()
        if "scheme" in lowered or "postgresql-compatible" in lowered:
            return UnsupportedDatabaseError(message)
        if "sslmode" in lowered or "certificate" in lowered or "ssl" in lowered:
            return SchemaSSLError(message)
        return None

    if isinstance(exc, (OperationalError, InterfaceError, DBAPIError)):
        return _translate_driver_error(exc)

    if isinstance(exc, SQLAlchemyError):
        return SchemaConnectionError("Database connection failed")

    # psycopg / OS-level errors sometimes surface without SQLAlchemy wrapping
    message = str(exc)
    lowered = message.lower()
    translated = _classify_message(lowered, message)
    return translated


def _translate_driver_error(exc: BaseException) -> SchemaConnectionError:
    message = str(exc)
    lowered = message.lower()
    classified = _classify_message(lowered, message)
    if classified is not None:
        return classified
    return SchemaConnectionError("Database connection failed")


def _classify_message(lowered: str, original: str) -> SchemaConnectionError | None:
    if any(
        marker in lowered
        for marker in (
            "password authentication failed",
            "authentication failed",
            "invalid password",
            "role \"",
            "role does not exist",
            "28p01",
            "28000",
        )
    ):
        return SchemaAuthenticationError(
            "Invalid database credentials; authentication failed"
        )

    if any(
        marker in lowered
        for marker in (
            "does not exist",
            "3d000",
            "unknown database",
            "no database or schema specified",
            "invalidcatalogname",
            "invalid name",
        )
    ) and (
        "database" in lowered
        or "catalog" in lowered
        or "no database or schema specified" in lowered
    ):
        return SchemaDatabaseNotFoundError(
            "Target database does not exist or is not accessible"
        )

    if any(
        marker in lowered
        for marker in (
            "certificate verify failed",
            "ssl",
            "tls",
            "certificate",
            "wrong version number",
            "sslmode",
            "invalid response to ssl",
        )
    ):
        return SchemaSSLError("SSL connection failed")

    if any(
        marker in lowered
        for marker in (
            "timeout",
            "timed out",
            "connection timed out",
            "canceling statement due to statement timeout",
        )
    ):
        return SchemaTimeoutError("Database connection or statement timed out")

    if any(
        marker in lowered
        for marker in (
            "could not connect",
            "connection refused",
            "network is unreachable",
            "name or service not known",
            "nodename nor servname",
            "getaddrinfo failed",
            "failed to resolve",
            "server closed the connection",
            "connection reset",
            "no route to host",
        )
    ):
        return SchemaNetworkError("Unable to reach database host")

    return None
