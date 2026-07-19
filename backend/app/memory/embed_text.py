"""Compose audited embedding text for Titan (reasoning + surprises, not raw DDL)."""

from __future__ import annotations

from typing import Any


def compose_embed_text(
    *,
    migration_summary: str,
    risk_narrative: str,
    lessons_learned: str,
    surprise_notes: str | None,
    migration_sql: str | None = None,
) -> str:
    """Build the exact text that will be embedded and stored verbatim.

    Raw DDL may appear briefly but must not dominate. Ordering is load-bearing
    for retrieval quality: summary → risk → lessons → surprise → optional DDL.
    """
    parts = [
        f"Migration summary: {migration_summary.strip()}",
        f"Risk narrative: {risk_narrative.strip()}",
        f"Lessons learned: {lessons_learned.strip()}",
    ]
    if surprise_notes and surprise_notes.strip():
        parts.append(f"Surprise: {surprise_notes.strip()}")
    if migration_sql and migration_sql.strip():
        # Cap DDL so it cannot become the majority of the text.
        ddl = migration_sql.strip()
        max_ddl = max(120, sum(len(p) for p in parts) // 3)
        if len(ddl) > max_ddl:
            ddl = ddl[:max_ddl] + "…"
        parts.append(f"DDL excerpt: {ddl}")
    return "\n\n".join(parts)


def classify_migration_type(statement_types: list[str] | None, sql: str) -> str:
    """Compact classification for hybrid ranking filters."""
    types = [t.lower() for t in (statement_types or [])]
    sql_l = sql.lower()
    if any("drop" in t for t in types) or "drop " in sql_l:
        if "column" in sql_l:
            return "drop_column"
        if "index" in sql_l:
            return "drop_index"
        if "table" in sql_l:
            return "drop_table"
        return "drop"
    if "create index" in sql_l or "create unique index" in sql_l:
        return "create_index"
    if "alter table" in sql_l and "add column" in sql_l:
        return "add_column"
    if "alter table" in sql_l and "alter column" in sql_l:
        return "alter_column"
    if "create table" in sql_l:
        return "create_table"
    if types:
        return types[0][:64]
    return "unknown"


def summarize_schema(snapshot: dict[str, Any] | None) -> tuple[str, int, int]:
    """Return (schema_summary, index_count, table_complexity)."""
    if not snapshot:
        return ("No schema snapshot available.", 0, 0)

    schemas = snapshot.get("schemas") or []
    table_count = 0
    index_count = 0
    row_total = 0
    names: list[str] = []
    for schema in schemas:
        if not isinstance(schema, dict):
            continue
        for table in schema.get("tables") or []:
            if not isinstance(table, dict):
                continue
            table_count += 1
            name = table.get("name") or table.get("table_name") or "?"
            rows = table.get("estimated_row_count")
            if isinstance(rows, int):
                row_total += rows
            names.append(str(name))
            indexes = table.get("indexes") or []
            if isinstance(indexes, list):
                index_count += len(indexes)
            cols = table.get("columns") or []
            if isinstance(cols, list) and len(cols) > 8:
                # Coarse complexity bump for wide tables.
                pass

    # table_complexity: tables + coarse width signal via index density.
    complexity = table_count + min(index_count, 50)
    name_preview = ", ".join(names[:8])
    if len(names) > 8:
        name_preview += f", …(+{len(names) - 8})"
    summary = (
        f"{table_count} tables, ~{row_total:,} estimated rows, "
        f"{index_count} indexes. Tables: {name_preview or 'none'}."
    )
    return summary, index_count, complexity


def summarize_migration(sql: str, migration_type: str) -> str:
    compact = " ".join(sql.split())
    if len(compact) > 240:
        compact = compact[:240] + "…"
    return f"{migration_type}: {compact}"
