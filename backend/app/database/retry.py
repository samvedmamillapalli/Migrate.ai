from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

# CockroachDB / PostgreSQL serialization failure.
_SERIALIZATION_SQLSTATE = "40001"
_DEFAULT_MAX_ATTEMPTS = 3
_BASE_DELAY_SECONDS = 0.05


def is_serialization_failure(exc: BaseException) -> bool:
    """Return True when the error is a retryable transaction conflict."""
    sqlstate = _extract_sqlstate(exc)
    if sqlstate == _SERIALIZATION_SQLSTATE:
        return True

    message = str(exc).lower()
    return (
        "40001" in message
        or "serialization failure" in message
        or "restart transaction" in message
    )


def _extract_sqlstate(exc: BaseException) -> str | None:
    if isinstance(exc, DBAPIError | OperationalError) and exc.orig is not None:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate:
            return str(sqlstate)
        pgcode = getattr(exc.orig, "pgcode", None)
        if pgcode:
            return str(pgcode)
    sqlstate = getattr(exc, "sqlstate", None)
    if sqlstate:
        return str(sqlstate)
    cause = exc.__cause__
    if cause is not None and cause is not exc:
        return _extract_sqlstate(cause)
    return None


async def with_txn_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    on_retry: Callable[[], Awaitable[None]] | None = None,
) -> T:
    """Retry ``operation`` on CockroachDB serialization failures (SQLSTATE 40001)."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    attempt = 0
    while True:
        attempt += 1
        try:
            return await operation()
        except Exception as exc:
            if not is_serialization_failure(exc) or attempt >= max_attempts:
                raise
            logger.info(
                "Retrying transaction after serialization failure",
                extra={"attempt": attempt, "max_attempts": max_attempts},
            )
            if on_retry is not None:
                await on_retry()
            await asyncio.sleep(_BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
