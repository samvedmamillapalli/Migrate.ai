from __future__ import annotations

import asyncio
import random
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

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

# Rows per INSERT statement. Each batch is sent as ONE multi-row VALUES
# statement, so this is also the number of network round trips saved. The
# PostgreSQL wire protocol caps a statement at 65535 bind parameters, and a
# batch costs rows*columns of them, so the effective batch is re-derived
# per table from its column count (see _rows_per_batch) and this is only the
# ceiling for narrow tables.
_INSERT_BATCH_MAX = 1_000
_MAX_BIND_PARAMS = 60_000  # headroom under the 65535 protocol limit

# How many tables to seed concurrently. Seeding is round-trip-bound against a
# remote CockroachDB Cloud cluster, not CPU-bound, so overlapping tables is
# most of the win. Matches the bounded-gather limit already used by
# schema_snapshot._fill_exact_row_counts.
_TABLE_CONCURRENCY = 8


def _rows_per_batch(column_count: int) -> int:
    """Largest row batch that stays under the bind-parameter ceiling."""
    if column_count <= 0:
        return _INSERT_BATCH_MAX
    return max(1, min(_INSERT_BATCH_MAX, _MAX_BIND_PARAMS // column_count))


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
        engine: AsyncEngine | None = None,
    ) -> SeedReport:
        normalized = normalize_target_database_url(connection_url, force_cockroach=True)
        owns_engine = engine is None
        if engine is None:
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
            if owns_engine:
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

    async def seed_rows_only(
        self,
        connection_url: str,
        metadata: DatabaseMetadata,
        scale_tier: ScaleTier,
        *,
        statement_timeout_ms: int = 300_000,
        engine: AsyncEngine | None = None,
    ) -> SeedReport:
        """Insert synthetic rows into an already-loaded schema (no DDL).

        Used after ``ShadowSchemaLoader`` so FK/CHECK from the real snapshot stay
        intact. Per-table failures are recorded as warnings (FK order / type
        mismatches) so a partial seed still yields measurable storage.
        """
        normalized = normalize_target_database_url(connection_url, force_cockroach=True)
        owns_engine = engine is None
        if engine is None:
            engine = create_async_engine(normalized, pool_pre_ping=True)
        report = SeedReport(scale_tier=scale_tier)
        row_cap = TIER_ROW_CAPS[scale_tier]
        warnings: list[str] = []
        targets = [
            table
            for schema in metadata.schemas
            if schema.name not in _SYSTEM_SCHEMAS
            for table in schema.tables
        ]

        # Seed tables concurrently. Each table is an independent INSERT stream
        # and per-table failures were already isolated as warnings, so the only
        # thing serializing them was the single shared connection. A fixed pool
        # of workers, each holding one connection for its whole lifetime, keeps
        # connection setup (including pool_pre_ping's round trip and the
        # statement_timeout SET) to once per worker rather than once per table.
        pending = iter(targets)
        results: list[tuple[str, int, str | None]] = []

        async def worker() -> None:
            async with engine.connect() as raw:
                conn = await raw.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(
                    text(f"SET statement_timeout = {int(statement_timeout_ms)}")
                )
                for table in pending:  # a shared iterator is safe: no await here
                    try:
                        inserted = await self._load_rows(conn, table, row_cap)
                        results.append((table.name, inserted, None))
                    except Exception as exc:  # noqa: BLE001 - best-effort seed
                        logger.warning(
                            "Skipped synthetic seed for table",
                            extra={"table": table.name, "error": str(exc)[:200]},
                        )
                        results.append(
                            (
                                table.name,
                                0,
                                f"{table.schema_name}.{table.name}: {exc}"[:500],
                            )
                        )

        try:
            worker_count = max(1, min(_TABLE_CONCURRENCY, len(targets)))
            await asyncio.gather(*(worker() for _ in range(worker_count)))
            for name, inserted, warning in results:
                if warning is not None:
                    warnings.append(warning)
                    continue
                report.rows_inserted += inserted
                report.per_table_rows[name] = inserted
        finally:
            if owns_engine:
                await engine.dispose()

        report.warnings = warnings
        logger.info(
            "Seeded synthetic rows on shadow",
            extra={
                "scale_tier": scale_tier.value,
                "rows_inserted": report.rows_inserted,
                "warning_count": len(warnings),
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

    def _server_side_values_sql(self, table: TableMetadata, target: int) -> str | None:
        """Build ``INSERT .. SELECT .. FROM generate_series`` for this table.

        Returns None if any column has no safe SQL generator, in which case the
        caller falls back to shipping rows from Python.

        This exists because the client-side path is dominated by moving data,
        not by round trips: measured on a real CockroachDB BASIC cluster with
        the demo shape (10 tables x 40 columns x 4,500 rows), generating rows
        in the database took 1.9s against 72.1s for client-side inserts - the
        45,000 x 40 values simply never cross the wire.
        """
        columns = sorted(table.columns, key=lambda c: c.ordinal_position)
        if not columns:
            return None
        pk_set = set(table.primary_key)
        exprs: list[str] = []
        for column in columns:
            expr = self._sql_value_expr(column, is_pk=column.name in pk_set)
            if expr is None:
                return None
            exprs.append(expr)
        col_names = ", ".join(f'"{c.name}"' for c in columns)
        return (
            f"INSERT INTO {self._qualified(table)} ({col_names}) "
            f"SELECT {', '.join(exprs)} FROM generate_series(1, {int(target)}) AS g"
        )

    @staticmethod
    def _sql_value_expr(column: ColumnMetadata, *, is_pk: bool) -> str | None:
        """SQL expression generating one synthetic value, mirroring _value_for.

        ``g`` is generate_series' 1..N counter, so any expression using it is
        unique per row - which is what primary keys need.
        """
        family = _type_family(column)
        if family == "uuid":
            return "gen_random_uuid()"
        if family == "int":
            return "g" if is_pk else "(random() * 1000000)::INT8"
        if family == "bool":
            return "random() < 0.5"
        if family == "float":
            return "(random() * 10000)::FLOAT8"
        if family == "timestamp":
            return "now() - ((random() * 10000000)::INT8 || ' seconds')::INTERVAL"
        if family == "date":
            return "(now() - ((random() * 3650)::INT8 || ' days')::INTERVAL)::DATE"
        if family == "json":
            return "'{}'::JSONB"
        if family == "bytes":
            return "decode(md5(random()::STRING), 'hex')"
        if family == "string":
            max_len = column.character_maximum_length
            if is_pk:
                # Must stay unique: derive from the counter, not from random().
                base = "('r_' || g::STRING)"
                if max_len is not None and 0 < max_len < 24:
                    return f"left({base}, {int(max_len)})"
                return base
            width = 32
            if max_len is not None and 0 < max_len < width:
                width = int(max_len)
            return f"left(md5(random()::STRING), {width})"
        return None

    async def _load_rows(
        self,
        conn: AsyncConnection,
        table: TableMetadata,
        row_cap: int,
    ) -> int:
        target = self._row_target(table, row_cap)
        if target <= 0:
            return 0

        # Preferred path: let the database generate the rows. Falls back to the
        # client-side path below on any failure (an unmappable column type, or a
        # generator expression the target rejects), so a seed can degrade in
        # speed but never in correctness.
        server_sql = self._server_side_values_sql(table, target)
        if server_sql is not None:
            try:
                await conn.execute(text(server_sql))
                return target
            except Exception as exc:  # noqa: BLE001 - fall back, do not fail
                logger.warning(
                    "Server-side seed failed; falling back to client-side rows",
                    extra={"table": table.name, "error": str(exc)[:200]},
                )

        columns = sorted(table.columns, key=lambda c: c.ordinal_position)
        pk_set = set(table.primary_key)
        col_names = ", ".join(f'"{c.name}"' for c in columns)
        qualified = self._qualified(table)
        per_batch = _rows_per_batch(len(columns))
        # Resolve each column's type family and PK-ness once per table rather
        # than once per generated value.
        col_specs = [(c, _type_family(c), c.name in pk_set) for c in columns]

        # One multi-row VALUES statement per batch rather than passing a list of
        # dicts to conn.execute (which becomes executemany). Against a remote
        # CockroachDB Cloud cluster the wall time here is dominated by round
        # trips, not by row generation, so collapsing a batch into a single
        # statement is the difference that matters.
        inserted = 0
        for start in range(0, target, per_batch):
            count = min(per_batch, target - start)
            tuples: list[str] = []
            params: dict[str, object] = {}
            for offset in range(count):
                row_index = start + offset
                names = []
                for col_pos, (column, family, is_pk) in enumerate(col_specs):
                    key = f"p{offset}_{col_pos}"
                    params[key] = self._value_for(
                        column, row_index=row_index, is_pk=is_pk, family=family
                    )
                    names.append(f":{key}")
                tuples.append(f"({', '.join(names)})")
            stmt = text(
                f"INSERT INTO {qualified} ({col_names}) VALUES {', '.join(tuples)}"
            )
            await conn.execute(stmt, params)
            inserted += count
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
        family: str | None = None,
    ) -> object:
        # `family` is passed in by _load_rows, which resolves it once per column.
        # Deriving it here instead costs one _type_family call per *value*: at
        # 45k rows x 40 columns that was 1.8M calls and a measured 4.2s of the
        # seed, for an answer that cannot change within a table.
        if family is None:
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
