# Phase 10: Grading, Agentic Memory, and Continuous Improvement

This document describes what was built for Phase 10. The authoritative design
decisions live in [`phase10.md`](phase10.md); this file is the implementation
record.

Roadmap mapping: Development Roadmap Phase 10 (grade + remember). Completes the
closed loop: **predict → verify → grade → remember**.

---

## Locked product decisions used here

| Decision | Choice |
| --- | --- |
| Owner identity (1A) | Soft `owner_identity` string on runs and memories (same pattern as `approver_identity`); no real auth yet |
| When grade/memory run (2A) | Hooked into persist-results / `ExecutionService.record_execution`, plus callable `POST /runs/{id}/grade`. **No** Step Functions Grade state |

---

## What was built

```
Shadow execution persists ExecutionResult
        ↓
Deterministic grading (YAML bands, per tier)
        ↓
Surprise / lessons prose (Bedrock; never blocks numeric grade)
        ↓
Memory write + Titan embedding VECTOR(1024)
        ↓
CockroachDB Distributed Vector Index
        ↓
Hybrid retrieval replaces Phase 9 stub
        ↓
Conditional weak_retrieval confidence adjustment
```

### Packages

| Path | Responsibility |
| --- | --- |
| `backend/app/grading/` | `grading.yaml`, bands, numeric engine, surprise/lessons prose |
| `backend/app/memory/` | Embed text, Titan client, memory write, hybrid retrieval, metrics SQL |
| `backend/app/services/grading_pipeline_service.py` | Orchestrates grade → memory → linked recommendation learning |
| `POST /runs/{id}/grade` | Manual / script path (also auto from persist) |
| `POST /runs/memories/repair-embeddings` | Pending embedding repair |
| `GET /runs/metrics/accuracy` | Plain SQL metrics for Phase 11 charts |

### Framing (project-wide)

- Blast radius means **backfill duration, storage growth, resource saturation,
  and rollback safety** — never lock duration.
- Embeddings emphasize reasoning and surprises, not raw DDL dominance.
- Every retrieval is attributed end-to-end (candidates, scores, re-rank factors,
  prompt inclusion).
- No fabricated memories.

---

## Grading config schema

Committed file: `backend/app/grading/grading.yaml`

Validated on load by `GradingFile`. Malformed files raise `GradingConfigError`
at startup (same fail-loud pattern as Phase 9 policy).

### Scalar accuracy score (frozen formula)

Mean of within-band scores for **duration**, **storage**, and **rollback**.
On timeout, duration contributes **0** (unverifiable) rather than discarding
the run. Documented so the calibration curve stays comparable across corpus runs.

### Timeout handling

`execution_results.timed_out` is set from statement-timeout failures. Duration
is marked unverifiable; rollback/flags still grade; memory lessons call out the
time-budget blow.

### Rollback mapping

- **low** actual: clean success, not rollback_required
- **medium** actual: success but rollback_required
- **high** actual: failure or timeout

Consistency pairs live in YAML (`rollback.consistent_pairs`).

### Surprise / lessons

Versioned prompt `surprise_lessons_v1`. One repair retry. On failure,
`prose_status=failed` with deterministic fallback lessons — **numeric grade is
never blocked**.

---

## Memory + VECTOR index

Table: `migration_memories`

- `VECTOR(1024)` column `embedding`
- CockroachDB **Distributed Vector Index**:
  `CREATE VECTOR INDEX ix_migration_memories_embedding ON migration_memories (embedding vector_cosine_ops)`
- **This index serves every hybrid retrieval candidate query** (required hackathon tool).
- `embedding_status`: `pending` | `ready` | `failed`
- Corpus identity constant: `__migration_oracle_corpus__` (Phase 12 writes under it)

### Embedding text composition

Order (load-bearing): migration summary → risk narrative → lessons → surprise
→ capped DDL excerpt. Stored verbatim on `embed_text`.

### Titan

`BEDROCK_EMBEDDING_MODEL_ID` (default `amazon.titan-embed-text-v2:0`). Injectable
`EmbeddingClient` / `MockEmbeddingClient` for tests.

---

## Hybrid retrieval

1. Embed query text with Titan
2. Vector ANN candidates from the CRDB index (scoped to `owner_identity` + corpus)
3. Deterministic re-rank: semantic, migration type, tier proximity, schema shape,
   risk-flag overlap (weights in `grading.yaml`)
4. Top 5 returned behind the Phase 9 `MemoryRetrieval` interface

Attribution is persisted in `explainability.memory.attribution` on the run.

### Confidence change (Phase 9 behavior update)

`weak_retrieval` reduction now fires only when retrieval is empty or all
similarities are below `retrieval.weak_similarity_threshold`. Adjustment reasons
state actual support found (no longer “stubbed until Phase 10”).

---

## Recommendation learning

- `migration_runs.revises_run_id` links a revised run to an earlier one
- `recommendation_outcome` on the original stores linked evidence
- Success is claimed **only** from linked graded revisions (denominators in metrics)

---

## Environment variables

| Variable | Purpose |
| --- | --- |
| `BEDROCK_PREDICTION_MODEL_ID` | Claude for surprise/lessons (same as Phase 9) |
| `BEDROCK_EMBEDDING_MODEL_ID` | Titan embeddings (1024-d) |
| `BEDROCK_REGION` | Defaults to `us-east-1` |

---

## Alembic

Revision `h3c9f6a2b041_phase10_grading_and_memory`:

- `owner_identity`, `revises_run_id`, `recommendation_outcome` on `migration_runs`
- `timed_out` on `execution_results`
- `grades` table
- `migration_memories` + vector index

---

## API additions

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/runs` | Accepts `owner_identity`, `revises_run_id` |
| POST | `/runs/{id}/grade` | Grade + write memory |
| GET | `/runs/{id}/grade` | Fetch grade |
| GET | `/runs/{id}/memory` | Fetch memory (no raw vector) |
| POST | `/runs/memories/repair-embeddings` | Repair pending embeds |
| GET | `/runs/metrics/accuracy` | SQL metrics payload |

Persist-results Lambda now passes `timed_out` and runs grading automatically.

---

## Verification

```powershell
cd backend
alembic upgrade head
python scripts/verify_phase10_grading_memory.py
```

Uses MockBedrock + MockEmbedding; no live Bedrock required.

---

## Earlier-phase changes

| Area | Change |
| --- | --- |
| Phase 9 confidence | `weak_retrieval` conditional; honest reasons |
| Phase 9 memory interface | Extended with optional attribution fields; stub kept for offline tests |
| Phase 9 prediction pipeline | Uses `HybridMemoryRetrieval` with `owner_identity` |
| Phase 7/8 execution | `timed_out` on outcomes; persist hooks grade+memory |
| Create run API | `owner_identity` + `revises_run_id` |
| Startup | Validates `grading.yaml` alongside `policy.yaml` |

---

## Out of scope (unchanged)

- Seeded corpus batch (Phase 12)
- Frontend charts / memory panel (Phase 11)
- Step Functions Grade state
- Executing AI-generated SQL
- Policy learning from outcomes

---

## What Phase 12 adds

Corpus ingestion under `__migration_oracle_corpus__`, lengthening the accuracy
curves that Phase 10’s machinery already computes honestly from real graded runs.
