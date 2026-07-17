from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.logging import get_logger

logger = get_logger(__name__)

# Namespaces that are implementation internals, not customer schema.
_EXCLUDED_SCHEMAS = frozenset(
    {
        "information_schema",
        "pg_catalog",
        "pg_toast",
        "crdb_internal",
        "pg_extension",
    }
)


@dataclass(slots=True)
class RawColumn:
    table_schema: str
    table_name: str
    column_name: str
    data_type: str
    udt_name: str | None
    is_nullable: bool
    column_default: str | None
    ordinal_position: int
    character_maximum_length: int | None
    numeric_precision: int | None
    numeric_scale: int | None


@dataclass(slots=True)
class RawForeignKey:
    constraint_name: str
    table_schema: str
    table_name: str
    column_name: str
    foreign_table_schema: str
    foreign_table_name: str
    foreign_column_name: str
    ordinal_position: int
    update_rule: str | None
    delete_rule: str | None


@dataclass(slots=True)
class RawIndex:
    table_schema: str
    table_name: str
    index_name: str
    column_name: str
    ordinal_position: int
    is_unique: bool
    is_primary: bool
    index_type: str | None
    index_definition: str | None


@dataclass(slots=True)
class RawConstraint:
    table_schema: str
    table_name: str
    constraint_name: str
    constraint_type: str
    column_name: str | None
    ordinal_position: int | None
    check_clause: str | None


@dataclass(slots=True)
class RawTableStats:
    table_schema: str
    table_name: str
    estimated_row_count: int | None
    estimated_size_bytes: int | None


@dataclass(slots=True)
class RawSchemaSnapshot:
    database_name: str
    server_version: str | None
    schemas: list[str]
    tables: list[tuple[str, str]]  # (schema, table)
    columns: list[RawColumn]
    primary_keys: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    foreign_keys: list[RawForeignKey] = field(default_factory=list)
    indexes: list[RawIndex] = field(default_factory=list)
    constraints: list[RawConstraint] = field(default_factory=list)
    table_stats: dict[tuple[str, str], RawTableStats] = field(default_factory=dict)
    estimated_database_size_bytes: int | None = None


class SchemaInspector:
    """Low-level read-only collector for PostgreSQL-compatible catalogs.

    Performs SQL against information_schema / pg_catalog only. Does not
    assemble Pydantic models or apply prediction-oriented analysis.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def collect(
        self,
        *,
        include_schemas: frozenset[str] | None = None,
    ) -> RawSchemaSnapshot:
        database_name = await self._fetch_database_name()
        server_version = await self._fetch_server_version()
        is_cockroach = _is_cockroachdb(
            server_version,
            dialect_name=self._connection.engine.dialect.name,
        )
        schemas = await self._fetch_schemas(include_schemas=include_schemas)
        tables = await self._fetch_tables(schemas)
        columns = await self._fetch_columns(schemas) if tables else []
        primary_keys = await self._fetch_primary_keys(schemas) if tables else {}
        foreign_keys = await self._fetch_foreign_keys(schemas) if tables else []
        indexes = await self._fetch_indexes(schemas) if tables else []
        constraints = await self._fetch_constraints(schemas) if tables else []
        table_stats = (
            await self._fetch_table_stats(tables, is_cockroach=is_cockroach)
            if tables
            else {}
        )
        db_size = await self._fetch_database_size(is_cockroach=is_cockroach)

        logger.info(
            "Collected raw schema snapshot",
            extra={
                "database_name": database_name,
                "schema_count": len(schemas),
                "table_count": len(tables),
                "is_cockroach": is_cockroach,
            },
        )

        return RawSchemaSnapshot(
            database_name=database_name,
            server_version=server_version,
            schemas=schemas,
            tables=tables,
            columns=columns,
            primary_keys=primary_keys,
            foreign_keys=foreign_keys,
            indexes=indexes,
            constraints=constraints,
            table_stats=table_stats,
            estimated_database_size_bytes=db_size,
        )

    async def _fetch_database_name(self) -> str:
        result = await self._connection.execute(text("SELECT current_database()"))
        return str(result.scalar_one())

    async def _fetch_server_version(self) -> str | None:
        try:
            result = await self._connection.execute(text("SELECT version()"))
            value = result.scalar_one_or_none()
            return str(value) if value is not None else None
        except Exception:
            await self._connection.rollback()
            logger.warning("Unable to read server version")
            return None

    async def _fetch_schemas(
        self,
        *,
        include_schemas: frozenset[str] | None,
    ) -> list[str]:
        result = await self._connection.execute(
            text(
                """
                SELECT schema_name
                FROM information_schema.schemata
                ORDER BY schema_name
                """
            )
        )
        schemas = [str(row[0]) for row in result.all()]
        filtered = [
            name
            for name in schemas
            if name not in _EXCLUDED_SCHEMAS
            and not name.startswith("pg_temp")
            and not name.startswith("pg_toast")
        ]
        if include_schemas is not None:
            filtered = [name for name in filtered if name in include_schemas]
        return filtered

    async def _fetch_tables(self, schemas: list[str]) -> list[tuple[str, str]]:
        if not schemas:
            return []
        result = await self._connection.execute(
            text(
                """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_type = 'BASE TABLE'
                  AND table_schema = ANY(:schemas)
                ORDER BY table_schema, table_name
                """
            ),
            {"schemas": schemas},
        )
        return [(str(row[0]), str(row[1])) for row in result.all()]

    async def _fetch_columns(self, schemas: list[str]) -> list[RawColumn]:
        result = await self._connection.execute(
            text(
                """
                SELECT
                    table_schema,
                    table_name,
                    column_name,
                    data_type,
                    udt_name,
                    is_nullable,
                    column_default,
                    ordinal_position,
                    character_maximum_length,
                    numeric_precision,
                    numeric_scale
                FROM information_schema.columns
                WHERE table_schema = ANY(:schemas)
                ORDER BY table_schema, table_name, ordinal_position
                """
            ),
            {"schemas": schemas},
        )
        columns: list[RawColumn] = []
        for row in result.mappings().all():
            columns.append(
                RawColumn(
                    table_schema=str(row["table_schema"]),
                    table_name=str(row["table_name"]),
                    column_name=str(row["column_name"]),
                    data_type=str(row["data_type"]),
                    udt_name=str(row["udt_name"]) if row["udt_name"] is not None else None,
                    is_nullable=str(row["is_nullable"]).upper() == "YES",
                    column_default=(
                        str(row["column_default"])
                        if row["column_default"] is not None
                        else None
                    ),
                    ordinal_position=int(row["ordinal_position"]),
                    character_maximum_length=_as_optional_int(
                        row["character_maximum_length"]
                    ),
                    numeric_precision=_as_optional_int(row["numeric_precision"]),
                    numeric_scale=_as_optional_int(row["numeric_scale"]),
                )
            )
        return columns

    async def _fetch_primary_keys(
        self,
        schemas: list[str],
    ) -> dict[tuple[str, str], list[str]]:
        result = await self._connection.execute(
            text(
                """
                SELECT
                    tc.table_schema,
                    tc.table_name,
                    kcu.column_name,
                    kcu.ordinal_position
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_schema = kcu.constraint_schema
                 AND tc.constraint_name = kcu.constraint_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_schema = ANY(:schemas)
                ORDER BY
                    tc.table_schema,
                    tc.table_name,
                    kcu.ordinal_position
                """
            ),
            {"schemas": schemas},
        )
        primary_keys: dict[tuple[str, str], list[str]] = defaultdict(list)
        for row in result.all():
            key = (str(row[0]), str(row[1]))
            primary_keys[key].append(str(row[2]))
        return dict(primary_keys)

    async def _fetch_foreign_keys(self, schemas: list[str]) -> list[RawForeignKey]:
        # Join referenced columns via referential_constraints + ordinal_position
        # so composite foreign keys do not cartesian-product.
        result = await self._connection.execute(
            text(
                """
                SELECT
                    tc.constraint_name,
                    kcu.table_schema,
                    kcu.table_name,
                    kcu.column_name,
                    ccu.table_schema AS foreign_table_schema,
                    ccu.table_name AS foreign_table_name,
                    ccu.column_name AS foreign_column_name,
                    kcu.ordinal_position,
                    rc.update_rule,
                    rc.delete_rule
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_schema = kcu.constraint_schema
                 AND tc.constraint_name = kcu.constraint_name
                JOIN information_schema.referential_constraints AS rc
                  ON tc.constraint_schema = rc.constraint_schema
                 AND tc.constraint_name = rc.constraint_name
                JOIN information_schema.key_column_usage AS ccu
                  ON rc.unique_constraint_schema = ccu.constraint_schema
                 AND rc.unique_constraint_name = ccu.constraint_name
                 AND kcu.ordinal_position = ccu.ordinal_position
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND kcu.table_schema = ANY(:schemas)
                ORDER BY
                    kcu.table_schema,
                    kcu.table_name,
                    tc.constraint_name,
                    kcu.ordinal_position
                """
            ),
            {"schemas": schemas},
        )
        foreign_keys: list[RawForeignKey] = []
        for row in result.mappings().all():
            foreign_keys.append(
                RawForeignKey(
                    constraint_name=str(row["constraint_name"]),
                    table_schema=str(row["table_schema"]),
                    table_name=str(row["table_name"]),
                    column_name=str(row["column_name"]),
                    foreign_table_schema=str(row["foreign_table_schema"]),
                    foreign_table_name=str(row["foreign_table_name"]),
                    foreign_column_name=str(row["foreign_column_name"]),
                    ordinal_position=int(row["ordinal_position"]),
                    update_rule=(
                        str(row["update_rule"]) if row["update_rule"] is not None else None
                    ),
                    delete_rule=(
                        str(row["delete_rule"]) if row["delete_rule"] is not None else None
                    ),
                )
            )
        return foreign_keys

    async def _fetch_indexes(self, schemas: list[str]) -> list[RawIndex]:
        # pg_catalog is available on PostgreSQL and CockroachDB.
        result = await self._connection.execute(
            text(
                """
                SELECT
                    n.nspname AS table_schema,
                    t.relname AS table_name,
                    i.relname AS index_name,
                    a.attname AS column_name,
                    x.ordinality AS ordinal_position,
                    ix.indisunique AS is_unique,
                    ix.indisprimary AS is_primary,
                    am.amname AS index_type,
                    pg_get_indexdef(ix.indexrelid) AS index_definition
                FROM pg_index AS ix
                JOIN pg_class AS t ON t.oid = ix.indrelid
                JOIN pg_class AS i ON i.oid = ix.indexrelid
                JOIN pg_namespace AS n ON n.oid = t.relnamespace
                JOIN pg_am AS am ON am.oid = i.relam
                CROSS JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS x(attnum, ordinality)
                JOIN pg_attribute AS a
                  ON a.attrelid = t.oid
                 AND a.attnum = x.attnum
                WHERE n.nspname = ANY(:schemas)
                  AND t.relkind = 'r'
                  AND a.attnum > 0
                ORDER BY
                    n.nspname,
                    t.relname,
                    i.relname,
                    x.ordinality
                """
            ),
            {"schemas": schemas},
        )
        indexes: list[RawIndex] = []
        for row in result.mappings().all():
            indexes.append(
                RawIndex(
                    table_schema=str(row["table_schema"]),
                    table_name=str(row["table_name"]),
                    index_name=str(row["index_name"]),
                    column_name=str(row["column_name"]),
                    ordinal_position=int(row["ordinal_position"]),
                    is_unique=bool(row["is_unique"]),
                    is_primary=bool(row["is_primary"]),
                    index_type=(
                        str(row["index_type"]) if row["index_type"] is not None else None
                    ),
                    index_definition=(
                        str(row["index_definition"])
                        if row["index_definition"] is not None
                        else None
                    ),
                )
            )
        return indexes

    async def _fetch_constraints(self, schemas: list[str]) -> list[RawConstraint]:
        result = await self._connection.execute(
            text(
                """
                SELECT
                    tc.table_schema,
                    tc.table_name,
                    tc.constraint_name,
                    tc.constraint_type,
                    kcu.column_name,
                    kcu.ordinal_position,
                    cc.check_clause
                FROM information_schema.table_constraints AS tc
                LEFT JOIN information_schema.key_column_usage AS kcu
                  ON tc.constraint_schema = kcu.constraint_schema
                 AND tc.constraint_name = kcu.constraint_name
                LEFT JOIN information_schema.check_constraints AS cc
                  ON tc.constraint_schema = cc.constraint_schema
                 AND tc.constraint_name = cc.constraint_name
                WHERE tc.table_schema = ANY(:schemas)
                ORDER BY
                    tc.table_schema,
                    tc.table_name,
                    tc.constraint_name,
                    kcu.ordinal_position
                """
            ),
            {"schemas": schemas},
        )
        constraints: list[RawConstraint] = []
        for row in result.mappings().all():
            constraints.append(
                RawConstraint(
                    table_schema=str(row["table_schema"]),
                    table_name=str(row["table_name"]),
                    constraint_name=str(row["constraint_name"]),
                    constraint_type=str(row["constraint_type"]),
                    column_name=(
                        str(row["column_name"]) if row["column_name"] is not None else None
                    ),
                    ordinal_position=_as_optional_int(row["ordinal_position"]),
                    check_clause=(
                        str(row["check_clause"])
                        if row["check_clause"] is not None
                        else None
                    ),
                )
            )
        return constraints

    async def _fetch_table_stats(
        self,
        tables: list[tuple[str, str]],
        *,
        is_cockroach: bool,
    ) -> dict[tuple[str, str], RawTableStats]:
        if not tables:
            return {}

        by_schema: dict[str, list[str]] = defaultdict(list)
        for schema_name, table_name in tables:
            by_schema[schema_name].append(table_name)

        stats: dict[tuple[str, str], RawTableStats] = {}
        for schema_name, table_names in by_schema.items():
            if is_cockroach:
                row_counts = await self._fetch_cockroach_row_estimates(schema_name)
            else:
                row_counts = await self._fetch_row_estimates(schema_name, table_names)

            sizes = await self._fetch_table_sizes(
                schema_name,
                table_names,
                is_cockroach=is_cockroach,
            )
            for table_name in table_names:
                key = (schema_name, table_name)
                stats[key] = RawTableStats(
                    table_schema=schema_name,
                    table_name=table_name,
                    estimated_row_count=row_counts.get(table_name),
                    estimated_size_bytes=sizes.get(table_name),
                )

        for schema_name, table_name in tables:
            key = (schema_name, table_name)
            if key not in stats:
                stats[key] = RawTableStats(
                    table_schema=schema_name,
                    table_name=table_name,
                    estimated_row_count=None,
                    estimated_size_bytes=None,
                )
        return stats

    async def _fetch_row_estimates(
        self,
        schema_name: str,
        table_names: list[str],
    ) -> dict[str, int | None]:
        result = await self._connection.execute(
            text(
                """
                SELECT
                    c.relname AS table_name,
                    GREATEST(c.reltuples::bigint, 0) AS estimated_row_count
                FROM pg_class AS c
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                WHERE c.relkind = 'r'
                  AND n.nspname = :schema_name
                  AND c.relname = ANY(:table_names)
                """
            ),
            {"schema_name": schema_name, "table_names": table_names},
        )
        return {
            str(row["table_name"]): _as_optional_int(row["estimated_row_count"])
            for row in result.mappings().all()
        }

    async def _fetch_cockroach_row_estimates(
        self,
        schema_name: str,
    ) -> dict[str, int | None]:
        """CockroachDB Cloud exposes reliable row estimates via SHOW TABLES."""
        if not _is_safe_sql_identifier(schema_name):
            logger.warning(
                "Skipping CockroachDB row estimates for unsafe schema name",
                extra={"schema": schema_name},
            )
            return {}

        quoted = schema_name.replace('"', '""')
        try:
            result = await self._connection.execute(
                text(
                    f'SELECT table_name, estimated_row_count '
                    f'FROM [SHOW TABLES FROM "{quoted}"]'
                )
            )
            return {
                str(row["table_name"]): _as_optional_int(row["estimated_row_count"])
                for row in result.mappings().all()
            }
        except Exception:
            await self._connection.rollback()
            logger.warning(
                "Unable to read CockroachDB SHOW TABLES row estimates",
                extra={"schema": schema_name},
            )
            return {}

    async def _fetch_table_sizes(
        self,
        schema_name: str,
        table_names: list[str],
        *,
        is_cockroach: bool,
    ) -> dict[str, int | None]:
        if is_cockroach:
            return await self._fetch_cockroach_table_sizes(schema_name, table_names)
        return await self._fetch_postgres_table_sizes(schema_name, table_names)

    async def _fetch_postgres_table_sizes(
        self,
        schema_name: str,
        table_names: list[str],
    ) -> dict[str, int | None]:
        try:
            result = await self._connection.execute(
                text(
                    """
                    SELECT
                        c.relname AS table_name,
                        pg_total_relation_size(c.oid)::bigint AS estimated_size_bytes
                    FROM pg_class AS c
                    JOIN pg_namespace AS n ON n.oid = c.relnamespace
                    WHERE c.relkind = 'r'
                      AND n.nspname = :schema_name
                      AND c.relname = ANY(:table_names)
                    """
                ),
                {"schema_name": schema_name, "table_names": table_names},
            )
            return {
                str(row["table_name"]): _as_optional_int(row["estimated_size_bytes"])
                for row in result.mappings().all()
            }
        except Exception:
            await self._connection.rollback()
            logger.warning(
                "Unable to estimate PostgreSQL table sizes",
                extra={"schema": schema_name},
            )
            return {}

    async def _fetch_cockroach_table_sizes(
        self,
        schema_name: str,
        table_names: list[str],
    ) -> dict[str, int | None]:
        """Best-effort size estimates.

        CockroachDB Cloud restricts ``crdb_internal`` size views. When size
        APIs are unavailable, return an empty mapping so callers keep nulls.
        """
        try:
            result = await self._connection.execute(
                text(
                    """
                    SELECT
                        schema_name,
                        table_name,
                        approximate_disk_bytes::bigint AS estimated_size_bytes
                    FROM crdb_internal.table_sizes
                    WHERE database_name = current_database()
                      AND schema_name = :schema_name
                      AND table_name = ANY(:table_names)
                    """
                ),
                {"schema_name": schema_name, "table_names": table_names},
            )
            return {
                str(row["table_name"]): _as_optional_int(row["estimated_size_bytes"])
                for row in result.mappings().all()
            }
        except Exception:
            # Expected on CockroachDB Cloud without unsafe internals.
            await self._connection.rollback()
            logger.info(
                "Table size estimates unavailable on this CockroachDB target",
                extra={"schema": schema_name},
            )
            return {}

    async def _fetch_database_size(self, *, is_cockroach: bool) -> int | None:
        if is_cockroach:
            try:
                result = await self._connection.execute(
                    text(
                        """
                        SELECT COALESCE(SUM(approximate_disk_bytes), 0)::bigint
                        FROM crdb_internal.table_sizes
                        WHERE database_name = current_database()
                        """
                    )
                )
                return _as_optional_int(result.scalar_one_or_none())
            except Exception:
                await self._connection.rollback()
                logger.info(
                    "Database size estimate unavailable on this CockroachDB target"
                )
                return None

        try:
            result = await self._connection.execute(
                text("SELECT pg_database_size(current_database())::bigint")
            )
            return _as_optional_int(result.scalar_one_or_none())
        except Exception:
            await self._connection.rollback()
            logger.warning("Unable to estimate database size")
            return None


def _is_cockroachdb(
    server_version: str | None,
    *,
    dialect_name: str | None = None,
) -> bool:
    if dialect_name and "cockroach" in dialect_name.lower():
        return True
    if not server_version:
        return False
    return "cockroachdb" in server_version.lower()


def _is_safe_sql_identifier(value: str) -> bool:
    if not value:
        return False
    if value[0].isdigit():
        return False
    return all(ch.isalnum() or ch == "_" for ch in value)


def _as_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
