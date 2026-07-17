from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.logging import get_logger
from app.schema_analysis.connection import normalize_target_database_url
from app.schema_analysis.models import (
    ColumnMetadata,
    DatabaseMetadata,
    TableMetadata,
)

logger = get_logger(__name__)

_SYSTEM_SCHEMAS = frozenset(
    {"information_schema", "pg_catalog", "crdb_internal", "pg_extension"}
)


@dataclass
class SchemaLoadReport:
    """What the loader recreated on the shadow cluster."""

    schemas_created: int = 0
    tables_created: int = 0
    columns_created: int = 0
    primary_keys_created: int = 0
    indexes_created: int = 0
    foreign_keys_created: int = 0
    constraints_created: int = 0
    warnings: list[str] = field(default_factory=list)


class ShadowSchemaLoader:
    """Recreate a customer's schema *structure* on a shadow cluster from a
    Phase 6 ``DatabaseMetadata`` snapshot: schemas, tables, columns, primary
    keys, foreign keys, indexes, and CHECK/UNIQUE constraints.

    Tables are created first (columns + PK inline), then foreign keys and other
    constraints are added by ALTER so cross-table references resolve regardless
    of creation order. Runs under AUTOCOMMIT because CockroachDB rejects a schema
    change that follows a write in the same transaction and processes DDL as
    online jobs.
    """

    async def load(
        self,
        connection_url: str,
        metadata: DatabaseMetadata,
        *,
        statement_timeout_ms: int = 300_000,
    ) -> SchemaLoadReport:
        normalized = normalize_target_database_url(connection_url, force_cockroach=True)
        engine = create_async_engine(normalized, pool_pre_ping=True)
        report = SchemaLoadReport()
        try:
            async with engine.connect() as raw:
                conn = await raw.execution_options(isolation_level="AUTOCOMMIT")
                await conn.execute(
                    text(f"SET statement_timeout = {int(statement_timeout_ms)}")
                )
                tables: list[TableMetadata] = []
                for schema in metadata.schemas:
                    if schema.name in _SYSTEM_SCHEMAS:
                        continue
                    if schema.name != "public":
                        await conn.execute(
                            text(f'CREATE SCHEMA IF NOT EXISTS "{schema.name}"')
                        )
                        report.schemas_created += 1
                    tables.extend(schema.tables)

                # 1) tables (columns + primary key)
                for table in tables:
                    await conn.execute(text(self._create_table_ddl(table)))
                    report.tables_created += 1
                    report.columns_created += len(table.columns)
                    if table.primary_key:
                        report.primary_keys_created += 1

                # 2) secondary indexes
                for table in tables:
                    report.indexes_created += await self._create_indexes(conn, table)

                # 3) foreign keys (all tables now exist)
                for table in tables:
                    report.foreign_keys_created += await self._create_foreign_keys(
                        conn, table, report
                    )

                # 4) CHECK / UNIQUE constraints
                for table in tables:
                    report.constraints_created += await self._create_constraints(
                        conn, table, report
                    )
        finally:
            await engine.dispose()

        logger.info(
            "Loaded schema onto shadow",
            extra={
                "tables": report.tables_created,
                "foreign_keys": report.foreign_keys_created,
                "constraints": report.constraints_created,
            },
        )
        return report

    # -- DDL builders -------------------------------------------------------

    def _create_table_ddl(self, table: TableMetadata) -> str:
        cols = [
            self._column_ddl(c)
            for c in sorted(table.columns, key=lambda c: c.ordinal_position)
        ]
        if table.primary_key:
            pk = ", ".join(f'"{c}"' for c in table.primary_key)
            cols.append(f"PRIMARY KEY ({pk})")
        return (
            f"CREATE TABLE IF NOT EXISTS {self._qualified(table)} "
            f"(\n  " + ",\n  ".join(cols) + "\n)"
        )

    def _column_ddl(self, column: ColumnMetadata) -> str:
        nullable = "" if column.is_nullable else " NOT NULL"
        return f'"{column.name}" {map_column_type(column)}{nullable}'

    async def _create_indexes(self, conn, table: TableMetadata) -> int:
        created = 0
        for index in table.indexes:
            if index.is_primary or not index.columns:
                continue
            cols = ", ".join(f'"{c}"' for c in index.columns)
            unique = "UNIQUE " if index.is_unique else ""
            name = f"{table.name}_{index.name}"[:120]
            try:
                await conn.execute(
                    text(
                        f'CREATE {unique}INDEX IF NOT EXISTS "{name}" '
                        f"ON {self._qualified(table)} ({cols})"
                    )
                )
                created += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("skipped index", extra={"index": index.name})
        return created

    async def _create_foreign_keys(
        self, conn, table: TableMetadata, report: SchemaLoadReport
    ) -> int:
        created = 0
        for fk in table.foreign_keys:
            cols = ", ".join(f'"{c}"' for c in fk.constrained_columns)
            ref_cols = ", ".join(f'"{c}"' for c in fk.referred_columns)
            ref = self._qualified_name(fk.referred_schema, fk.referred_table)
            name = f"{table.name}_{fk.name}"[:120]
            stmt = (
                f"ALTER TABLE {self._qualified(table)} "
                f'ADD CONSTRAINT "{name}" FOREIGN KEY ({cols}) '
                f"REFERENCES {ref} ({ref_cols})"
            )
            if fk.on_delete:
                stmt += f" ON DELETE {fk.on_delete}"
            if fk.on_update:
                stmt += f" ON UPDATE {fk.on_update}"
            try:
                await conn.execute(text(stmt))
                created += 1
            except Exception as exc:  # noqa: BLE001
                report.warnings.append(f"FK {fk.name} on {table.name}: {exc}")
        return created

    async def _create_constraints(
        self, conn, table: TableMetadata, report: SchemaLoadReport
    ) -> int:
        created = 0
        for c in table.constraints:
            ctype = c.constraint_type.upper()
            name = f"{table.name}_{c.name}"[:120]
            if "PRIMARY" in ctype or "FOREIGN" in ctype:
                continue  # handled inline / separately
            if "UNIQUE" in ctype and c.columns:
                cols = ", ".join(f'"{col}"' for col in c.columns)
                stmt = (
                    f"ALTER TABLE {self._qualified(table)} "
                    f'ADD CONSTRAINT "{name}" UNIQUE ({cols})'
                )
            elif "CHECK" in ctype and c.definition:
                stmt = (
                    f"ALTER TABLE {self._qualified(table)} "
                    f'ADD CONSTRAINT "{name}" {c.definition}'
                    if c.definition.upper().startswith("CHECK")
                    else f"ALTER TABLE {self._qualified(table)} "
                    f'ADD CONSTRAINT "{name}" CHECK ({c.definition})'
                )
            else:
                continue
            try:
                await conn.execute(text(stmt))
                created += 1
            except Exception as exc:  # noqa: BLE001
                report.warnings.append(f"constraint {c.name} on {table.name}: {exc}")
        return created

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _qualified(table: TableMetadata) -> str:
        return ShadowSchemaLoader._qualified_name(table.schema_name, table.name)

    @staticmethod
    def _qualified_name(schema: str | None, name: str) -> str:
        if schema and schema != "public":
            return f'"{schema}"."{name}"'
        return f'"{name}"'


def type_family(column: ColumnMetadata) -> str:
    raw = (column.udt_name or column.data_type or "").lower()
    if "uuid" in raw:
        return "uuid"
    if "bool" in raw:
        return "bool"
    if "timestamp" in raw:
        return "timestamp"
    if raw == "date":
        return "date"
    if "json" in raw:
        return "json"
    if any(k in raw for k in ("bytea", "bytes", "blob")):
        return "bytes"
    if any(k in raw for k in ("int", "serial")):
        return "int"
    if any(k in raw for k in ("numeric", "decimal", "real", "double", "float")):
        return "float"
    return "string"


def map_column_type(column: ColumnMetadata) -> str:
    """Map a snapshot column onto a CockroachDB-compatible column type."""
    fam = type_family(column)
    base = {
        "uuid": "UUID",
        "bool": "BOOL",
        "timestamp": "TIMESTAMPTZ",
        "date": "DATE",
        "json": "JSONB",
        "bytes": "BYTES",
        "int": "INT8",
        "float": "FLOAT8",
    }
    if fam in base:
        return base[fam]
    if column.character_maximum_length and column.character_maximum_length > 0:
        return f"VARCHAR({column.character_maximum_length})"
    return "STRING"
