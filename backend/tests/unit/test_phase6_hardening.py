from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from app.core.exceptions import (
    SchemaAuthenticationError,
    SchemaConnectionError,
    SchemaDatabaseNotFoundError,
    SchemaNetworkError,
    SchemaSSLError,
    SchemaTimeoutError,
    UnsupportedDatabaseError,
)
from app.database.retry import is_serialization_failure, with_txn_retry
from app.schema_analysis.connection import normalize_target_database_url
from app.schema_analysis.errors import (
    is_cockroach_version_parse_error,
    translate_schema_error,
)


def test_translate_wrong_password() -> None:
    err = translate_schema_error(
        OperationalError("password authentication failed for user", None, None)
    )
    assert isinstance(err, SchemaAuthenticationError)


def test_translate_missing_database() -> None:
    err = translate_schema_error(
        OperationalError('database "nope" does not exist', None, None)
    )
    assert isinstance(err, SchemaDatabaseNotFoundError)


def test_translate_timeout() -> None:
    err = translate_schema_error(TimeoutError())
    assert isinstance(err, SchemaTimeoutError)


def test_translate_ssl() -> None:
    err = translate_schema_error(
        OperationalError("SSL connection has failed: certificate verify failed", None, None)
    )
    assert isinstance(err, SchemaSSLError)


def test_translate_network() -> None:
    err = translate_schema_error(
        OperationalError("could not connect to server: Connection refused", None, None)
    )
    assert isinstance(err, SchemaNetworkError)


def test_translate_unsupported_scheme() -> None:
    with pytest.raises(UnsupportedDatabaseError):
        normalize_target_database_url("mysql://user:pass@localhost:3306/db")


def test_normalize_force_cockroach() -> None:
    url = normalize_target_database_url(
        "postgresql://u:p@localhost:26257/db?sslmode=disable",
        force_cockroach=True,
    )
    assert url.startswith("cockroachdb+psycopg://")


def test_cockroach_version_parse_error_detection() -> None:
    assert is_cockroach_version_parse_error(
        AssertionError("Could not determine version from string 'CockroachDB CCL'")
    )
    assert not is_cockroach_version_parse_error(AssertionError("other"))
    assert translate_schema_error(
        AssertionError("Could not determine version from string 'CockroachDB'")
    ) is None


def test_is_serialization_failure() -> None:
    class FakeOrig:
        sqlstate = "40001"

    exc = OperationalError("restart transaction", None, None)
    exc.orig = FakeOrig()  # type: ignore[attr-defined]
    assert is_serialization_failure(exc)
    assert is_serialization_failure(RuntimeError("serialization failure: 40001"))
    assert not is_serialization_failure(RuntimeError("unrelated"))


@pytest.mark.asyncio
async def test_with_txn_retry_retries_then_succeeds() -> None:
    attempts = {"n": 0}

    async def operation() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("restart transaction: SQLSTATE 40001")
        return "ok"

    rollbacks = {"n": 0}

    async def on_retry() -> None:
        rollbacks["n"] += 1

    result = await with_txn_retry(operation, max_attempts=3, on_retry=on_retry)
    assert result == "ok"
    assert attempts["n"] == 3
    assert rollbacks["n"] == 2


@pytest.mark.asyncio
async def test_with_txn_retry_gives_up() -> None:
    async def operation() -> str:
        raise RuntimeError("serialization failure")

    with pytest.raises(RuntimeError):
        await with_txn_retry(operation, max_attempts=2)


def test_generic_sqlalchemy_error_does_not_leak_driver_text() -> None:
    err = translate_schema_error(SQLAlchemyError("secret internals xyz"))
    assert isinstance(err, SchemaConnectionError)
    assert err is not None
    assert "secret internals" not in err.message
    assert err.message == "Database connection failed"
