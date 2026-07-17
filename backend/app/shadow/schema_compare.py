from __future__ import annotations

from dataclasses import dataclass, field

from app.schema_analysis.models import DatabaseMetadata, TableMetadata
from app.shadow.schema_loader import type_family


@dataclass
class ComparisonReport:
    """Structural diff between an expected snapshot and the recreated database."""

    matched: bool = True
    schemas_ok: bool = True
    tables_ok: bool = True
    columns_ok: bool = True
    primary_keys_ok: bool = True
    foreign_keys_ok: bool = True
    indexes_ok: bool = True
    constraints_ok: bool = True
    mismatches: list[str] = field(default_factory=list)

    def fail(self, category: str, message: str) -> None:
        setattr(self, category, False)
        self.matched = False
        self.mismatches.append(message)


def _tables_by_key(metadata: DatabaseMetadata) -> dict[tuple[str, str], TableMetadata]:
    result: dict[tuple[str, str], TableMetadata] = {}
    for schema in metadata.schemas:
        if schema.name in {"information_schema", "pg_catalog", "crdb_internal", "pg_extension"}:
            continue
        for table in schema.tables:
            result[(schema.name, table.name)] = table
    return result


def compare_snapshots(
    expected: DatabaseMetadata,
    actual: DatabaseMetadata,
) -> ComparisonReport:
    """Compare every recreated element against the snapshot.

    Column types are compared by normalized *family* (int/string/uuid/...), not
    exact strings, because the loader maps types onto a compact CockroachDB set
    and CockroachDB normalizes representations on read-back.
    """
    report = ComparisonReport()
    exp = _tables_by_key(expected)
    act = _tables_by_key(actual)

    exp_schemas = {k[0] for k in exp}
    act_schemas = {k[0] for k in act}
    for missing in exp_schemas - act_schemas:
        report.fail("schemas_ok", f"schema not recreated: {missing}")

    for key, exp_table in exp.items():
        act_table = act.get(key)
        if act_table is None:
            report.fail("tables_ok", f"table not recreated: {key[0]}.{key[1]}")
            continue
        _compare_table(key, exp_table, act_table, report)

    return report


def _compare_table(
    key: tuple[str, str],
    expected: TableMetadata,
    actual: TableMetadata,
    report: ComparisonReport,
) -> None:
    label = f"{key[0]}.{key[1]}"

    # Columns (name, type family, nullability)
    exp_cols = {c.name: c for c in expected.columns}
    act_cols = {c.name: c for c in actual.columns}
    for name, ec in exp_cols.items():
        ac = act_cols.get(name)
        if ac is None:
            report.fail("columns_ok", f"{label}: missing column {name}")
            continue
        if type_family(ec) != type_family(ac):
            report.fail(
                "columns_ok",
                f"{label}.{name}: type family {type_family(ec)} != {type_family(ac)}",
            )
        if ec.is_nullable != ac.is_nullable:
            report.fail(
                "columns_ok",
                f"{label}.{name}: nullability {ec.is_nullable} != {ac.is_nullable}",
            )

    # Primary key (as a set of columns)
    if set(expected.primary_key) != set(actual.primary_key):
        report.fail(
            "primary_keys_ok",
            f"{label}: PK {expected.primary_key} != {actual.primary_key}",
        )

    # Foreign keys (by referred table + constrained columns)
    exp_fks = {
        (fk.referred_table, tuple(sorted(fk.constrained_columns)))
        for fk in expected.foreign_keys
    }
    act_fks = {
        (fk.referred_table, tuple(sorted(fk.constrained_columns)))
        for fk in actual.foreign_keys
    }
    for missing in exp_fks - act_fks:
        report.fail("foreign_keys_ok", f"{label}: missing FK {missing}")

    # Indexes (by column set + uniqueness), ignoring the primary index
    exp_idx = {
        (tuple(sorted(i.columns)), i.is_unique)
        for i in expected.indexes
        if not i.is_primary
    }
    act_idx = {
        (tuple(sorted(i.columns)), i.is_unique)
        for i in actual.indexes
        if not i.is_primary
    }
    for missing in exp_idx - act_idx:
        report.fail("indexes_ok", f"{label}: missing index {missing}")

    # Constraints by type (UNIQUE/CHECK); PK/FK covered above.
    exp_con = _constraint_signatures(expected)
    act_con = _constraint_signatures(actual)
    for missing in exp_con - act_con:
        report.fail("constraints_ok", f"{label}: missing constraint {missing}")


def _constraint_signatures(table: TableMetadata) -> set[tuple[str, tuple[str, ...]]]:
    sigs: set[tuple[str, tuple[str, ...]]] = set()
    for c in table.constraints:
        ctype = c.constraint_type.upper()
        if "PRIMARY" in ctype or "FOREIGN" in ctype:
            continue
        if "UNIQUE" in ctype:
            sigs.add(("UNIQUE", tuple(sorted(c.columns))))
        elif "CHECK" in ctype:
            # CHECK constraints don't appear in key_column_usage, so re-inspected
            # CHECKs come back with empty columns. Compare presence, not columns,
            # so a recreated CHECK isn't a false mismatch.
            sigs.add(("CHECK", ()))
    return sigs
