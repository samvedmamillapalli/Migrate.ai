"""Deterministic risk and policy analysis using sqlglot (Postgres dialect).

Runs before any model call. Authoritative over the model for whether execution
may proceed automatically. Framing: blast radius means backfill duration,
storage growth, resource saturation, and rollback safety — never lock duration.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.core.logging import get_logger
from app.policy.config import get_policy_file
from app.policy.models import (
    CompatibilityRiskValue,
    FindingSeverity,
    PolicyAnalysisResult,
    PolicyDecisionValue,
    PolicyFile,
    RiskFinding,
    RuleConfig,
    escalate_severity,
    max_compatibility,
    max_decision,
)
from app.schema_analysis.models import DatabaseMetadata

logger = get_logger(__name__)

DIALECT = "postgres"


def _table_name(node: exp.Expression | None) -> str | None:
    if node is None:
        return None
    table = node if isinstance(node, exp.Table) else node.find(exp.Table)
    if table is None:
        return None
    name = table.name
    db = table.db
    if db:
        return f"{db}.{name}"
    return name or None


def _ident_name(node: exp.Expression | None) -> str | None:
    if node is None:
        return None
    if isinstance(node, exp.Identifier):
        return node.name
    if isinstance(node, exp.Column):
        return node.name
    if isinstance(node, exp.Table):
        return node.name
    return getattr(node, "name", None) or str(node)


def _build_row_index(snapshot: DatabaseMetadata | None) -> dict[str, int | None]:
    """Map lowercased table name (and schema.table) → estimated_row_count."""
    index: dict[str, int | None] = {}
    if snapshot is None:
        return index
    for schema in snapshot.schemas:
        for table in schema.tables:
            rows = table.estimated_row_count
            index[table.name.lower()] = rows
            index[f"{schema.name}.{table.name}".lower()] = rows
            index[f"{table.schema_name}.{table.name}".lower()] = rows
    return index


def _lookup_rows(
    table: str | None,
    row_index: dict[str, int | None],
) -> tuple[int | None, bool]:
    if not table:
        return None, False
    key = table.lower()
    if key in row_index:
        return row_index[key], True
    # bare name fallback already covered; try last segment
    if "." in key:
        bare = key.rsplit(".", 1)[-1]
        if bare in row_index:
            return row_index[bare], True
    return None, False


class PolicyEngine:
    """Parse migration SQL and produce structured policy analysis."""

    def __init__(self, policy: PolicyFile | None = None) -> None:
        self._policy = policy or get_policy_file()

    def analyze(
        self,
        migration_sql: str,
        snapshot: DatabaseMetadata | None = None,
    ) -> PolicyAnalysisResult:
        row_index = _build_row_index(snapshot)
        findings: list[RiskFinding] = []
        statement_types: list[str] = []
        parse_failed = False

        try:
            statements = sqlglot.parse(migration_sql, dialect=DIALECT)
        except ParseError as exc:
            logger.warning(
                "Migration SQL parse failed",
                extra={"error": str(exc)},
            )
            parse_failed = True
            findings.append(self._finding_from_rule("parse_failure", objects=[]))
            return self._aggregate(
                findings=findings,
                statement_types=["parse_failure"],
                parse_failed=True,
            )

        if not statements or all(st is None for st in statements):
            parse_failed = True
            findings.append(self._finding_from_rule("parse_failure", objects=[]))
            return self._aggregate(
                findings=findings,
                statement_types=["parse_failure"],
                parse_failed=True,
            )

        for stmt in statements:
            if stmt is None:
                parse_failed = True
                findings.append(
                    self._finding_from_rule("parse_failure", objects=[]),
                )
                statement_types.append("parse_failure")
                continue

            statement_types.append(type(stmt).__name__)
            findings.extend(self._analyze_statement(stmt, row_index))

        # CRDB-specific primary key rewrite that sqlglot may mangle
        if self._looks_like_crdb_primary_key_change(migration_sql, findings):
            # Prefer table names already seen; else mark unknown
            tables = self._extract_alter_table_names(migration_sql)
            if not any(f.rule_id == "primary_key_change" for f in findings):
                for table in tables or ["(unknown)"]:
                    findings.append(
                        self._finding_from_rule(
                            "primary_key_change",
                            objects=[table],
                            row_index=row_index,
                            table=table if table != "(unknown)" else None,
                        )
                    )

        return self._aggregate(
            findings=findings,
            statement_types=statement_types,
            parse_failed=parse_failed,
        )

    def _analyze_statement(
        self,
        stmt: exp.Expression,
        row_index: dict[str, int | None],
    ) -> list[RiskFinding]:
        findings: list[RiskFinding] = []

        # DROP TABLE
        if isinstance(stmt, exp.Drop) and (stmt.args.get("kind") or "").upper() == "TABLE":
            table = _table_name(stmt.this) or _ident_name(stmt.this)
            findings.append(
                self._finding_from_rule(
                    "drop_table",
                    objects=[table] if table else [],
                    row_index=row_index,
                    table=table,
                )
            )
            return findings

        # CREATE INDEX
        if isinstance(stmt, exp.Create) and isinstance(stmt.this, exp.Index):
            index_node: exp.Index = stmt.this
            table = _table_name(index_node.args.get("table")) or _ident_name(
                index_node.args.get("table")
            )
            findings.append(
                self._finding_from_rule(
                    "index_creation",
                    objects=[table] if table else [],
                    row_index=row_index,
                    table=table,
                    escalate=True,
                )
            )
            return findings

        # ALTER TABLE actions
        if isinstance(stmt, exp.Alter) and (stmt.args.get("kind") or "").upper() == "TABLE":
            table = _table_name(stmt.this) or _ident_name(stmt.this)
            actions = stmt.args.get("actions") or []
            for action in actions:
                findings.extend(
                    self._analyze_alter_action(action, table, row_index)
                )

        return findings

    def _analyze_alter_action(
        self,
        action: exp.Expression,
        table: str | None,
        row_index: dict[str, int | None],
    ) -> list[RiskFinding]:
        findings: list[RiskFinding] = []
        objects = [table] if table else []

        # DROP COLUMN
        if isinstance(action, exp.Drop) and (action.args.get("kind") or "").upper() == "COLUMN":
            col = _ident_name(action.this)
            objs = objects + ([col] if col else [])
            findings.append(
                self._finding_from_rule(
                    "drop_column",
                    objects=objs,
                    row_index=row_index,
                    table=table,
                )
            )
            return findings

        # DROP CONSTRAINT that looks like a primary key
        if isinstance(action, exp.Drop) and (action.args.get("kind") or "").upper() == "CONSTRAINT":
            cname = (_ident_name(action.this) or "").lower()
            if "pkey" in cname or "primary" in cname:
                findings.append(
                    self._finding_from_rule(
                        "primary_key_change",
                        objects=objects + ([cname] if cname else []),
                        row_index=row_index,
                        table=table,
                        escalate=True,
                    )
                )
            return findings

        # ADD CONSTRAINT / FK / PK
        if isinstance(action, exp.AddConstraint):
            if list(action.find_all(exp.ForeignKey)):
                findings.append(
                    self._finding_from_rule(
                        "foreign_key_add",
                        objects=objects,
                        row_index=row_index,
                        table=table,
                        escalate=True,
                    )
                )
            if list(action.find_all(exp.PrimaryKey)):
                findings.append(
                    self._finding_from_rule(
                        "primary_key_change",
                        objects=objects,
                        row_index=row_index,
                        table=table,
                        escalate=True,
                    )
                )
            # CHECK / UNIQUE tightening → backward incompatible
            check_cls = getattr(exp, "CheckColumnConstraint", None)
            unique_cls = getattr(exp, "UniqueColumnConstraint", None)
            for constraint in action.find_all(exp.Constraint):
                inner = constraint.args.get("expressions") or []
                for node in inner:
                    is_check = check_cls is not None and isinstance(node, check_cls)
                    is_unique = unique_cls is not None and isinstance(node, unique_cls)
                    if is_check or is_unique:
                        findings.append(
                            self._finding_from_rule(
                                "backward_incompatible",
                                objects=objects,
                                row_index=row_index,
                                table=table,
                            )
                        )
            # Also bare PrimaryKey without Constraint wrapper already handled
            return findings

        # ALTER COLUMN: type change, SET NOT NULL, or mangled PRIMARY KEY
        if isinstance(action, exp.AlterColumn):
            col_name = (_ident_name(action.this) or "").strip()
            if col_name.upper() == "PRIMARY KEY" or "PRIMARY KEY" in col_name.upper():
                findings.append(
                    self._finding_from_rule(
                        "primary_key_change",
                        objects=objects,
                        row_index=row_index,
                        table=table,
                        escalate=True,
                    )
                )
                return findings

            if action.args.get("dtype") is not None:
                objs = objects + ([col_name] if col_name else [])
                findings.append(
                    self._finding_from_rule(
                        "table_rewrite",
                        objects=objs,
                        row_index=row_index,
                        table=table,
                        escalate=True,
                    )
                )

            if action.args.get("allow_null") is False:
                objs = objects + ([col_name] if col_name else [])
                findings.append(
                    self._finding_from_rule(
                        "backward_incompatible",
                        objects=objs,
                        row_index=row_index,
                        table=table,
                    )
                )
            return findings

        # ADD COLUMN with NOT NULL and/or DEFAULT → backfill candidate
        if isinstance(action, exp.ColumnDef):
            col = _ident_name(action.this)
            objs = objects + ([col] if col else [])
            constraints = action.args.get("constraints") or []
            has_not_null = False
            has_default = False
            for c in constraints:
                kind = c.args.get("kind") if isinstance(c, exp.ColumnConstraint) else c
                if isinstance(kind, exp.NotNullColumnConstraint):
                    has_not_null = True
                if isinstance(kind, exp.DefaultColumnConstraint):
                    has_default = True
                # also inspect nested
                if list(c.find_all(exp.NotNullColumnConstraint)):
                    has_not_null = True
                if list(c.find_all(exp.DefaultColumnConstraint)):
                    has_default = True

            if has_not_null and has_default:
                findings.append(
                    self._finding_from_rule(
                        "long_running_backfill",
                        objects=objs,
                        row_index=row_index,
                        table=table,
                        escalate=True,
                    )
                )
                findings.append(
                    self._finding_from_rule(
                        "backward_incompatible",
                        objects=objs,
                        row_index=row_index,
                        table=table,
                    )
                )
            elif has_not_null:
                findings.append(
                    self._finding_from_rule(
                        "backward_incompatible",
                        objects=objs,
                        row_index=row_index,
                        table=table,
                    )
                )
            elif has_default:
                findings.append(
                    self._finding_from_rule(
                        "long_running_backfill",
                        objects=objs,
                        row_index=row_index,
                        table=table,
                        escalate=True,
                    )
                )
            return findings

        # RENAME TABLE / COLUMN
        if isinstance(action, exp.AlterRename) or type(action).__name__ == "AlterRename":
            findings.append(
                self._finding_from_rule(
                    "backward_incompatible",
                    objects=objects,
                    row_index=row_index,
                    table=table,
                )
            )
            return findings

        if isinstance(action, exp.RenameColumn):
            old = _ident_name(action.this)
            new = _ident_name(action.args.get("to"))
            objs = objects + [x for x in (old, new) if x]
            findings.append(
                self._finding_from_rule(
                    "backward_incompatible",
                    objects=objs,
                    row_index=row_index,
                    table=table,
                )
            )
            return findings

        return findings

    def _finding_from_rule(
        self,
        rule_id: str,
        *,
        objects: list[str],
        row_index: dict[str, int | None] | None = None,
        table: str | None = None,
        escalate: bool = False,
    ) -> RiskFinding:
        rule = self._require_rule(rule_id)
        severity = rule.base_severity
        row_count: int | None = None
        row_count_known = True
        explanation = rule.explanation.strip()

        if escalate or rule.escalate_by_row_count:
            row_count, found = _lookup_rows(table, row_index or {})
            row_count_known = found
            if not found:
                explanation = (
                    f"{explanation} Row count for "
                    f"{table or 'referenced table'} is unknown in the schema "
                    f"snapshot (table missing or discovery fell back); severity "
                    f"was not escalated from table size."
                )
                row_count_known = False
            else:
                severity = escalate_severity(
                    rule.base_severity,
                    row_count,
                    self._policy.defaults.row_count_thresholds,
                )
                if row_count is not None:
                    explanation = (
                        f"{explanation} Estimated row count for "
                        f"{table}: {row_count:,}."
                    )

        return RiskFinding(
            rule_id=rule_id,
            title=rule.title,
            severity=severity,
            objects=objects,
            explanation=explanation,
            policy_decision=rule.policy_decision,
            row_count=row_count,
            row_count_known=row_count_known,
        )

    def _require_rule(self, rule_id: str) -> RuleConfig:
        rule = self._policy.rules.get(rule_id)
        if rule is None:
            raise ValueError(f"Policy rule not defined: {rule_id}")
        if not rule.enabled:
            # Return a no-op style rule that still allows construction; callers
            # should skip disabled rules. For parse_failure we always emit.
            return rule
        return rule

    def _aggregate(
        self,
        *,
        findings: list[RiskFinding],
        statement_types: list[str],
        parse_failed: bool,
    ) -> PolicyAnalysisResult:
        # Drop findings whose rules are disabled (except parse_failure always kept)
        active: list[RiskFinding] = []
        for finding in findings:
            rule = self._policy.rules.get(finding.rule_id)
            if rule is not None and not rule.enabled and finding.rule_id != "parse_failure":
                continue
            active.append(finding)

        if not active:
            return PolicyAnalysisResult(
                risk_flags=[],
                compatibility_risk=CompatibilityRiskValue.LOW,
                requires_expand_contract=False,
                requires_manual_review=parse_failed,
                policy_decision=PolicyDecisionValue.ALLOW,
                parsed_statement_types=statement_types,
                parse_failed=parse_failed,
            )

        decision = max_decision(*(f.policy_decision for f in active))
        compat = CompatibilityRiskValue.LOW
        requires_expand = False
        requires_review = parse_failed

        for finding in active:
            rule = self._policy.rules.get(finding.rule_id)
            if rule is None:
                continue
            compat = max_compatibility(compat, rule.compatibility_risk)
            if rule.requires_expand_contract:
                requires_expand = True
            if rule.requires_manual_review or finding.severity == FindingSeverity.HIGH:
                requires_review = True

        if any(f.severity == FindingSeverity.HIGH for f in active):
            requires_review = True

        return PolicyAnalysisResult(
            risk_flags=active,
            compatibility_risk=compat,
            requires_expand_contract=requires_expand,
            requires_manual_review=requires_review,
            policy_decision=decision,
            parsed_statement_types=statement_types,
            parse_failed=parse_failed,
        )

    @staticmethod
    def _looks_like_crdb_primary_key_change(
        sql: str,
        findings: list[RiskFinding],
    ) -> bool:
        if any(f.rule_id == "primary_key_change" for f in findings):
            return False
        normalized = " ".join(sql.upper().split())
        return "ALTER PRIMARY KEY" in normalized or "USING COLUMNS" in normalized

    @staticmethod
    def _extract_alter_table_names(sql: str) -> list[str]:
        names: list[str] = []
        try:
            for stmt in sqlglot.parse(sql, dialect=DIALECT):
                if isinstance(stmt, exp.Alter):
                    name = _table_name(stmt.this) or _ident_name(stmt.this)
                    if name:
                        names.append(name)
        except ParseError:
            return names
        return names


def analyze_migration(
    migration_sql: str,
    snapshot: DatabaseMetadata | None = None,
    *,
    policy: PolicyFile | None = None,
) -> PolicyAnalysisResult:
    """Convenience entry point for the deterministic policy layer."""
    return PolicyEngine(policy=policy).analyze(migration_sql, snapshot)
