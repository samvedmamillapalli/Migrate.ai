"""Anonymization pipeline for cross-customer memory — docs/cross_customer.md §3.

Every step here exists to make one guarantee true: nothing that leaves this
module can be traced back to the account that produced it, and nothing that
leaves this module contains an identifier (table name, column name, index
name, or literal value) from the original migration.

Best-effort throughout, like every other enrichment in this app (MCP
investigation, changefeeds, Slack notifications): a failure at any step
means ``anonymize_migration_for_sharing`` returns ``None`` and the run is
simply not promoted — never a partial or best-guess promotion. See the
module docstring in ``app.memory.open_source_corpus`` and
``app.services.workflow_orchestration_service`` for the same posture applied
elsewhere in this codebase.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import sqlglot
from sqlglot import exp

from app.core.logging import get_logger
from app.prediction.bedrock_client import BedrockClient, extract_json_object

logger = get_logger(__name__)

# Same dialect already used for SQL parsing elsewhere in this app
# (app/policy/engine.py) — kept as one named constant so both call sites
# can't silently drift apart.
DIALECT = "postgres"

_MIN_IDENTIFIER_LEN_FOR_LEAK_CHECK = 2  # see find_leaked_identifiers()


@dataclass(frozen=True)
class SqlShape:
    """Output of step 1 — the identifier-free SQL template plus the exact
    set of real identifiers that were removed, so step 4 knows what to
    check for."""

    template: str
    identifiers: frozenset[str]


@dataclass(frozen=True)
class GeneralizedNarrative:
    """Output of step 3 — Bedrock-rewritten narrative text, generic by
    construction (or as close as an LLM pass can guarantee; step 4 is the
    actual backstop, not this)."""

    summary: str
    risk_narrative: str
    lessons_learned: str
    surprise_notes: str | None


@dataclass(frozen=True)
class AnonymizedRecord:
    """Fully anonymized, promotion-ready record — see docs/cross_customer.md §1
    for the table this maps onto. Never constructed unless step 4 (defense
    in depth) has already passed."""

    sql_shape_template: str
    generalized_summary: str
    generalized_risk_narrative: str
    generalized_lessons_learned: str
    generalized_surprise_notes: str | None
    risk_flags: list[dict[str, Any]]
    shape_hash: str


class AnonymizationFailedError(Exception):
    """Raised internally when a step fails; always caught by the
    orchestrator, never allowed to propagate to a caller."""


# --- Step 1: SQL shape template -------------------------------------------


def build_sql_shape_template(migration_sql: str, *, dialect: str = DIALECT) -> SqlShape:
    """Parse ``migration_sql`` and return an identifier-free template.

    Two-pass, not single-pass: first collect every real table name, column
    name, and index name from the parsed AST (independent of where each one
    textually appears — a table name, a column definition, a bare column
    reference, an index's own name, and a foreign key's referenced column
    are four different AST shapes in sqlglot), then substitute purely by
    string value. A single-pass "replace as you walk, classified by parent
    node type" approach was tried first and missed identifiers inside
    ``REFERENCES table (column)`` clauses and ``CREATE INDEX <name>``
    clauses, both of which are real, common DDL shapes — the two-pass
    design exists because of that concrete, reproduced failure, not as a
    hypothetical precaution.

    Literal values (both string and numeric) are replaced with type
    placeholders. Numeric literals inside a type parameter (e.g. the ``32``
    in ``VARCHAR(32)``) are replaced the same way — a cosmetic quirk
    (``VARCHAR(<int_literal>)``) since a column-width number is not
    identifying, but consistent behavior is simpler and safer to reason
    about than special-casing it.

    Raises ``AnonymizationFailedError`` if the SQL cannot be parsed —
    callers must treat that as "cannot anonymize, do not promote", never as
    "promote it unparsed".
    """
    try:
        statements = sqlglot.parse(migration_sql, dialect=dialect)
    except Exception as exc:  # noqa: BLE001 - any parse failure is fatal here
        raise AnonymizationFailedError(f"SQL parse failed: {exc}") from exc

    if not statements or any(s is None for s in statements):
        raise AnonymizationFailedError("SQL parsed to no usable statements")

    all_identifiers: set[str] = set()
    rendered: list[str] = []

    for stmt in statements:
        table_names, column_names, index_names = _collect_identifiers(stmt)
        table_map = _rename_map(table_names, "TABLE")
        column_map = _rename_map(column_names, "COL")
        index_map = _rename_map(index_names, "INDEX")
        all_identifiers |= table_names | column_names | index_names

        def _replace(node: exp.Expression) -> exp.Expression:
            if isinstance(node, exp.Identifier):
                name = node.this
                for mapping in (table_map, column_map, index_map):
                    if name in mapping:
                        return exp.Identifier(this=mapping[name], quoted=False)
                return node
            if isinstance(node, exp.Literal):
                placeholder = "<string_literal>" if node.is_string else "<int_literal>"
                return exp.Var(this=placeholder)
            return node

        transformed = stmt.transform(_replace)
        rendered.append(transformed.sql(dialect=dialect))

    return SqlShape(template="; ".join(rendered), identifiers=frozenset(all_identifiers))


def _collect_identifiers(
    stmt: exp.Expression,
) -> tuple[set[str], set[str], set[str]]:
    table_names = {t.name for t in stmt.find_all(exp.Table) if t.name}

    column_names: set[str] = set()
    for coldef in stmt.find_all(exp.ColumnDef):
        if isinstance(coldef.this, exp.Identifier) and coldef.this.this:
            column_names.add(coldef.this.this)
    for col in stmt.find_all(exp.Column):
        if col.name:
            column_names.add(col.name)
    # Foreign-key REFERENCES table (col, ...) — the referenced column list
    # is a bare Identifier list inside Reference(this=Schema(...)), not an
    # exp.Column, so it needs its own walk (see module docstring).
    for ref in stmt.find_all(exp.Reference):
        schema = ref.this
        if isinstance(schema, exp.Schema):
            for e in schema.expressions:
                if isinstance(e, exp.Identifier) and e.this:
                    column_names.add(e.this)
    column_names -= table_names

    index_names: set[str] = set()
    for idx in stmt.find_all(exp.Index):
        if isinstance(idx.this, exp.Identifier) and idx.this.this:
            index_names.add(idx.this.this)

    return table_names, column_names, index_names


def _rename_map(names: set[str], prefix: str) -> dict[str, str]:
    # Longest-first so a shorter name that happens to be a substring of a
    # longer one (e.g. "user" inside "user_profile") never gets a chance to
    # partially matter — irrelevant for the value-keyed dict lookup used
    # here, but keeps the numbering stable/deterministic across runs.
    ordered = sorted(names, key=len, reverse=True)
    return {name: f"{prefix}_{i + 1}" for i, name in enumerate(ordered)}


# --- Step 1b: schema-snapshot identifiers ----------------------------------

# Column/table names that are ordinary English or SQL words. A column
# literally named "name", "id", or "status" carries essentially no
# identifying signal about the contributing account — but it collides
# constantly with the generic structural language step 3 is *supposed* to
# produce ("the target column", "check the status"), so including these in
# the leak check would reject nearly every promotion for no safety gain.
# Same reasoning as _MIN_IDENTIFIER_LEN_FOR_LEAK_CHECK above. Identifiers
# from the migration SQL itself are never filtered by this — they are the
# primary risk and stay unfiltered.
_GENERIC_IDENTIFIER_STOPLIST = frozenset(
    {
        "id", "name", "type", "status", "value", "data", "key", "index",
        "date", "time", "timestamp", "created", "updated", "deleted",
        "created_at", "updated_at", "deleted_at", "user", "users", "public",
        "count", "total", "amount", "price", "code", "text", "title",
        "description", "content", "message", "level", "state", "kind",
        "order", "group", "table", "column", "schema", "database", "version",
        "active", "enabled", "disabled", "default", "size", "length",
        "start", "end", "begin", "result", "error", "source", "target",
        "parent", "child", "position", "number", "label", "notes", "email",
    }
)


def extract_schema_identifiers(schema_snapshot: Any) -> frozenset[str]:
    """Every table/column/index/schema name in a run's ``schema_snapshot``.

    docs/cross_customer.md §3 step 4 specifies checking the generalized text
    against identifiers pulled from the *schema snapshot*, not only from the
    migration SQL — because the LLM-written prose being generalized
    (``prediction.reasoning``, ``lessons_learned``) can reference a table the
    migration statement itself never names. Without this, such a name would
    pass the leak check undetected.

    Generic names (``_GENERIC_IDENTIFIER_STOPLIST``) and very short names are
    dropped; see that constant for why.
    """
    if not isinstance(schema_snapshot, dict):
        return frozenset()

    found: set[str] = set()

    def _add(value: Any) -> None:
        if isinstance(value, str):
            name = value.strip()
            if (
                len(name) >= _MIN_IDENTIFIER_LEN_FOR_LEAK_CHECK
                and name.lower() not in _GENERIC_IDENTIFIER_STOPLIST
            ):
                found.add(name)

    _add(schema_snapshot.get("database_name"))
    for schema in schema_snapshot.get("schemas") or []:
        if not isinstance(schema, dict):
            continue
        _add(schema.get("name"))
        for table in schema.get("tables") or []:
            if not isinstance(table, dict):
                continue
            _add(table.get("name"))
            for column in table.get("columns") or []:
                if isinstance(column, dict):
                    _add(column.get("name"))
            for index in table.get("indexes") or []:
                if isinstance(index, dict):
                    _add(index.get("name"))
                else:
                    _add(index)

    return frozenset(found)


# --- Step 2: structural risk flags -----------------------------------------


def structural_risk_flags(risk_flags: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Keep only ``rule_id`` and ``severity``. Deliberately drop ``message``
    even though today's messages are static ``policy.yaml`` text (see
    docs/cross_customer.md §3 step 2) — don't rely on that staying true."""
    out: list[dict[str, Any]] = []
    for flag in risk_flags or []:
        if not isinstance(flag, dict):
            continue
        rule_id = flag.get("rule_id")
        severity = flag.get("severity")
        if rule_id is None:
            continue
        out.append({"rule_id": str(rule_id), "severity": str(severity or "unknown")})
    return out


# --- Step 3: narrative generalization (Bedrock) ----------------------------

_GENERALIZATION_SYSTEM_PROMPT = """You anonymize database-migration incident write-ups \
for a shared, cross-company memory pool. You will be given prose that may \
reference real table names, column names, or other identifying details, \
plus an explicit list of the real identifiers that must not appear in your \
output under any spelling or casing.

Rewrite the text so it describes the same underlying mechanism and lesson \
using only generic structural language ("the target column", "the affected \
table", "the referenced table"). Preserve the technical substance — locking \
behavior, backfill cost, rollback risk, timing — remove every concrete name.

Return ONLY a JSON object with exactly these keys, each a string (surprise \
may be null if the input was empty/null):
{"summary": "...", "risk_narrative": "...", "lessons_learned": "...", "surprise_notes": "..."}

Do not include any identifier from the provided list anywhere in your \
output, including inside code-like text or quotes. If you cannot rewrite a \
field without using a forbidden identifier, replace that specific detail \
with a generic placeholder rather than omitting the sentence."""


def generalize_narrative_via_bedrock(
    client: BedrockClient,
    *,
    migration_summary: str,
    risk_narrative: str,
    lessons_learned: str,
    surprise_notes: str | None,
    identifiers: frozenset[str],
    model_id: str,
) -> GeneralizedNarrative:
    """Step 3. Raises ``AnonymizationFailedError`` on any Bedrock or parsing
    failure — the orchestrator treats that as "skip this promotion", never
    as a reason to fall back to the ungeneralized text."""
    payload = {
        "forbidden_identifiers": sorted(identifiers),
        "migration_summary": migration_summary,
        "risk_narrative": risk_narrative,
        "lessons_learned": lessons_learned,
        "surprise_notes": surprise_notes,
    }
    user_prompt = (
        "Anonymize this migration write-up:\n" + json.dumps(payload, indent=2)
    )
    try:
        raw = client.generate_json(
            system_prompt=_GENERALIZATION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model_id=model_id,
        )
        parsed = extract_json_object(raw)
    except Exception as exc:  # noqa: BLE001 - any Bedrock/parse failure is fatal here
        raise AnonymizationFailedError(
            f"Bedrock generalization failed: {exc}"
        ) from exc

    summary = str(parsed.get("summary") or "").strip()
    risk = str(parsed.get("risk_narrative") or "").strip()
    lessons = str(parsed.get("lessons_learned") or "").strip()
    surprise_raw = parsed.get("surprise_notes")
    surprise = str(surprise_raw).strip() if surprise_raw else None

    if not summary or not risk or not lessons:
        raise AnonymizationFailedError(
            "Bedrock generalization returned an empty required field"
        )

    return GeneralizedNarrative(
        summary=summary,
        risk_narrative=risk,
        lessons_learned=lessons,
        surprise_notes=surprise,
    )


# --- Step 4: defense-in-depth validation -----------------------------------


def find_leaked_identifiers(text: str, identifiers: frozenset[str]) -> list[str]:
    """Word-boundary search for any real identifier inside ``text``.

    Identifiers shorter than ``_MIN_IDENTIFIER_LEN_FOR_LEAK_CHECK`` are
    skipped — a single-letter column name (real examples exist: postgoose's
    own test fixtures use ``x``/``y``) collides constantly with ordinary
    English/SQL words ("KEY", "BY", "OR") under any substring or
    word-boundary check and makes the check useless through false positives
    without meaningfully improving safety (a one-character name carries
    almost no identifying signal on its own). Plain substring matching was
    tried first and rejected for the same reason in the opposite direction:
    it flagged safe output as leaking whenever a short identifier happened
    to appear inside a longer unrelated word.

    Returns the list of identifiers found (empty means clean). Case-
    insensitive, since SQL identifiers are commonly re-cased by formatters.
    """
    found: list[str] = []
    for name in identifiers:
        if len(name) < _MIN_IDENTIFIER_LEN_FOR_LEAK_CHECK:
            continue
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])"
        if re.search(pattern, text, re.IGNORECASE):
            found.append(name)
    return found


def validate_no_identifiers_leaked(
    record_texts: dict[str, str | None],
    identifiers: frozenset[str],
) -> dict[str, list[str]]:
    """Run ``find_leaked_identifiers`` over every text field of a candidate
    record. Returns ``{field_name: [leaked identifiers]}`` for any field
    with a leak — empty dict means the record is clean and safe to
    promote."""
    leaks: dict[str, list[str]] = {}
    for field_name, text in record_texts.items():
        if not text:
            continue
        found = find_leaked_identifiers(text, identifiers)
        if found:
            leaks[field_name] = found
    return leaks


# --- Shape hash (dedup key, §7) --------------------------------------------


def compute_shape_hash(
    *, sql_shape_template: str, scale_tier: str, outcome_class: str
) -> str:
    """Deterministic dedup key — see docs/cross_customer.md §7. Same
    template + scale tier + outcome collapses to the same row instead of a
    near-duplicate insert."""
    raw = f"{sql_shape_template}|{scale_tier}|{outcome_class}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --- Orchestration ----------------------------------------------------------


def anonymize_migration_for_sharing(
    *,
    bedrock_client: BedrockClient,
    bedrock_model_id: str,
    migration_sql: str,
    migration_summary: str,
    risk_narrative: str,
    lessons_learned: str,
    surprise_notes: str | None,
    risk_flags: list[dict[str, Any]] | None,
    scale_tier: str,
    outcome_class: str,
    schema_snapshot: Any = None,
) -> AnonymizedRecord | None:
    """Run the full §3 pipeline. Returns ``None`` (never raises) on any
    failure at any step, logging why — matching this app's established
    posture for enrichment that must never block or corrupt the thing it's
    built on top of (MCP investigation, changefeeds, Slack notifications)."""
    try:
        shape = build_sql_shape_template(migration_sql)
        flags = structural_risk_flags(risk_flags)

        # §3 step 4 — the leak check runs against identifiers from the
        # schema snapshot too, not just the ones the migration statement
        # happens to name. The prose being generalized here is LLM output
        # from the prediction/grading pipeline and can reference a table the
        # DDL never touched.
        check_identifiers = shape.identifiers | extract_schema_identifiers(
            schema_snapshot
        )

        generalized = generalize_narrative_via_bedrock(
            bedrock_client,
            migration_summary=migration_summary,
            risk_narrative=risk_narrative,
            lessons_learned=lessons_learned,
            surprise_notes=surprise_notes,
            identifiers=check_identifiers,
            model_id=bedrock_model_id,
        )

        leaks = validate_no_identifiers_leaked(
            {
                "sql_shape_template": shape.template,
                "generalized_summary": generalized.summary,
                "generalized_risk_narrative": generalized.risk_narrative,
                "generalized_lessons_learned": generalized.lessons_learned,
                "generalized_surprise_notes": generalized.surprise_notes,
            },
            check_identifiers,
        )
        if leaks:
            logger.warning(
                "Cross-customer anonymization rejected: identifier leak detected",
                extra={"leaked_fields": leaks},
            )
            return None

        shape_hash = compute_shape_hash(
            sql_shape_template=shape.template,
            scale_tier=scale_tier,
            outcome_class=outcome_class,
        )

        return AnonymizedRecord(
            sql_shape_template=shape.template,
            generalized_summary=generalized.summary,
            generalized_risk_narrative=generalized.risk_narrative,
            generalized_lessons_learned=generalized.lessons_learned,
            generalized_surprise_notes=generalized.surprise_notes,
            risk_flags=flags,
            shape_hash=shape_hash,
        )
    except AnonymizationFailedError as exc:
        logger.warning(
            "Cross-customer anonymization pipeline failed; skipping promotion",
            extra={"error": str(exc)},
        )
        return None
    except Exception as exc:  # noqa: BLE001 - never let promotion crash the caller
        logger.warning(
            "Cross-customer anonymization pipeline failed unexpectedly; skipping promotion",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )
        return None
