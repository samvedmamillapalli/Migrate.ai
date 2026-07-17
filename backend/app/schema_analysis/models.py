from __future__ import annotations

from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ColumnMetadata(BaseModel):
    """Column-level metadata for a single table."""

    model_config = ConfigDict(frozen=True)

    name: str
    data_type: str
    udt_name: str | None = None
    is_nullable: bool
    column_default: str | None = None
    ordinal_position: int
    character_maximum_length: int | None = None
    numeric_precision: int | None = None
    numeric_scale: int | None = None
    is_primary_key: bool = False
    is_unique: bool = False


class ForeignKeyMetadata(BaseModel):
    """Foreign-key relationship from one table to another."""

    model_config = ConfigDict(frozen=True)

    name: str
    constrained_columns: list[str]
    referred_schema: str
    referred_table: str
    referred_columns: list[str]
    on_update: str | None = None
    on_delete: str | None = None


class IndexMetadata(BaseModel):
    """Index definition for a table."""

    model_config = ConfigDict(frozen=True)

    name: str
    columns: list[str]
    is_unique: bool
    is_primary: bool = False
    index_type: str | None = None
    definition: str | None = None


class ConstraintMetadata(BaseModel):
    """Table constraint (PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK, etc.)."""

    model_config = ConfigDict(frozen=True)

    name: str
    constraint_type: str
    columns: list[str] = Field(default_factory=list)
    definition: str | None = None


class TableMetadata(BaseModel):
    """Complete metadata for a single table."""

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        ser_json_by_alias=True,
    )

    name: str
    schema_name: str = Field(
        validation_alias=AliasChoices("schema_name", "schema"),
        serialization_alias="schema",
    )
    column_count: int
    columns: list[ColumnMetadata]
    primary_key: list[str]
    foreign_keys: list[ForeignKeyMetadata]
    indexes: list[IndexMetadata]
    constraints: list[ConstraintMetadata]
    estimated_row_count: int | None = None
    estimated_size_bytes: int | None = None


class SchemaMetadata(BaseModel):
    """Metadata for a single database schema namespace."""

    model_config = ConfigDict(frozen=True)

    name: str
    tables: list[TableMetadata]
    table_count: int


class DatabaseMetadata(BaseModel):
    """Top-level structured snapshot of a PostgreSQL-compatible database."""

    model_config = ConfigDict(frozen=True)

    database_name: str
    server_version: str | None = None
    schemas: list[SchemaMetadata]
    schema_count: int
    table_count: int
    estimated_size_bytes: int | None = None
    inspected_at: datetime
