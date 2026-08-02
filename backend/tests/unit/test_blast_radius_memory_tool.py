"""Regression tests for the agent-facing `search_prior_migrations` tool.

Task 6: the blast-radius investigator can query Migration Oracle's own graded
history mid-investigation, via CockroachDB's distributed vector index. These
tests need no database and no AWS — they lock in the contracts that are easy to
break silently:

* the tool is only offered when it can actually be served,
* it never raises (a failed search is a finding, not a crash),
* its output stays inside the context cap it promises,
* documented open-source incidents are never presented as our own graded runs.
"""

from __future__ import annotations

import asyncio

from app.shadow.blast_radius_investigator import (
    _MEMORY_RESULT_MAX_CHARS,
    _MEMORY_TOOL_MAX_LIMIT,
    _MEMORY_TOOL_SPEC,
    MEMORY_TOOL_NAME,
    _format_memory_hits,
    _search_prior_migrations,
)


class _Mem:
    """Minimal stand-in for a MigrationMemory row."""

    def __init__(
        self,
        *,
        migration_type="add_column",
        scale_tier="large",
        summary="did a thing",
        lesson="learned a thing",
        outcome="backfill_rewrite",
        predicted=900.0,
        actual=1200.0,
        not_graded=False,
    ):
        self.migration_type = migration_type
        self.scale_tier = scale_tier
        self.migration_summary = summary
        self.lessons_learned = lesson
        self.prediction_summary = {"estimated_duration_seconds": predicted}
        self.execution_summary = {"actual_duration_seconds": actual}
        self.grade_summary = {
            "outcome_class": outcome,
            "integrity": {"not_a_graded_run": not_graded},
        }


class _Embedder:
    def __init__(self, boom=False):
        self.boom = boom

    def embed(self, text, *, model_id=None):
        if self.boom:
            raise RuntimeError("titan exploded")
        return [0.0] * 1024

    @property
    def model_id(self):
        return "test"


class _Repo:
    """Session stub whose only job is to satisfy MigrationMemoryRepository."""

    def __init__(self, rows=None, boom=False):
        self.rows = rows or []
        self.boom = boom


def test_tool_spec_shape_is_valid_bedrock_toolspec() -> None:
    spec = _MEMORY_TOOL_SPEC["toolSpec"]
    assert spec["name"] == MEMORY_TOOL_NAME
    assert spec["inputSchema"]["json"]["required"] == ["query"]
    props = spec["inputSchema"]["json"]["properties"]
    assert set(props) == {"query", "limit"}
    # The description must tell the model this is NOT the shadow cluster —
    # otherwise it wastes calls asking history for live row counts.
    assert "not" in spec["description"].lower()


def test_empty_query_is_an_error_finding_not_a_crash() -> None:
    text, is_error = asyncio.run(
        _search_prior_migrations(
            session=_Repo(), embedding_client=_Embedder(), arguments={}
        )
    )
    assert is_error is True
    assert "query" in text


def test_embedder_failure_never_raises() -> None:
    """A failed search must come back as a finding the model can reason about."""
    text, is_error = asyncio.run(
        _search_prior_migrations(
            session=_Repo(),
            embedding_client=_Embedder(boom=True),
            arguments={"query": "anything"},
        )
    )
    assert is_error is True
    assert "unavailable" in text.lower()
    # It must also steer the model rather than leaving it to guess.
    assert "do not guess" in text.lower()


def test_no_hits_says_unprecedented_rather_than_safe() -> None:
    """An empty corpus result must not read as reassurance."""
    text = _format_memory_hits([], "ix_migration_memories_embedding_ready")
    assert "unprecedented" in text.lower()
    assert "no prior migrations" in text.lower()


def test_open_source_incident_is_not_labelled_as_our_graded_run() -> None:
    ours = _format_memory_hits([(_Mem(not_graded=False), 0.9)], "ix")
    theirs = _format_memory_hits([(_Mem(not_graded=True), 0.9)], "ix")
    # Match the delimited origin field, not a bare substring: the disclaimer
    # "(not one of our graded runs)" legitimately *contains* "our graded run".
    assert "| our graded run |" in ours
    assert "| documented open-source incident" in theirs
    assert "| our graded run |" not in theirs
    assert "not one of our graded runs" in theirs


def test_predicted_vs_actual_is_rendered_and_missing_data_is_honest() -> None:
    with_both = _format_memory_hits([(_Mem(predicted=900.0, actual=1200.0), 0.5)], "ix")
    assert "predicted 900s -> actual 1200s" in with_both

    missing = _Mem()
    missing.execution_summary = {}
    assert "duration not recorded" in _format_memory_hits([(missing, 0.5)], "ix")


def test_output_is_capped_for_model_context() -> None:
    """Long corpus text must not blow up the model's context window."""
    huge = _Mem(summary="x" * 5000, lesson="y" * 5000)
    text = _format_memory_hits([(huge, 0.5)] * _MEMORY_TOOL_MAX_LIMIT, "ix")
    assert len(text) <= _MEMORY_RESULT_MAX_CHARS


def test_index_name_is_surfaced_so_the_index_is_visible_not_just_claimed() -> None:
    text = _format_memory_hits([(_Mem(), 0.5)], "ix_migration_memories_embedding_ready")
    assert "ix_migration_memories_embedding_ready" in text
    assert "vector index" in text
