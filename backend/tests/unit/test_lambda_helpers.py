"""Unit tests for Lambda secret connection helpers."""

from __future__ import annotations

import pytest

from app.lambdas.errors import LambdaValidationError
from app.lambdas.helpers import connection_from_secret


def test_connection_from_secret_accepts_database_url() -> None:
    conn = connection_from_secret(
        {
            "database_url": (
                "postgresql://app:s3cret@db.example.com:26257/appdb?sslmode=require"
            )
        }
    )
    assert conn.host == "db.example.com"
    assert conn.port == 26257
    assert conn.database == "appdb"
    assert conn.username == "app"
    assert conn.password.get_secret_value() == "s3cret"


def test_connection_from_secret_accepts_structured_fields() -> None:
    conn = connection_from_secret(
        {
            "host": "db.example.com",
            "port": 26257,
            "database": "appdb",
            "username": "app",
            "password": "s3cret",
            "ssl_mode": "require",
        }
    )
    assert conn.host == "db.example.com"
    assert conn.username == "app"


def test_connection_from_secret_rejects_empty_payload() -> None:
    with pytest.raises(LambdaValidationError):
        connection_from_secret({})
