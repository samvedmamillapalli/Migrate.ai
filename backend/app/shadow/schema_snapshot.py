"""Before/after structural snapshots of the shadow cluster, and their diff.

Storage-byte delta (``crdb_internal.table_span_stats``) already answers "how
much bigger did the database get." This answers the question that actually
matters for a migration review: "what changed shape." Two full introspection
passes around the migrate stage, diffed by table/column/index/constraint with
add/remove/change semantics — never a quality judgment (a migration usually
doesn't "improve" anything, so nothing here is colored as better or worse,
only as changed).

Also captures a small real row sample (see ``capture_shadow_snapshot``'s
``sample_tables``) for the tables the migration actually touches, using the
same open connection as the structural snapshot rather than a second one.
"""

from __future__ import annotations

import asyncio
import decimal
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any, Literal

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.logging import get_logger
from app.schema_analysis.analyzer import SchemaAnalyzer
from app.schema_analysis.connection import SchemaAnalysisConnection
from app.schema_analysis.models import DatabaseMetadata

logger = get_logger(__name__)

_IGNORED_SCHEMAS = frozenset(
    {"information_schema", "pg_catalog", "crdb_internal", "pg_extension"}
)
_SQL_DIALECT = "postgres"
_ROW_SAMPLE_LIMIT_DEFAULT = 20
# A freshly-provisioned shadow cluster can have a brief connection hiccup
# (DNS/proxy/pod warmup) in the seconds right after creation — real cloud
# infra, not a code bug. Mirrors the bounded-retry style already used for the
# Cloud API itself (app.shadow.ccloud_api_provider), scaled down for a local
# SQL connect instead of an HTTP call.
_SNAPSHOT_MAX_RETRIES = 2
_SNAPSHOT_BACKOFF_BASE_SECONDS = 1.0

DiffKind = Literal["added", "removed", "changed", "unchanged"]


@dataclass
class ShadowSnapshot:
    """Structure (+ optional row samples), one connection, one capture point."""

    schema: dict[str, Any] | None
    row_samples: dict[str, Any] | None


def extract_referenced_tables(migration_sql: str) -> list[str]:
    """Every table name referenced anywhere in the migration SQL.

    Mirrors the table-extraction convention already used in
    ``app.policy.engine`` (sqlglot, Postgres dialect, ``find_all(exp.Table)``)
    so this doesn't introduce a second, different parsing convention.
    """
    names: list[str] = []
    seen: set[str] = set()
    try:
        statements = sqlglot.parse(migration_sql, dialect=_SQL_DIALECT)
    except ParseError:
        return names
    for stmt in statements:
        if stmt is None:
            continue
        for table_node in stmt.find_all(exp.Table):
            name = table_node.name
            db = table_node.db
            qualified = f"{db}.{name}" if db else name
            if not qualified:
                continue
            key = qualified.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(qualified)
    return names


async def capture_shadow_schema_snapshot(
    connection_url: str,
    *,
    statement_timeout_ms: int = 30_000,
) -> dict[str, Any] | None:
    """Structure-only snapshot (back-compat wrapper, no row sampling).

    Kept for the local/dev orchestrator path, which only wanted the
    structural snapshot. Prefer ``capture_shadow_snapshot`` for anything that
    also wants row samples.
    """
    result = await capture_shadow_snapshot(
        connection_url, statement_timeout_ms=statement_timeout_ms
    )
    return result.schema if result else None


async def capture_shadow_snapshot(
    connection_url: str,
    *,
    statement_timeout_ms: int = 30_000,
    sample_tables: list[str] | None = None,
    sample_limit: int = _ROW_SAMPLE_LIMIT_DEFAULT,
    match_row_ids: dict[str, list[dict[str, Any]]] | None = None,
) -> ShadowSnapshot | None:
    """Structural snapshot, and optionally a real row sample, in one connection.

    Unlike customer-database discovery, the shadow connection legitimately has
    write access — it has to, to seed and migrate — so this intentionally
    skips the read-only assertion `discover_database_metadata` enforces; that
    check protects the customer's database, not this disposable one.

    ``sample_tables``: table names (as referenced in the migration SQL) to
    also pull up to ``sample_limit`` real rows from, in the *same* connection
    used for the structural pass — never a second connection for this.
    ``match_row_ids``: when set (the "after" capture), re-fetch these exact
    primary-key values instead of an arbitrary fresh LIMIT, so the same
    conceptual rows are comparable before/after.

    Best-effort throughout: returns None only if the connection never opens
    even after retrying (see ``_SNAPSHOT_MAX_RETRIES`` — a fresh shadow
    cluster can have a brief transient connection hiccup in the seconds
    right after creation; retried before giving up rather than failing on
    the first blip). Row-sample failure for an individual table never fails
    the whole snapshot — it's recorded per-table instead (see
    ``_capture_row_samples``).
    """
    attempt = 0
    last_exc: Exception | None = None
    while attempt <= _SNAPSHOT_MAX_RETRIES:
        attempt += 1
        try:
            async with SchemaAnalysisConnection(
                connection_url,
                statement_timeout_ms=statement_timeout_ms,
                force_cockroach=True,
            ) as target:
                async with target.connection() as conn:
                    metadata: DatabaseMetadata = await SchemaAnalyzer().analyze_open_connection(
                        conn, enforce_read_only=False
                    )
                    row_samples: dict[str, Any] | None = None
                    if sample_tables:
                        row_samples = await _capture_row_samples(
                            conn,
                            metadata,
                            sample_tables,
                            limit=sample_limit,
                            match_row_ids=match_row_ids,
                        )
                    dumped = metadata.model_dump(mode="json")
                    await _fill_exact_row_counts(conn, dumped)
            return ShadowSnapshot(schema=dumped, row_samples=row_samples)
        except Exception as exc:  # noqa: BLE001 - best-effort, never blocks migration
            last_exc = exc
            if attempt <= _SNAPSHOT_MAX_RETRIES:
                delay = _SNAPSHOT_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                logger.info(
                    "Shadow snapshot capture attempt failed, retrying",
                    extra={
                        "attempt": attempt,
                        "delay_seconds": delay,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                await asyncio.sleep(delay)
    logger.warning(
        "Shadow snapshot capture failed",
        extra={
            "attempts": attempt,
            "error": f"{type(last_exc).__name__}: {last_exc}" if last_exc else "unknown",
        },
    )
    return None


# --- exact row counts -------------------------------------------------------


async def _fill_exact_row_counts(
    conn: AsyncConnection, snapshot: dict[str, Any]
) -> None:
    """Replace each table's ``estimated_row_count`` with a real ``count(*)``.

    ``SchemaAnalyzer`` sources row counts from ``SHOW TABLES``, which reads
    CockroachDB's table statistics. Statistics lag a bulk insert, so a table
    the seeder just filled reports 0 rows for a while — which would render as
    a confident, wrong "0" in the cluster comparison's ROWS column.

    Counting exactly is affordable *here specifically* and nowhere else: this
    only ever runs against the disposable shadow cluster, whose tables are
    capped at ``TIER_ROW_CAPS`` (1k-50k rows). It is never used on the
    customer's database, where a full scan per table would not be acceptable.

    Best-effort and in-place: a table that fails to count keeps whatever
    estimate it already had rather than failing the snapshot.
    """
    for schema in snapshot.get("schemas") or []:
        schema_name = schema.get("name") or ""
        if schema_name in _IGNORED_SCHEMAS:
            continue
        for table in schema.get("tables") or []:
            table_name = table.get("name")
            if not table_name:
                continue
            exact = await _count_rows(conn, _qualify(schema_name, table_name))
            if exact is not None:
                table["estimated_row_count"] = exact


# --- row sampling -----------------------------------------------------------


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return str(value)


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _qualify(schema_name: str, table_name: str) -> str:
    return f"{_quote_ident(schema_name)}.{_quote_ident(table_name)}"


def _index_tables_for_sampling(
    metadata: DatabaseMetadata,
) -> dict[str, dict[str, Any]]:
    """Lowercase bare-name and schema.table lookup, mirrors app.policy.engine."""
    out: dict[str, dict[str, Any]] = {}
    for schema in metadata.schemas:
        if schema.name in _IGNORED_SCHEMAS:
            continue
        for table in schema.tables:
            dumped = table.model_dump(mode="json")
            out[table.name.lower()] = dumped
            out[f"{schema.name}.{table.name}".lower()] = dumped
    return out


def _lookup_table(
    requested: str, index: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    key = requested.lower()
    if key in index:
        return index[key]
    if "." in key:
        bare = key.rsplit(".", 1)[-1]
        if bare in index:
            return index[bare]
    return None


async def _count_rows(conn: AsyncConnection, qualified_table: str) -> int | None:
    try:
        result = await conn.execute(text(f"SELECT count(*) FROM {qualified_table}"))
        return int(result.scalar_one())
    except Exception:  # noqa: BLE001 - best-effort
        return None


async def _fetch_rows_ordered(
    conn: AsyncConnection,
    qualified_table: str,
    pk_cols: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    sql = f"SELECT * FROM {qualified_table}"
    if pk_cols:
        sql += " ORDER BY " + ", ".join(_quote_ident(c) for c in pk_cols)
    sql += f" LIMIT {int(limit)}"
    result = await conn.execute(text(sql))
    return [
        {k: _json_safe(v) for k, v in dict(row).items()}
        for row in result.mappings().all()
    ]


async def _fetch_rows_by_pk(
    conn: AsyncConnection,
    qualified_table: str,
    pk_cols: list[str],
    before_rows: list[dict[str, Any]],
    limit: int,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """Re-fetch the exact rows identified by `before_rows`' primary key values."""
    if not pk_cols:
        rows = await _fetch_rows_ordered(conn, qualified_table, pk_cols, limit)
        return rows, False, "Table has no primary key on record — showing a fresh sample instead of matching rows."

    values = [
        tuple(r[pk] for pk in pk_cols)
        for r in before_rows[:limit]
        if all(pk in r for pk in pk_cols)
    ]
    if not values:
        rows = await _fetch_rows_ordered(conn, qualified_table, pk_cols, limit)
        return rows, False, "Before sample had no usable primary key values — showing a fresh sample instead of matching rows."

    params: dict[str, Any] = {}
    if len(pk_cols) == 1:
        names = [f"v{i}" for i in range(len(values))]
        for name, tup in zip(names, values):
            params[name] = tup[0]
        where_sql = f"{_quote_ident(pk_cols[0])} IN ({', '.join(f':{n}' for n in names)})"
    else:
        placeholders = []
        for i, tup in enumerate(values):
            names = [f"v{i}_{j}" for j in range(len(tup))]
            for name, v in zip(names, tup):
                params[name] = v
            placeholders.append("(" + ", ".join(f":{n}" for n in names) + ")")
        cols_sql = "(" + ", ".join(_quote_ident(c) for c in pk_cols) + ")"
        where_sql = f"{cols_sql} IN ({', '.join(placeholders)})"

    sql = f"SELECT * FROM {qualified_table} WHERE {where_sql}"
    result = await conn.execute(text(sql), params)
    rows = [
        {k: _json_safe(v) for k, v in dict(row).items()}
        for row in result.mappings().all()
    ]
    note = None
    if len(rows) < len(values):
        note = f"{len(rows)} of {len(values)} before rows still exist after the migration."
    return rows, True, note


async def _capture_row_samples(
    conn: AsyncConnection,
    metadata: DatabaseMetadata,
    table_names: list[str],
    *,
    limit: int,
    match_row_ids: dict[str, list[dict[str, Any]]] | None,
) -> dict[str, Any]:
    """Real column list + up to `limit` real rows per referenced table.

    Never raises — a failure to sample one table is recorded on that table's
    entry (`error`) and the rest continue. This is enrichment, not a required
    step for the migration to be considered successful.
    """
    index = _index_tables_for_sampling(metadata)
    tables: dict[str, Any] = {}
    seen_physical: set[str] = set()
    for requested in table_names:
        table_meta = _lookup_table(requested, index)
        if table_meta is not None:
            physical_key = f"{table_meta.get('schema_name')}.{table_meta.get('name')}".lower()
            if physical_key in seen_physical:
                continue  # same table referenced qualified + unqualified — capture once
            seen_physical.add(physical_key)
        if table_meta is None:
            tables[requested] = {
                "table": requested,
                "columns": [],
                "primary_key": [],
                "rows": [],
                "sampled_count": 0,
                "total_row_count": None,
                "matched_by_pk": False,
                "note": None,
                "error": "Table not found in the shadow cluster's current schema.",
            }
            continue

        qualified_display = f"{table_meta.get('schema_name')}.{table_meta.get('name')}"
        qualified_sql = _qualify(table_meta.get("schema_name", ""), table_meta.get("name", ""))
        pk_cols: list[str] = table_meta.get("primary_key") or []
        before_ids = None
        if match_row_ids:
            before_ids = match_row_ids.get(requested) or match_row_ids.get(
                qualified_display
            )
        try:
            if before_ids:
                rows, matched_by_pk, note = await _fetch_rows_by_pk(
                    conn, qualified_sql, pk_cols, before_ids, limit
                )
            else:
                rows = await _fetch_rows_ordered(conn, qualified_sql, pk_cols, limit)
                matched_by_pk = False
                note = None
            total = await _count_rows(conn, qualified_sql)
            tables[requested] = {
                "table": qualified_display,
                "columns": table_meta.get("columns") or [],
                "primary_key": pk_cols,
                "rows": rows,
                "sampled_count": len(rows),
                "total_row_count": total,
                "matched_by_pk": matched_by_pk,
                "note": note,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 - per-table best-effort
            logger.warning(
                "Row sample capture failed for table",
                extra={"table": qualified_display, "error": f"{type(exc).__name__}: {exc}"},
            )
            tables[requested] = {
                "table": qualified_display,
                "columns": table_meta.get("columns") or [],
                "primary_key": pk_cols,
                "rows": [],
                "sampled_count": 0,
                "total_row_count": None,
                "matched_by_pk": False,
                "note": None,
                "error": f"{type(exc).__name__}: {exc}",
            }

    return {"tables": tables, "captured_at": datetime.now(UTC).isoformat()}


def build_row_ids_for_matching(
    row_sample: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]]] | None:
    """Extract {table: [pk-value dicts]} from a "before" row sample capture,
    ready to pass as `match_row_ids` into the "after" capture."""
    if not row_sample or not row_sample.get("tables"):
        return None
    out: dict[str, list[dict[str, Any]]] = {}
    for table_key, table_data in row_sample["tables"].items():
        pk_cols = table_data.get("primary_key") or []
        rows = table_data.get("rows") or []
        if not pk_cols or not rows:
            continue
        matched = [
            {pk: row.get(pk) for pk in pk_cols}
            for row in rows
            if all(pk in row for pk in pk_cols)
        ]
        if matched:
            out[table_key] = matched
            out[table_data.get("table", table_key)] = matched
    return out or None


# --- schema diff (unchanged from before this task) --------------------------


def _index_tables(metadata: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not metadata:
        return out
    for schema in metadata.get("schemas") or []:
        sname = schema.get("name") or ""
        if sname in _IGNORED_SCHEMAS:
            continue
        for table in schema.get("tables") or []:
            tname = table.get("name") or ""
            out[f"{sname}.{tname}"] = table
    return out


def _column_signature(col: dict[str, Any]) -> tuple[str | None, bool]:
    return (col.get("data_type"), bool(col.get("is_nullable")))


def _diff_columns(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    before_by_name = {c.get("name"): c for c in before}
    after_by_name = {c.get("name"): c for c in after}
    names = sorted(set(before_by_name) | set(after_by_name))
    diffs: list[dict[str, Any]] = []
    for name in names:
        b = before_by_name.get(name)
        a = after_by_name.get(name)
        if b is None:
            diffs.append({"name": name, "kind": "added", "type": a.get("data_type")})
        elif a is None:
            diffs.append({"name": name, "kind": "removed", "type": b.get("data_type")})
        elif _column_signature(b) != _column_signature(a):
            diffs.append(
                {
                    "name": name,
                    "kind": "changed",
                    "before_type": b.get("data_type"),
                    "after_type": a.get("data_type"),
                    "before_nullable": b.get("is_nullable"),
                    "after_nullable": a.get("is_nullable"),
                }
            )
        else:
            diffs.append({"name": name, "kind": "unchanged", "type": a.get("data_type")})
    return diffs


def _diff_named_set(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> tuple[list[str], list[str]]:
    """Added/removed names for indexes or constraints (by name)."""
    before_names = {i.get("name") for i in before if i.get("name")}
    after_names = {i.get("name") for i in after if i.get("name")}
    added = sorted(after_names - before_names)
    removed = sorted(before_names - after_names)
    return added, removed


def _diff_table(
    key: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, Any]:
    if before is None:
        assert after is not None
        return {
            "name": key,
            "kind": "added",
            "columns": [
                {"name": c.get("name"), "kind": "added", "type": c.get("data_type")}
                for c in after.get("columns") or []
            ],
            "indexes_added": [i.get("name") for i in after.get("indexes") or []],
            "indexes_removed": [],
            "constraints_added": [i.get("name") for i in after.get("constraints") or []],
            "constraints_removed": [],
        }
    if after is None:
        return {
            "name": key,
            "kind": "removed",
            "columns": [
                {"name": c.get("name"), "kind": "removed", "type": c.get("data_type")}
                for c in before.get("columns") or []
            ],
            "indexes_added": [],
            "indexes_removed": [i.get("name") for i in before.get("indexes") or []],
            "constraints_added": [],
            "constraints_removed": [i.get("name") for i in before.get("constraints") or []],
        }

    columns = _diff_columns(before.get("columns") or [], after.get("columns") or [])
    indexes_added, indexes_removed = _diff_named_set(
        before.get("indexes") or [], after.get("indexes") or []
    )
    constraints_added, constraints_removed = _diff_named_set(
        before.get("constraints") or [], after.get("constraints") or []
    )
    changed = (
        any(c["kind"] != "unchanged" for c in columns)
        or indexes_added
        or indexes_removed
        or constraints_added
        or constraints_removed
    )
    return {
        "name": key,
        "kind": "changed" if changed else "unchanged",
        "columns": columns,
        "indexes_added": indexes_added,
        "indexes_removed": indexes_removed,
        "constraints_added": constraints_added,
        "constraints_removed": constraints_removed,
    }


def build_schema_diff(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Structural before/after diff, or None if neither snapshot is available.

    Color semantics belong to the frontend (green=added, red=removed,
    amber=changed, grey=unchanged) — this only classifies, it never judges
    quality, since a migration usually doesn't "improve" anything.
    """
    if before is None and after is None:
        return None
    before_tables = _index_tables(before)
    after_tables = _index_tables(after)
    keys = sorted(set(before_tables) | set(after_tables))
    tables = [
        _diff_table(key, before_tables.get(key), after_tables.get(key))
        for key in keys
    ]
    return {"tables": tables}
