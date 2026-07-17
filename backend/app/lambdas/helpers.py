"""Shared helpers for Lambda handlers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from pydantic import SecretStr

from app.database.models import SchemaDiscoveryStatus
from app.lambdas.errors import LambdaValidationError
from app.schema_analysis.database_connection import DatabaseConnection, SslMode
from app.schema_analysis.models import (
    ColumnMetadata,
    DatabaseMetadata,
    SchemaMetadata,
    TableMetadata,
)


def parse_run_id(event: dict[str, Any]) -> uuid.UUID:
    raw = event.get("run_id")
    if not raw:
        raise LambdaValidationError("event.run_id is required")
    try:
        return uuid.UUID(str(raw))
    except ValueError as exc:
        raise LambdaValidationError(f"Invalid run_id: {raw}") from exc


def connection_from_secret(payload: dict[str, Any]) -> DatabaseConnection:
    try:
        return DatabaseConnection.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - normalize to handler error
        raise LambdaValidationError(
            "connection secret must include host, database, username, password"
        ) from exc


def connection_from_database_url(database_url: str) -> DatabaseConnection:
    parsed = urlparse(database_url)
    if not parsed.hostname or not parsed.path or parsed.path == "/":
        raise LambdaValidationError("DATABASE_URL is missing host or database")
    query = parse_qs(parsed.query)
    ssl_raw = (query.get("sslmode") or ["require"])[0]
    try:
        ssl_mode = SslMode(ssl_raw)
    except ValueError:
        ssl_mode = SslMode.REQUIRE
    password = unquote(parsed.password or "")
    username = unquote(parsed.username or "")
    if not username:
        raise LambdaValidationError("DATABASE_URL is missing username")
    return DatabaseConnection(
        host=parsed.hostname,
        port=parsed.port or 26257,
        database=unquote(parsed.path.lstrip("/")),
        username=username,
        password=SecretStr(password),
        ssl_mode=ssl_mode,
    )


def local_fixture_metadata() -> DatabaseMetadata:
    """Minimal schema used when live discovery is rejected in local mode."""
    table = TableMetadata(
        name="items",
        schema_name="public",
        column_count=2,
        columns=[
            ColumnMetadata(
                name="id",
                data_type="integer",
                is_nullable=False,
                ordinal_position=1,
                is_primary_key=True,
            ),
            ColumnMetadata(
                name="name",
                data_type="text",
                is_nullable=True,
                ordinal_position=2,
            ),
        ],
        primary_key=["id"],
        foreign_keys=[],
        indexes=[],
        constraints=[],
        estimated_row_count=0,
    )
    schema = SchemaMetadata(name="public", tables=[table], table_count=1)
    return DatabaseMetadata(
        database_name="local_fixture",
        server_version="CockroachDB local fixture",
        schemas=[schema],
        schema_count=1,
        table_count=1,
        inspected_at=datetime.now(UTC),
    )


def discovery_already_done(status: SchemaDiscoveryStatus | None) -> bool:
    return status == SchemaDiscoveryStatus.SUCCEEDED


def shadow_secret_name(run_id: uuid.UUID) -> str:
    return f"migration-oracle/shadow/{run_id}"


def total_estimated_rows(metadata: DatabaseMetadata) -> int | None:
    total = 0
    seen = False
    for schema in metadata.schemas:
        for table in schema.tables:
            if table.estimated_row_count is not None:
                total += table.estimated_row_count
                seen = True
    return total if seen else None
