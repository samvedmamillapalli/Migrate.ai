from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import TracebackType
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse, urlunparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.core.exceptions import SchemaSSLError, UnsupportedDatabaseError
from app.core.logging import get_logger
from app.database.session import resolve_cockroach_ca_cert
from app.schema_analysis.errors import host_and_database_from_url, safe_log_target

logger = get_logger(__name__)

_SECURE_SSL_MODES = frozenset({"verify-ca", "verify-full"})
_SUPPORTED_SCHEMES = frozenset(
    {
        "postgresql",
        "postgres",
        "postgresql+psycopg",
        "postgres+psycopg",
        "cockroachdb",
        "cockroachdb+psycopg",
    }
)


def redact_database_url(database_url: str) -> str:
    """Return a connection string with the password removed.

    Prefer ``safe_log_target`` for application logs. This helper exists for
    diagnostics that must never include secrets.
    """
    parsed = urlparse(database_url)
    if not parsed.username and "@" not in (parsed.netloc or ""):
        return database_url

    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    user = unquote(parsed.username) if parsed.username else ""
    auth = f"{user}:***@" if user else "***@"
    return urlunparse(
        (
            parsed.scheme,
            f"{auth}{host}{port}",
            parsed.path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _choose_async_scheme(scheme: str, hostname: str | None) -> str:
    """Select the async SQLAlchemy dialect for the target database."""
    normalized_scheme = scheme.lower()
    if normalized_scheme.startswith("cockroachdb"):
        return "cockroachdb+psycopg"

    host = (hostname or "").lower()
    if "cockroachlabs" in host or host.endswith(".crdb.io"):
        return "cockroachdb+psycopg"

    return "postgresql+psycopg"


def normalize_target_database_url(
    database_url: str,
    *,
    force_cockroach: bool = False,
) -> str:
    """Normalize a PostgreSQL-compatible URL for async SQLAlchemy + psycopg."""
    if not database_url or not database_url.strip():
        raise UnsupportedDatabaseError("database_url is required")

    parsed = urlparse(database_url.strip())
    scheme = parsed.scheme.lower()
    if scheme not in _SUPPORTED_SCHEMES:
        raise UnsupportedDatabaseError(
            "database_url must use a PostgreSQL-compatible scheme "
            "(postgresql://, postgres://, or cockroachdb://)"
        )

    if force_cockroach:
        async_scheme = "cockroachdb+psycopg"
    else:
        async_scheme = _choose_async_scheme(scheme, parsed.hostname)

    query = parse_qs(parsed.query, keep_blank_values=True)
    sslmode = (query.get("sslmode", ["prefer"])[0] or "prefer").lower()

    if sslmode in _SECURE_SSL_MODES and "sslrootcert" not in query:
        ca_cert = resolve_cockroach_ca_cert()
        if ca_cert is None:
            raise SchemaSSLError(
                "sslmode requires a CA certificate, but none was found at the "
                "standard CockroachDB/libpq location"
            )
        query["sslrootcert"] = [str(ca_cert)]

    normalized_query = urlencode(
        {key: values[-1] for key, values in query.items()},
        quote_via=quote,
        safe="/:\\",
    )

    return urlunparse(
        (
            async_scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            normalized_query,
            parsed.fragment,
        )
    )


class SchemaAnalysisConnection:
    """Short-lived async engine for read-only schema inspection.

    Owns engine lifecycle. Callers must use as an async context manager or
    explicitly call ``close()``. Never logs credentials or connection strings.
    """

    def __init__(
        self,
        database_url: str,
        *,
        connect_timeout: int = 30,
        statement_timeout_ms: int = 60_000,
        force_cockroach: bool = False,
    ) -> None:
        self._raw_url = database_url
        self._normalized_url = normalize_target_database_url(
            database_url,
            force_cockroach=force_cockroach,
        )
        self._connect_timeout = connect_timeout
        self._statement_timeout_ms = statement_timeout_ms
        self._host, self._database = host_and_database_from_url(self._normalized_url)
        self._engine: AsyncEngine | None = create_async_engine(
            self._normalized_url,
            pool_pre_ping=True,
            pool_size=1,
            max_overflow=0,
            connect_args={
                "connect_timeout": connect_timeout,
                "application_name": "migration-oracle-schema-analysis",
            },
        )
        logger.info(
            "Schema analysis connection initialized",
            extra={
                **safe_log_target(self._host, self._database),
                "connect_timeout": connect_timeout,
            },
        )

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("Schema analysis connection is closed")
        return self._engine

    async def connect(self) -> AsyncConnection:
        """Open a connection and apply a statement timeout when supported."""
        connection = await self.engine.connect()
        try:
            await connection.execute(
                text(f"SET statement_timeout = {int(self._statement_timeout_ms)}")
            )
            await connection.commit()
        except Exception:
            await connection.rollback()
            logger.warning(
                "Unable to set statement_timeout; continuing without it",
                extra=safe_log_target(self._host, self._database),
            )
        return connection

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection]:
        conn = await self.connect()
        try:
            yield conn
        finally:
            await conn.close()

    async def ping(self) -> str:
        async with self.connection() as conn:
            version = (await conn.execute(text("SELECT version()"))).scalar_one()
        return str(version)

    async def close(self) -> None:
        if self._engine is None:
            return
        await self._engine.dispose()
        self._engine = None
        logger.info(
            "Schema analysis connection closed",
            extra=safe_log_target(self._host, self._database),
        )

    async def __aenter__(self) -> SchemaAnalysisConnection:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()
