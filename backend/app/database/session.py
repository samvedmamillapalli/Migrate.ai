from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.logging import get_logger

logger = get_logger(__name__)

_SECURE_SSL_MODES = frozenset({"verify-ca", "verify-full"})


def resolve_cockroach_ca_cert() -> Path | None:
    """Return a Cockroach Cloud CA cert path if one is available.

    Search order:
    1. Lambda package (``certs/root.crt`` next to the handler)
    2. Repo-bundled public CA (``certs/cockroach-cloud-ca.crt``) so teammates
       do not need a manual download after clone
    3. Standard libpq locations (``%APPDATA%\\postgresql\\root.crt`` /
       ``~/.postgresql/root.crt``)
    """
    candidates: list[Path] = []

    # Bundled into Lambda packages by package_lambda_for_sam.py
    lambda_root = os.environ.get("LAMBDA_TASK_ROOT")
    if lambda_root:
        candidates.append(Path(lambda_root) / "certs" / "root.crt")
        candidates.append(Path(lambda_root) / "root.crt")

    # backend/app/database/session.py → repo root is parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    candidates.append(repo_root / "certs" / "cockroach-cloud-ca.crt")
    candidates.append(repo_root / "certs" / "root.crt")

    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "postgresql" / "root.crt")
    else:
        candidates.append(Path.home() / ".postgresql" / "root.crt")

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def normalize_database_url(database_url: str) -> str:
    """Normalize CockroachDB Cloud URLs for async SQLAlchemy + psycopg."""
    if not database_url:
        raise ValueError("DATABASE_URL is required")

    parsed = urlparse(database_url)
    scheme = parsed.scheme.lower()

    if scheme in {"postgresql", "postgres", "cockroachdb"}:
        scheme = "cockroachdb+psycopg"
    elif scheme in {"postgresql+psycopg", "postgres+psycopg"}:
        scheme = "cockroachdb+psycopg"
    elif scheme != "cockroachdb+psycopg":
        raise ValueError(
            "DATABASE_URL must use postgresql:// or cockroachdb+psycopg:// for CockroachDB"
        )

    query = parse_qs(parsed.query, keep_blank_values=True)
    sslmode = (query.get("sslmode", ["disable"])[0] or "disable").lower()

    if sslmode in _SECURE_SSL_MODES and "sslrootcert" not in query:
        ca_cert = resolve_cockroach_ca_cert()
        if ca_cert is None:
            # Lambda packages may lack a host CA; still encrypt with require.
            if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or os.environ.get(
                "LAMBDA_TASK_ROOT"
            ):
                query["sslmode"] = ["require"]
                logger.warning(
                    "No Cockroach CA in Lambda package; falling back to sslmode=require"
                )
            else:
                raise ValueError(
                    "sslmode requires a CA certificate, but none was found at the "
                    "standard CockroachDB/libpq location "
                    "(%APPDATA%\\postgresql\\root.crt on Windows, "
                    "~/.postgresql/root.crt on macOS/Linux)"
                )
        else:
            query["sslrootcert"] = [str(ca_cert)]
            logger.info(
                "Detected CockroachDB CA certificate",
                extra={"sslrootcert": str(ca_cert)},
            )

    normalized_query = urlencode(
        {key: values[-1] for key, values in query.items()},
        quote_via=quote,
        safe="/:\\",
    )

    return urlunparse(
        (
            scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            normalized_query,
            parsed.fragment,
        )
    )


class DatabaseSessionManager:
    def __init__(self, database_url: str) -> None:
        normalized_url = normalize_database_url(database_url)

        self._engine: AsyncEngine | None = create_async_engine(
            normalized_url,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": 30,
                "application_name": "migration-oracle",
            },
        )
        self._session_factory: async_sessionmaker[AsyncSession] | None = (
            async_sessionmaker(
                self._engine,
                expire_on_commit=False,
            )
        )
        logger.info("Database engine initialized")

    def _require_session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise RuntimeError("Database session manager is closed")
        return self._session_factory

    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def check_connection(self) -> str:
        session_factory = self._require_session_factory()
        async with session_factory() as session:
            version = (
                await session.execute(text("SELECT version()"))
            ).scalar_one()
        return str(version)

    async def close(self) -> None:
        if self._engine is None:
            return

        await self._engine.dispose()
        self._engine = None
        self._session_factory = None
        logger.info("Database engine disposed")
