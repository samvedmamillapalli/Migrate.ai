"""Debug-only fake migration generator (not real graded history).

Creates random SQL + a synthetic schema snapshot so predict can run without
a live customer database. Does NOT write graded memories or accuracy points.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from app.schema_analysis.models import (
    ColumnMetadata,
    DatabaseMetadata,
    IndexMetadata,
    SchemaMetadata,
    TableMetadata,
)

# Curated patterns — random picks, not fabricated grades.
_FAKE_MIGRATIONS: list[tuple[str, str]] = [
    (
        "add_column_default",
        "ALTER TABLE users ADD COLUMN active BOOL NOT NULL DEFAULT false;",
    ),
    (
        "create_index",
        "CREATE INDEX idx_users_email ON users (email);",
    ),
    (
        "create_unique_index",
        "CREATE UNIQUE INDEX idx_users_username ON users (username);",
    ),
    (
        "add_column_nullable",
        "ALTER TABLE orders ADD COLUMN notes STRING;",
    ),
    (
        "add_column_not_null_default",
        "ALTER TABLE orders ADD COLUMN status STRING NOT NULL DEFAULT 'open';",
    ),
    (
        "create_index_orders",
        "CREATE INDEX idx_orders_created_at ON orders (created_at);",
    ),
    (
        "alter_column_type",
        "ALTER TABLE users ALTER COLUMN phone TYPE STRING;",
    ),
    (
        "drop_index",
        "DROP INDEX idx_users_email;",
    ),
]


def pick_fake_migration(*, rng: random.Random | None = None) -> dict[str, Any]:
    r = rng or random.Random()
    kind, sql = r.choice(_FAKE_MIGRATIONS)
    if "idx_" in sql and r.random() < 0.5:
        suffix = r.randint(100, 999)
        sql = sql.replace("idx_", f"idx_dbg{suffix}_", 1)
    return {
        "kind": kind,
        "migration_sql": sql,
        "debug": True,
        "note": (
            "Synthetic debug migration only. Not a real customer change and "
            "not a graded memory."
        ),
    }


def _column(
    name: str,
    data_type: str,
    *,
    ordinal: int,
    nullable: bool = True,
    pk: bool = False,
) -> ColumnMetadata:
    return ColumnMetadata(
        name=name,
        data_type=data_type,
        udt_name=data_type.lower(),
        is_nullable=nullable,
        column_default=None,
        ordinal_position=ordinal,
        is_primary_key=pk,
    )


def build_fake_schema_snapshot(*, rng: random.Random | None = None) -> dict[str, Any]:
    """Schema snapshot matching DatabaseMetadata (same shape as real discover)."""
    r = rng or random.Random()
    user_rows = r.choice([1_000, 10_000, 100_000, 500_000])
    order_rows = r.choice([5_000, 50_000, 250_000])

    users = TableMetadata(
        name="users",
        schema_name="public",
        column_count=4,
        columns=[
            _column("id", "UUID", ordinal=1, nullable=False, pk=True),
            _column("email", "STRING", ordinal=2),
            _column("username", "STRING", ordinal=3),
            _column("phone", "STRING", ordinal=4),
        ],
        primary_key=["id"],
        foreign_keys=[],
        indexes=[
            IndexMetadata(
                name="users_pkey",
                columns=["id"],
                is_unique=True,
                is_primary=True,
            ),
        ],
        constraints=[],
        estimated_row_count=user_rows,
        estimated_size_bytes=user_rows * 120,
    )
    orders = TableMetadata(
        name="orders",
        schema_name="public",
        column_count=3,
        columns=[
            _column("id", "UUID", ordinal=1, nullable=False, pk=True),
            _column("user_id", "UUID", ordinal=2, nullable=False),
            _column("created_at", "TIMESTAMPTZ", ordinal=3),
        ],
        primary_key=["id"],
        foreign_keys=[],
        indexes=[
            IndexMetadata(
                name="orders_pkey",
                columns=["id"],
                is_unique=True,
                is_primary=True,
            ),
        ],
        constraints=[],
        estimated_row_count=order_rows,
        estimated_size_bytes=order_rows * 200,
    )
    schema = SchemaMetadata(name="public", tables=[users, orders], table_count=2)
    metadata = DatabaseMetadata(
        database_name="debug_synthetic",
        server_version="CockroachDB (debug synthetic)",
        schemas=[schema],
        schema_count=1,
        table_count=2,
        estimated_size_bytes=user_rows * 120 + order_rows * 200,
        inspected_at=datetime.now(timezone.utc),
    )
    payload = metadata.model_dump(mode="json")
    payload["debug_synthetic"] = True
    return payload
