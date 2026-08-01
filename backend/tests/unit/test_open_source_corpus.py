"""Regression tests for open-source corpus integrity and metrics exclusion."""

from __future__ import annotations

import pytest

from app.memory.constants import (
    CORPUS_OWNER_IDENTITY,
    MEMORY_ORIGIN_OPEN_SOURCE_INCIDENT,
)
from app.memory.embed_text import compose_embed_text
from app.memory.open_source_corpus import (
    assert_corpus_owner,
    integrity_block,
    load_open_source_records,
)


def test_corpus_owner_constant_enforced() -> None:
    assert_corpus_owner(CORPUS_OWNER_IDENTITY)
    with pytest.raises(ValueError, match="CORPUS_OWNER_IDENTITY"):
        assert_corpus_owner("demo-corpus")
    with pytest.raises(ValueError, match="CORPUS_OWNER_IDENTITY"):
        assert_corpus_owner("anonymous")


def test_integrity_block_marks_not_graded() -> None:
    block = integrity_block(
        source_key="temporal:test",
        source_url="https://github.com/temporalio/temporal/issues/6273",
        project="Temporal",
    )
    assert block["kind"] == MEMORY_ORIGIN_OPEN_SOURCE_INCIDENT
    assert block["not_a_graded_run"] is True
    assert block["exclude_from_accuracy_metrics"] is True
    assert "6273" in (block["source_url"] or "")


def test_json_corpus_has_mechanism_summaries_and_spread() -> None:
    records = load_open_source_records()
    assert 8 <= len(records) <= 20
    types = {r.migration_type for r in records}
    assert "create_index" in types
    assert "add_column" in types
    for rec in records:
        assert rec.migration_summary
        assert not rec.migration_summary.upper().startswith("CREATE ")
        assert rec.grade_summary["integrity"]["not_a_graded_run"] is True
        assert rec.grade_summary["integrity"]["exclude_from_accuracy_metrics"] is True
        emb = compose_embed_text(
            migration_summary=rec.migration_summary,
            risk_narrative=rec.risk_narrative,
            lessons_learned=rec.lessons_learned,
            surprise_notes=rec.surprise_notes,
            migration_sql=rec.migration_sql,
        )
        narrative = emb.split("DDL excerpt:")[0]
        ddl_part = emb.split("DDL excerpt:")[-1] if "DDL excerpt:" in emb else ""
        assert len(narrative) > len(ddl_part), "DDL must be minority of embed text"


def test_compose_strips_ddl_dominant_summary() -> None:
    emb = compose_embed_text(
        migration_summary="create_index: CREATE INDEX idx ON t(a);",
        risk_narrative="Blocking index on a hot table causes write stalls.",
        lessons_learned="Prefer CONCURRENTLY outside transactions.",
        surprise_notes="Staging succeeded; production timed out.",
        migration_sql="CREATE INDEX idx ON t(a);",
    )
    assert "CREATE INDEX idx ON t(a)" not in emb.split("DDL excerpt:")[0]
    assert "mechanism" in emb.lower() or "Migration summary:" in emb
    assert emb.count("CREATE INDEX") <= 1


def test_accuracy_metrics_sql_excludes_open_source_predicate() -> None:
    """Static check that metrics module keeps the exclusion predicate."""
    import inspect

    from app.memory import metrics as metrics_mod

    src = inspect.getsource(metrics_mod.fetch_accuracy_metrics)
    assert "open_source" in src
    assert "synthetic_seed" in src or "exclude_from_accuracy" in src or "integrity" in src
    assert "NOT IN ('open_source', 'seed')" in src or "open_source" in src
