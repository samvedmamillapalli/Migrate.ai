"""Cross-customer anonymization pipeline — docs/cross_customer.md §3.

The test that actually matters in this file is the identifier-leak family:
given a real migration_sql with real identifiers, assert those identifiers
do NOT appear anywhere in the pipeline's output — including when the
(faked) Bedrock generalization step itself leaks one, which must cause the
whole promotion to be rejected, not silently accepted.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.memory.cross_customer_anonymizer import (
    AnonymizationFailedError,
    anonymize_migration_for_sharing,
    build_sql_shape_template,
    compute_shape_hash,
    extract_schema_identifiers,
    find_leaked_identifiers,
    generalize_narrative_via_bedrock,
    structural_risk_flags,
    validate_no_identifiers_leaked,
)
from app.prediction.bedrock_client import BedrockClient


class FakeBedrockClient(BedrockClient):
    """Returns a fixed JSON string, or raises, for testing the
    generalization step without a real Bedrock call."""

    def __init__(self, response_json: str | None = None, *, should_raise: bool = False) -> None:
        self._response_json = response_json
        self._should_raise = should_raise

    def generate_json(
        self, *, system_prompt: str, user_prompt: str, model_id: str | None = None
    ) -> str:
        if self._should_raise:
            raise RuntimeError("simulated Bedrock failure")
        assert self._response_json is not None
        return self._response_json

    async def converse_with_tools(self, **kwargs: Any) -> Any:  # pragma: no cover - unused here
        raise NotImplementedError


# --------------------------------------------------- Step 1: SQL shape template


@pytest.mark.parametrize(
    "sql",
    [
        "ALTER TABLE customers ADD COLUMN discount_pct INT NOT NULL DEFAULT 0;",
        "CREATE UNIQUE INDEX idx_customers_email ON customers (email);",
        "CREATE TABLE order_items (item_id int not null primary key, "
        "order_ref varchar(32) not null references orders (order_ref));",
        "UPDATE zerver_message SET recipient_id = 5 WHERE sender_id = 2 AND recipient_id = 3;",
        "ALTER TABLE dcim_interface ALTER COLUMN speed TYPE bigint;",
        "ALTER TABLE api_city DROP COLUMN nickname;",
    ],
)
def test_sql_shape_template_leaks_no_real_identifier(sql: str) -> None:
    shape = build_sql_shape_template(sql)
    leaked = find_leaked_identifiers(shape.template, shape.identifiers)
    assert leaked == [], f"identifiers leaked into template: {leaked}\ntemplate={shape.template}"
    # And the template must actually have replaced something, not just be
    # a no-op pass-through of the original SQL.
    assert shape.identifiers, "expected at least one real identifier to be found"


def test_sql_shape_template_catches_foreign_key_reference_column() -> None:
    """Regression test for a real bug found while building this: a bare
    Identifier inside REFERENCES table (column) is not an exp.Column node
    in sqlglot's AST and was missed by an earlier, single-pass version of
    this function."""
    shape = build_sql_shape_template(
        "CREATE TABLE order_items (id int primary key, "
        "order_ref varchar(32) references orders (order_ref));"
    )
    leaked = find_leaked_identifiers(shape.template, shape.identifiers)
    assert leaked == [], f"identifiers leaked: {leaked}\ntemplate={shape.template}"
    assert "orders" in shape.identifiers  # sanity: the referenced table was found at all


def test_sql_shape_template_catches_index_name() -> None:
    """Regression test: CREATE INDEX <name> ON ... carries the index's own
    name in a different AST shape (exp.Index.this) than table/column
    identifiers, and a naive walk missed it — index names commonly encode
    the table/column they cover (e.g. idx_customers_email), so this is a
    real leak vector, not a hypothetical one."""
    shape = build_sql_shape_template(
        "CREATE UNIQUE INDEX idx_customers_email ON customers (email);"
    )
    assert "idx_customers_email" not in shape.template


def test_sql_shape_template_raises_on_unparseable_sql() -> None:
    with pytest.raises(AnonymizationFailedError):
        build_sql_shape_template("THIS IS NOT valid !!! SQL SYNTAX (((")


# --------------------------------------------------- Step 2: structural risk flags


def test_structural_risk_flags_drops_message_keeps_rule_id_and_severity() -> None:
    raw = [
        {
            "rule_id": "backward_incompatible",
            "severity": "medium",
            "message": "customers.discount_pct specific narrative text",
        }
    ]
    out = structural_risk_flags(raw)
    assert out == [{"rule_id": "backward_incompatible", "severity": "medium"}]
    assert "message" not in out[0]
    assert "customers" not in str(out)


def test_structural_risk_flags_handles_empty_and_malformed_input() -> None:
    assert structural_risk_flags(None) == []
    assert structural_risk_flags([]) == []
    assert structural_risk_flags([{"not_a_rule_id": "x"}]) == []


# --------------------------------------------------- Step 4: leak detection itself


def test_find_leaked_identifiers_detects_real_leak() -> None:
    text = "The migration altered the customers table's discount_pct column."
    leaked = find_leaked_identifiers(text, frozenset({"customers", "discount_pct"}))
    assert set(leaked) == {"customers", "discount_pct"}


def test_find_leaked_identifiers_case_insensitive() -> None:
    text = "We modified the Customers table."
    assert find_leaked_identifiers(text, frozenset({"customers"})) == ["customers"]


def test_find_leaked_identifiers_no_false_positive_on_short_identifiers() -> None:
    """Real regression: single-letter column names (postgoose's own test
    fixtures use 'x'/'y') collide with ordinary English/SQL words under a
    naive substring check ('y' inside 'PRIMARY KEY'). Word-boundary
    matching plus a minimum-length skip fixes this."""
    text = "CREATE TABLE TABLE_1 (COL_1 INT NOT NULL PRIMARY KEY)"
    assert find_leaked_identifiers(text, frozenset({"x", "y"})) == []


def test_find_leaked_identifiers_no_false_positive_on_substring_collision() -> None:
    text = "The TABLE_1 row count grew."
    # "order" must not be flagged just because it's a substring of nothing
    # here, and a real identifier "orders" must not falsely match "order".
    assert find_leaked_identifiers(text, frozenset({"orders"})) == []


def test_validate_no_identifiers_leaked_reports_field_name() -> None:
    leaks = validate_no_identifiers_leaked(
        {
            "clean_field": "nothing identifying here",
            "leaky_field": "mentions the customers table directly",
        },
        frozenset({"customers"}),
    )
    assert leaks == {"leaky_field": ["customers"]}


# --------------------------------------------------- Step 3: Bedrock generalization


def test_generalize_narrative_success() -> None:
    client = FakeBedrockClient(
        response_json=(
            '{"summary": "A column was widened on a large table.", '
            '"risk_narrative": "Widening an integer column forces a table rewrite.", '
            '"lessons_learned": "Expect a full rewrite for width changes.", '
            '"surprise_notes": null}'
        )
    )
    result = generalize_narrative_via_bedrock(
        client,
        migration_summary="widen customers.legacy_id to bigint",
        risk_narrative="customers.legacy_id overflow risk",
        lessons_learned="watch customers table",
        surprise_notes=None,
        identifiers=frozenset({"customers", "legacy_id"}),
        model_id="fake-model",
    )
    assert result.summary == "A column was widened on a large table."
    assert result.surprise_notes is None


def test_generalize_narrative_raises_on_bedrock_failure() -> None:
    client = FakeBedrockClient(should_raise=True)
    with pytest.raises(AnonymizationFailedError):
        generalize_narrative_via_bedrock(
            client,
            migration_summary="x",
            risk_narrative="y",
            lessons_learned="z",
            surprise_notes=None,
            identifiers=frozenset(),
            model_id="fake-model",
        )


def test_generalize_narrative_raises_on_empty_required_field() -> None:
    client = FakeBedrockClient(
        response_json='{"summary": "", "risk_narrative": "x", "lessons_learned": "y", "surprise_notes": null}'
    )
    with pytest.raises(AnonymizationFailedError):
        generalize_narrative_via_bedrock(
            client,
            migration_summary="x",
            risk_narrative="y",
            lessons_learned="z",
            surprise_notes=None,
            identifiers=frozenset(),
            model_id="fake-model",
        )


# --------------------------------------------------- shape hash (dedup key)


def test_compute_shape_hash_deterministic() -> None:
    h1 = compute_shape_hash(
        sql_shape_template="ALTER TABLE TABLE_1 ADD COLUMN COL_1 INT",
        scale_tier="medium",
        outcome_class="clean_ok",
    )
    h2 = compute_shape_hash(
        sql_shape_template="ALTER TABLE TABLE_1 ADD COLUMN COL_1 INT",
        scale_tier="medium",
        outcome_class="clean_ok",
    )
    assert h1 == h2


def test_compute_shape_hash_differs_on_different_inputs() -> None:
    h1 = compute_shape_hash(
        sql_shape_template="ALTER TABLE TABLE_1 ADD COLUMN COL_1 INT",
        scale_tier="medium",
        outcome_class="clean_ok",
    )
    h2 = compute_shape_hash(
        sql_shape_template="ALTER TABLE TABLE_1 ADD COLUMN COL_1 INT",
        scale_tier="large",
        outcome_class="clean_ok",
    )
    assert h1 != h2


# --------------------------------------------------- full orchestration


def test_anonymize_migration_for_sharing_success_path() -> None:
    client = FakeBedrockClient(
        response_json=(
            '{"summary": "A NOT NULL column with a default was added to a busy table.", '
            '"risk_narrative": "Backfill cost scales with row count.", '
            '"lessons_learned": "Split into expand, backfill, constrain.", '
            '"surprise_notes": null}'
        )
    )
    record = anonymize_migration_for_sharing(
        bedrock_client=client,
        bedrock_model_id="fake-model",
        migration_sql="ALTER TABLE customers ADD COLUMN discount_pct INT NOT NULL DEFAULT 0;",
        migration_summary="add discount_pct to customers",
        risk_narrative="customers.discount_pct backfill risk",
        lessons_learned="watch the customers table",
        surprise_notes=None,
        risk_flags=[{"rule_id": "long_running_backfill", "severity": "medium", "message": "customers-specific text"}],
        scale_tier="medium",
        outcome_class="clean_ok",
    )
    assert record is not None
    assert "customers" not in record.sql_shape_template
    assert "discount_pct" not in record.sql_shape_template
    assert "customers" not in record.generalized_summary
    assert record.risk_flags == [{"rule_id": "long_running_backfill", "severity": "medium"}]
    assert record.shape_hash


def test_anonymize_migration_for_sharing_rejects_when_bedrock_output_leaks_identifier() -> None:
    """The test that actually matters: even if the LLM generalization step
    itself fails to scrub an identifier, the pipeline must reject the
    promotion rather than store the leak. This is Step 4 doing its job as
    the real backstop, not Step 3's prompt being trusted blindly."""
    client = FakeBedrockClient(
        response_json=(
            '{"summary": "A column was added to the customers table.", '
            '"risk_narrative": "generic", "lessons_learned": "generic", '
            '"surprise_notes": null}'
        )
    )
    record = anonymize_migration_for_sharing(
        bedrock_client=client,
        bedrock_model_id="fake-model",
        migration_sql="ALTER TABLE customers ADD COLUMN discount_pct INT NOT NULL DEFAULT 0;",
        migration_summary="add discount_pct to customers",
        risk_narrative="customers.discount_pct backfill risk",
        lessons_learned="watch the customers table",
        surprise_notes=None,
        risk_flags=[],
        scale_tier="medium",
        outcome_class="clean_ok",
    )
    assert record is None


def test_anonymize_migration_for_sharing_returns_none_on_unparseable_sql() -> None:
    client = FakeBedrockClient(response_json='{"summary":"x","risk_narrative":"x","lessons_learned":"x","surprise_notes":null}')
    record = anonymize_migration_for_sharing(
        bedrock_client=client,
        bedrock_model_id="fake-model",
        migration_sql="NOT VALID SQL ((( ???",
        migration_summary="x",
        risk_narrative="x",
        lessons_learned="x",
        surprise_notes=None,
        risk_flags=None,
        scale_tier="medium",
        outcome_class="clean_ok",
    )
    assert record is None


def test_anonymize_migration_for_sharing_returns_none_on_bedrock_failure() -> None:
    client = FakeBedrockClient(should_raise=True)
    record = anonymize_migration_for_sharing(
        bedrock_client=client,
        bedrock_model_id="fake-model",
        migration_sql="ALTER TABLE customers ADD COLUMN discount_pct INT NOT NULL DEFAULT 0;",
        migration_summary="x",
        risk_narrative="x",
        lessons_learned="x",
        surprise_notes=None,
        risk_flags=None,
        scale_tier="medium",
        outcome_class="clean_ok",
    )
    assert record is None


# ------------------------------------- Step 1b: schema-snapshot identifiers

_SNAPSHOT = {
    "database_name": "acme_prod",
    "schemas": [
        {
            "name": "public",
            "tables": [
                {
                    "name": "dunning_ledger",
                    "columns": [{"name": "id"}, {"name": "escalation_tier"}],
                    "indexes": [{"name": "idx_dunning_escalation"}],
                }
            ],
        }
    ],
}


def test_extract_schema_identifiers_finds_tables_columns_indexes() -> None:
    found = extract_schema_identifiers(_SNAPSHOT)
    assert "dunning_ledger" in found
    assert "escalation_tier" in found
    assert "idx_dunning_escalation" in found
    assert "acme_prod" in found


def test_extract_schema_identifiers_drops_generic_names() -> None:
    """Generic column names must NOT be leak-checked — "id"/"name"/"public"
    collide with the generic structural prose step 3 is supposed to
    produce, and would reject every promotion for no safety gain."""
    found = extract_schema_identifiers(_SNAPSHOT)
    assert "id" not in found
    assert "public" not in found


def test_extract_schema_identifiers_tolerates_garbage() -> None:
    assert extract_schema_identifiers(None) == frozenset()
    assert extract_schema_identifiers("not a dict") == frozenset()
    assert extract_schema_identifiers({"schemas": [None, {"tables": [None]}]}) == frozenset()


def test_anonymize_rejects_schema_identifier_leaked_by_bedrock() -> None:
    """The real regression: a table named in the SCHEMA SNAPSHOT but never
    named in the migration SQL. Before extract_schema_identifiers existed,
    the leak check only knew about SQL identifiers, so Bedrock echoing
    'dunning_ledger' here passed undetected."""
    leaky = FakeBedrockClient(
        '{"summary": "Adds a column.",'
        ' "risk_narrative": "The dunning_ledger table will be locked.",'
        ' "lessons_learned": "Backfill was slow.",'
        ' "surprise_notes": null}'
    )
    record = anonymize_migration_for_sharing(
        bedrock_client=leaky,
        bedrock_model_id="test-model",
        # NOTE: migration SQL touches a *different* table entirely.
        migration_sql="ALTER TABLE invoices ADD COLUMN retry_count INT;",
        migration_summary="adds a column",
        risk_narrative="r",
        lessons_learned="l",
        surprise_notes=None,
        risk_flags=[],
        scale_tier="small",
        outcome_class="clean_ok",
        schema_snapshot=_SNAPSHOT,
    )
    assert record is None, "schema-snapshot identifier leak must reject promotion"


def test_anonymize_without_schema_snapshot_still_works() -> None:
    """schema_snapshot is optional — runs that never discovered a schema
    must still be promotable."""
    clean = FakeBedrockClient(
        '{"summary": "Adds a nullable column to the target table.",'
        ' "risk_narrative": "Low risk.",'
        ' "lessons_learned": "Completed quickly.",'
        ' "surprise_notes": null}'
    )
    record = anonymize_migration_for_sharing(
        bedrock_client=clean,
        bedrock_model_id="test-model",
        migration_sql="ALTER TABLE invoices ADD COLUMN retry_count INT;",
        migration_summary="adds a column",
        risk_narrative="r",
        lessons_learned="l",
        surprise_notes=None,
        risk_flags=[],
        scale_tier="small",
        outcome_class="clean_ok",
        schema_snapshot=None,
    )
    assert record is not None
