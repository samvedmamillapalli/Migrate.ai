from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.logging import get_logger
from app.schema_analysis.connection import SchemaAnalysisConnection
from app.schema_analysis.errors import host_and_database_from_url, safe_log_target
from app.schema_analysis.inspector import (
    RawConstraint,
    RawForeignKey,
    RawIndex,
    RawSchemaSnapshot,
    SchemaInspector,
)
from app.schema_analysis.models import (
    ColumnMetadata,
    ConstraintMetadata,
    DatabaseMetadata,
    ForeignKeyMetadata,
    IndexMetadata,
    SchemaMetadata,
    TableMetadata,
)
from app.schema_analysis.read_only import enforce_session_read_only

logger = get_logger(__name__)


class SchemaAnalyzer:
    """Assemble structured database metadata suitable for AI prediction.

    Owns orchestration and analysis. Persistence, HTTP, and migration
    execution are intentionally out of scope.
    """

    async def analyze(
        self,
        database_url: str,
        *,
        include_schemas: frozenset[str] | None = None,
        connect_timeout: int = 30,
        statement_timeout_ms: int = 60_000,
    ) -> DatabaseMetadata:
        try:
            return await self._analyze_with_connection(
                database_url,
                include_schemas=include_schemas,
                connect_timeout=connect_timeout,
                statement_timeout_ms=statement_timeout_ms,
                force_cockroach=False,
            )
        except AssertionError as exc:
            # Vanilla postgresql dialect cannot parse CockroachDB version strings.
            if "Could not determine version" not in str(exc):
                raise
            logger.info(
                "Retrying schema analysis with CockroachDB dialect",
                extra=safe_log_target(*host_and_database_from_url(database_url)),
            )
            return await self._analyze_with_connection(
                database_url,
                include_schemas=include_schemas,
                connect_timeout=connect_timeout,
                statement_timeout_ms=statement_timeout_ms,
                force_cockroach=True,
            )

    async def _analyze_with_connection(
        self,
        database_url: str,
        *,
        include_schemas: frozenset[str] | None,
        connect_timeout: int,
        statement_timeout_ms: int,
        force_cockroach: bool,
    ) -> DatabaseMetadata:
        async with SchemaAnalysisConnection(
            database_url,
            connect_timeout=connect_timeout,
            statement_timeout_ms=statement_timeout_ms,
            force_cockroach=force_cockroach,
        ) as target:
            async with target.connection() as connection:
                inspector = SchemaInspector(connection)
                snapshot = await inspector.collect(include_schemas=include_schemas)
                metadata = self._build_metadata(snapshot)

        logger.info(
            "Schema analysis complete",
            extra={
                **safe_log_target(*host_and_database_from_url(database_url)),
                "schema_count": metadata.schema_count,
                "table_count": metadata.table_count,
            },
        )
        return metadata

    async def analyze_connection(
        self,
        connection: SchemaAnalysisConnection,
        *,
        include_schemas: frozenset[str] | None = None,
        enforce_read_only: bool = True,
    ) -> DatabaseMetadata:
        """Analyze using an already-open connection manager."""
        async with connection.connection() as conn:
            return await self.analyze_open_connection(
                conn,
                include_schemas=include_schemas,
                enforce_read_only=enforce_read_only,
            )

    async def analyze_open_connection(
        self,
        connection: AsyncConnection,
        *,
        include_schemas: frozenset[str] | None = None,
        enforce_read_only: bool = True,
    ) -> DatabaseMetadata:
        """Analyze using an already-acquired async connection."""
        if enforce_read_only:
            await enforce_session_read_only(connection)
        inspector = SchemaInspector(connection)
        snapshot = await inspector.collect(include_schemas=include_schemas)
        return self._build_metadata(snapshot)

    def _build_metadata(self, snapshot: RawSchemaSnapshot) -> DatabaseMetadata:
        columns_by_table: dict[tuple[str, str], list] = defaultdict(list)
        for column in snapshot.columns:
            columns_by_table[(column.table_schema, column.table_name)].append(column)

        fks_by_table = self._group_foreign_keys(snapshot.foreign_keys)
        indexes_by_table = self._group_indexes(snapshot.indexes)
        constraints_by_table = self._group_constraints(snapshot.constraints)

        schemas: list[SchemaMetadata] = []
        total_tables = 0

        for schema_name in snapshot.schemas:
            table_names = [
                table_name
                for table_schema, table_name in snapshot.tables
                if table_schema == schema_name
            ]
            tables: list[TableMetadata] = []
            for table_name in table_names:
                key = (schema_name, table_name)
                primary_key = list(snapshot.primary_keys.get(key, []))
                pk_set = set(primary_key)

                unique_columns = {
                    column_name
                    for constraint in constraints_by_table.get(key, [])
                    if constraint.constraint_type == "UNIQUE"
                    for column_name in constraint.columns
                }

                column_models = [
                    ColumnMetadata(
                        name=column.column_name,
                        data_type=column.data_type,
                        udt_name=column.udt_name,
                        is_nullable=column.is_nullable,
                        column_default=column.column_default,
                        ordinal_position=column.ordinal_position,
                        character_maximum_length=column.character_maximum_length,
                        numeric_precision=column.numeric_precision,
                        numeric_scale=column.numeric_scale,
                        is_primary_key=column.column_name in pk_set,
                        is_unique=column.column_name in unique_columns
                        or column.column_name in pk_set,
                    )
                    for column in columns_by_table.get(key, [])
                ]

                stats = snapshot.table_stats.get(key)
                tables.append(
                    TableMetadata(
                        name=table_name,
                        schema_name=schema_name,
                        column_count=len(column_models),
                        columns=column_models,
                        primary_key=primary_key,
                        foreign_keys=fks_by_table.get(key, []),
                        indexes=indexes_by_table.get(key, []),
                        constraints=constraints_by_table.get(key, []),
                        estimated_row_count=(
                            stats.estimated_row_count if stats is not None else None
                        ),
                        estimated_size_bytes=(
                            stats.estimated_size_bytes if stats is not None else None
                        ),
                    )
                )

            schemas.append(
                SchemaMetadata(
                    name=schema_name,
                    tables=tables,
                    table_count=len(tables),
                )
            )
            total_tables += len(tables)

        return DatabaseMetadata(
            database_name=snapshot.database_name,
            server_version=snapshot.server_version,
            schemas=schemas,
            schema_count=len(schemas),
            table_count=total_tables,
            estimated_size_bytes=snapshot.estimated_database_size_bytes,
            inspected_at=datetime.now(UTC),
        )

    @staticmethod
    def _group_foreign_keys(
        raw_foreign_keys: list[RawForeignKey],
    ) -> dict[tuple[str, str], list[ForeignKeyMetadata]]:
        grouped: dict[tuple[str, str], dict[str, list[RawForeignKey]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for fk in raw_foreign_keys:
            key = (fk.table_schema, fk.table_name)
            grouped[key][fk.constraint_name].append(fk)

        result: dict[tuple[str, str], list[ForeignKeyMetadata]] = {}
        for table_key, constraints in grouped.items():
            models: list[ForeignKeyMetadata] = []
            for constraint_name, rows in constraints.items():
                ordered = sorted(rows, key=lambda item: item.ordinal_position)
                first = ordered[0]
                models.append(
                    ForeignKeyMetadata(
                        name=constraint_name,
                        constrained_columns=[row.column_name for row in ordered],
                        referred_schema=first.foreign_table_schema,
                        referred_table=first.foreign_table_name,
                        referred_columns=[row.foreign_column_name for row in ordered],
                        on_update=first.update_rule,
                        on_delete=first.delete_rule,
                    )
                )
            result[table_key] = models
        return result

    @staticmethod
    def _group_indexes(
        raw_indexes: list[RawIndex],
    ) -> dict[tuple[str, str], list[IndexMetadata]]:
        grouped: dict[tuple[str, str], dict[str, list[RawIndex]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for index in raw_indexes:
            key = (index.table_schema, index.table_name)
            grouped[key][index.index_name].append(index)

        result: dict[tuple[str, str], list[IndexMetadata]] = {}
        for table_key, indexes in grouped.items():
            models: list[IndexMetadata] = []
            for index_name, rows in indexes.items():
                ordered = sorted(rows, key=lambda item: item.ordinal_position)
                first = ordered[0]
                models.append(
                    IndexMetadata(
                        name=index_name,
                        columns=[row.column_name for row in ordered],
                        is_unique=first.is_unique,
                        is_primary=first.is_primary,
                        index_type=first.index_type,
                        definition=first.index_definition,
                    )
                )
            result[table_key] = models
        return result

    @staticmethod
    def _group_constraints(
        raw_constraints: list[RawConstraint],
    ) -> dict[tuple[str, str], list[ConstraintMetadata]]:
        grouped: dict[tuple[str, str], dict[str, list[RawConstraint]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for constraint in raw_constraints:
            key = (constraint.table_schema, constraint.table_name)
            grouped[key][constraint.constraint_name].append(constraint)

        result: dict[tuple[str, str], list[ConstraintMetadata]] = {}
        for table_key, constraints in grouped.items():
            models: list[ConstraintMetadata] = []
            for constraint_name, rows in constraints.items():
                ordered = sorted(
                    rows,
                    key=lambda item: item.ordinal_position or 0,
                )
                first = ordered[0]
                columns = [
                    row.column_name
                    for row in ordered
                    if row.column_name is not None
                ]
                # Deduplicate while preserving order (CHECK constraints may
                # join without column rows and produce a single None).
                seen: set[str] = set()
                unique_columns: list[str] = []
                for column_name in columns:
                    if column_name not in seen:
                        seen.add(column_name)
                        unique_columns.append(column_name)

                models.append(
                    ConstraintMetadata(
                        name=constraint_name,
                        constraint_type=first.constraint_type,
                        columns=unique_columns,
                        definition=first.check_clause,
                    )
                )
            result[table_key] = models
        return result
