from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.logging import get_logger
from app.schema_analysis.connection import normalize_target_database_url
from app.schema_analysis.models import (
    ColumnMetadata,
    DatabaseMetadata,
    IndexMetadata,
    TableMetadata,
)
from app.shadow.models import TIER_ROW_CAPS, ScaleTier, SeedReport

logger = get_logger(__name__)

# Schemas we never recreate on the shadow.
_SYSTEM_SCHEMAS = frozenset(
    {"information_schema", "pg_catalog", "crdb_internal", "pg_extension"}
)

_INSERT_BATCH = 500


class ShadowSeeder:
    """Recreate a customer's schema *shape* on the shadow and load synthetic rows.

    Documented simplifications (safe for measuring a schema change's backfill
    duration, storage growth, resource saturation and rollback safety):

    * Foreign-key and CHECK constraints are omitted. We recreate columns, types,
      primary keys and secondary indexes. Dropping FK/CHECK keeps synthetic data
      generation tractable and does not affect how CockroachDB runs the schema
      change under test.
    * Column data types are mapped onto a compact set of CockroachDB types by
      family rather than reproduced byte-for-byte.
    * Row volume is capped per scale tier so the shadow stays inside free usage.
    """

    def __init__(self, *, seed: int = 1234) -> None:
        self._rng = random.Random(seed)

    async def seed(
        self,
        connection_url: str,
        metadata: DatabaseMetadata,
        scale_tier: ScaleTier,
        *,
        statement_timeout_ms: int = 300_000,
    ) -> SeedReport:
        normalized = normalize_target_database_url(connection_url, force_cockroach=True)
        engine = create_async_engine(normalized, pool_pre_ping=True)
        report = SeedReport(scale_tier=scale_tier)
        row_cap = TIER_ROW_CAPS[scale_tier]
        try:
            # AUTOCOMMIT: each statement is its own implicit transaction. This is
            # required on CockroachDB, which rejects a schema-change statement
            # (e.g. CREATE INDEX) that follows a write (INSERT) inside the *same*
            # transaction. Running each DDL/DML independently sidesteps that.
            async with engine.connect() as raw:
                conn = await raw.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(
                    text(f"SET statement_timeout = {int(statement_timeout_ms)}")
                )
                for schema in metadata.schemas:
                    if schema.name in _SYSTEM_SCHEMAS:
                        continue
                    if schema.name != "public":
                        await conn.execute(
                            text(f'CREATE SCHEMA IF NOT EXISTS "{schema.name}"')
                        )
                    for table in schema.tables:
                        await self._create_table(conn, table)
                        report.tables_created += 1
                        inserted = await self._load_rows(conn, table, row_cap)
                        report.rows_inserted += inserted
                        report.per_table_rows[table.name] = inserted
                        report.indexes_created += await self._create_indexes(
                            conn, table
                        )
        finally:
            await engine.dispose()

        logger.info(
            "Seeded shadow database",
            extra={
                "scale_tier": scale_tier.value,
                "tables_created": report.tables_created,
                "rows_inserted": report.rows_inserted,
            },
        )
        return report

    # -- DDL ----------------------------------------------------------------

    async def _create_table(self, conn: AsyncConnection, table: TableMetadata) -> None:
        qualified = self._qualified(table)
        col_defs: list[str] = []
        for column in sorted(table.columns, key=lambda c: c.ordinal_position):
            col_defs.append(self._column_ddl(column))
        pk = [f'"{c}"' for c in table.primary_key]
        if pk:
            col_defs.append(f"PRIMARY KEY ({', '.join(pk)})")
        ddl = f"CREATE TABLE IF NOT EXISTS {qualified} (\n  " + ",\n  ".join(col_defs) + "\n)"
        await conn.execute(text(ddl))

    async def _create_indexes(self, conn: AsyncConnection, table: TableMetadata) -> int:
        created = 0
        qualified = self._qualified(table)
        for index in table.indexes:
            if index.is_primary:
                continue  # PK already created inline
            if not index.columns:
                continue
            cols = ", ".join(f'"{c}"' for c in index.columns)
            unique = "UNIQUE " if index.is_unique else ""
            idx_name = self._safe_index_name(table, index)
            try:
                await conn.execute(
                    text(
                        f"CREATE {unique}INDEX IF NOT EXISTS "
                        f'"{idx_name}" ON {qualified} ({cols})'
                    )
                )
                created += 1
            except Exception:  # noqa: BLE001 - best-effort shape fidelity
                logger.warning(
                    "Skipped index during seeding",
                    extra={"table": table.name, "index": index.name},
                )
        return created

    # -- data ---------------------------------------------------------------

    async def _load_rows(
        self,
        conn: AsyncConnection,
        table: TableMetadata,
        row_cap: int,
    ) -> int:
        target = self._row_target(table, row_cap)
        if target <= 0:
            return 0

        columns = sorted(table.columns, key=lambda c: c.ordinal_position)
        pk_set = set(table.primary_key)
        col_names = ", ".join(f'"{c.name}"' for c in columns)
        placeholders = ", ".join(f":{c.name}" for c in columns)
        insert_sql = text(
            f"INSERT INTO {self._qualified(table)} ({col_names}) "
            f"VALUES ({placeholders})"
        )

        inserted = 0
        batch: list[dict[str, object]] = []
        for i in range(target):
            row = {
                c.name: self._value_for(c, row_index=i, is_pk=c.name in pk_set)
                for c in columns
            }
            batch.append(row)
            if len(batch) >= _INSERT_BATCH:
                await conn.execute(insert_sql, batch)
                inserted += len(batch)
                batch = []
        if batch:
            await conn.execute(insert_sql, batch)
            inserted += len(batch)
        return inserted

    def _row_target(self, table: TableMetadata, row_cap: int) -> int:
        estimated = table.estimated_row_count
        if estimated is None:
            # No estimate: seed a modest representative volume (10% of the cap)
            # so a backfill has something to chew on without overshooting.
            return max(1, row_cap // 10)
        return min(estimated, row_cap)

    def _value_for(
        self,
        column: ColumnMetadata,
        *,
        row_index: int,
        is_pk: bool,
    ) -> object:
        family = _type_family(column)
        # Primary-key columns must be unique; derive deterministically from the
        # row index where possible.
        if family == "uuid":
            return str(uuid.uuid4())
        if family == "int":
            return row_index + 1 if is_pk else self._rng.randint(0, 1_000_000)
        if family == "bool":
            return self._rng.random() < 0.5
        if family == "float":
            return round(self._rng.uniform(0, 10_000), 4)
        if family == "timestamp":
            return datetime.now(UTC) - timedelta(seconds=self._rng.randint(0, 10_000_000))
        if family == "date":
            return (datetime.now(UTC) - timedelta(days=self._rng.randint(0, 3650))).date()
        if family == "json":
            return "{}"
        if family == "bytes":
            return self._rng.randbytes(16)
        # string / fallback
        base = f"{column.name}_{row_index}_{self._rng.randint(0, 1_000_000)}"
        max_len = column.character_maximum_length
        if max_len is not None and max_len > 0:
            return base[:max_len]
        return base

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _qualified(table: TableMetadata) -> str:
        if table.schema_name and table.schema_name != "public":
            return f'"{table.schema_name}"."{table.name}"'
        return f'"{table.name}"'

    def _column_ddl(self, column: ColumnMetadata) -> str:
        col_type = _map_type(column)
        nullable = "" if column.is_nullable else " NOT NULL"
        return f'"{column.name}" {col_type}{nullable}'

    @staticmethod
    def _safe_index_name(table: TableMetadata, index: IndexMetadata) -> str:
        # Prefer the snapshot's real index name so migrations that DROP/CREATE
        # by name match what was loaded onto the shadow cluster.
        raw = (index.name or "_".join(index.columns) or f"{table.name}_idx").strip()
        return raw[:120]


def _type_family(column: ColumnMetadata) -> str:
    raw = (column.udt_name or column.data_type or "").lower()
    if "uuid" in raw:
        return "uuid"
    if any(k in raw for k in ("bool",)):
        return "bool"
    if any(k in raw for k in ("timestamp", "timestamptz")):
        return "timestamp"
    if raw in {"date"}:
        return "date"
    if any(k in raw for k in ("json", "jsonb")):
        return "json"
    if any(k in raw for k in ("bytea", "bytes", "blob")):
        return "bytes"
    if any(k in raw for k in ("int", "serial", "int2", "int4", "int8", "bigint", "smallint")):
        return "int"
    if any(
        k in raw
        for k in ("numeric", "decimal", "real", "double", "float", "float4", "float8")
    ):
        return "float"
    return "string"


def _map_type(column: ColumnMetadata) -> str:
    """Map a column onto a compact set of CockroachDB-compatible types."""
    family = _type_family(column)
    mapping = {
        "uuid": "UUID",
        "bool": "BOOL",
        "timestamp": "TIMESTAMPTZ",
        "date": "DATE",
        "json": "JSONB",
        "bytes": "BYTES",
        "int": "INT8",
        "float": "FLOAT8",
    }
    if family in mapping:
        return mapping[family]
    max_len = column.character_maximum_length
    if max_len is not None and max_len > 0:
        return f"VARCHAR({max_len})"
    return "STRING"
