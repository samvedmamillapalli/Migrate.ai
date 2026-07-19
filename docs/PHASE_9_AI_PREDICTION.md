# Phase 9: AI Prediction, Policy Checks, and Recommendation Engine

This document describes what was built for Phase 9. The authoritative design
decisions live in [`phase9.md`](phase9.md); this file is the implementation
record.

Roadmap mapping: Development Roadmap Phase 9 (predict step + safety layer +
human approval gate). Nothing in this phase executes migrations or grades
outcomes.

---

## What was built

Order of operations for a single run:

```
Schema snapshot (Phase 6) + migration SQL
        ↓
Deterministic Risk and Policy Layer   (sqlglot + YAML)
        ↓
Memory retrieval stub                 (empty; Phase 10 fills)
        ↓
AI Prediction (Bedrock call #1)
        ↓
Recommendation Generation (Bedrock call #2)
        ↓
awaiting_approval                     (human gate)
        ↓
Shadow execution only after proceed   (Phase 7 / 8 — not auto-started here)
```

### Packages

| Path | Responsibility |
| --- | --- |
| `backend/app/policy/` | YAML policy load/validate, sqlglot analysis, findings aggregation |
| `backend/app/prediction/` | Bedrock client, prompts, prediction, recommendation, confidence, memory stub |
| `backend/app/services/prediction_pipeline_service.py` | Orchestrates the full Phase 9 path |
| `backend/app/services/approval_service.py` | Human approval recording + status transitions |
| `POST /runs/{id}/predict` | Trigger the pipeline (script/API; not SFN) |
| `POST /runs/{id}/approve` | Record proceed / accept_recommended / cancel |

### Framing (project-wide)

- Blast radius means **backfill duration, storage growth, resource saturation,
  and rollback safety** — never lock duration.
- The closed **predict → verify → grade → remember** loop is the differentiator.
  The deterministic policy layer is safety infrastructure around that loop, not
  the novel contribution.

---

## Policy YAML schema

Committed file: `backend/app/policy/policy.yaml`

Validated on load by `PolicyFile` (`app.policy.models`). Malformed files raise
`PolicyConfigError` — no permissive fallback.

```yaml
version: 1
defaults:
  policy_decision: allow_with_warning
  row_count_thresholds:
    medium: 10000      # escalate severity to at least medium
    high: 1000000      # escalate severity to at least high
decision_precedence:   # most restrictive wins when aggregating
  - allow
  - allow_with_warning
  - block
rules:
  <rule_id>:
    enabled: true
    title: "..."
    base_severity: low | medium | high
    policy_decision: allow | allow_with_warning | block
    requires_manual_review: bool
    requires_expand_contract: bool
    compatibility_risk: low | medium | high
    escalate_by_row_count: bool   # use snapshot estimated_row_count
    explanation: "..."
```

Aggregation: any single contributing `block` makes the overall decision `block`.
High-severity findings and parse failures force `requires_manual_review`.

Parse failure: emit `parse_failure` finding, set review required, set decision
to at least `allow_with_warning` — never crash, never silently allow.

---

## Environment variables

| Variable | Purpose |
| --- | --- |
| `BEDROCK_PREDICTION_MODEL_ID` | Bedrock **inference profile** id (e.g. `us.anthropic.claude-sonnet-4-6`). Bare `anthropic.*` foundation ids are auto-mapped to a regional profile when possible. |
| `BEDROCK_RECOMMENDATION_MODEL_ID` | Optional; defaults to the prediction model id |
| `BEDROCK_REGION` | Defaults to `us-east-1` |
| `BEDROCK_EMBEDDING_MODEL_ID` | Reserved for Phase 10; unused in Phase 9 |

**Prerequisite:** request Anthropic Claude model access in the Amazon Bedrock
console for the configured region before live invocations succeed. Use an
inference profile id such as `us.anthropic.claude-sonnet-4-6` (not only the
foundation model id). Until then, leave the model ids blank and use the
injectable `MockBedrockClient` for verification.

See `.env.example` for commented templates.

---

## Data model changes

Alembic revision: `g2b8e5f1a930_phase9_prediction_policy_approval`

- `migration_runs`: `awaiting_approval` status (Python enum); policy columns
  (`risk_flags`, `compatibility_risk`, `requires_expand_contract`,
  `requires_manual_review`, `policy_decision`, `parsed_statement_types`);
  `recommendation`, `explainability`, `prediction_scale_tier`
- `predictions`: `raw_confidence_score`, `confidence_adjustments`,
  `key_assumptions`, `uncertainty_notes`, `model_version`,
  `prompt_template_version` (spec assumed `model_version` already existed —
  it did not; added here)
- New table `approvals`: append-only audit of human decisions

### Status transitions

```
pending → predicting | failed
predicting → awaiting_approval | failed
awaiting_approval → running | completed | failed
running → completed | failed
```

Approval mapping:

| Decision | New status | Meaning |
| --- | --- | --- |
| `proceed` | `running` | Human chose original SQL; shadow may run later |
| `accept_recommended` | `completed` | Run ends; **no** AI SQL executed |
| `cancel` | `failed` | Cancelled |

Overriding `policy_decision=block` with `proceed` requires
`override_rationale` (enforced in `ApprovalService` / API).

---

## Earlier phase changes

| Change | Why |
| --- | --- |
| `ALLOWED_STATUS_TRANSITIONS` no longer allows `predicting → running` | Gate must stop at `awaiting_approval` |
| `scripts/verify_phase4.py` status walk updated | Match new valid transitions |
| `Prediction` extended with versioning/confidence columns | Spec required fields that Phase 3 did not have |
| Step Functions ASL `DiscoverSchema` Comment annotated | Mark integration point without wiring pause |

---

## Step Functions wiring remaining (Phase 8 follow-up)

Phase 9 builds the DB state, API, and gate logic only. The ASL still goes
`DiscoverSchema → ProvisionShadowCluster` with **no** prediction or approval
pause.

To wire later:

1. After schema discovery (or as a control-plane step before starting SFN),
   call `PredictionPipelineService.run_prediction_pipeline` / `POST /runs/{id}/predict`.
2. Insert a `waitForTaskToken` state (e.g. `AwaitHumanApproval`) before
   `ProvisionShadowCluster`.
3. On `POST /runs/{id}/approve` with `decision=proceed`, call
   `SendTaskSuccess` with the task token; on cancel / accept_recommended, call
   `SendTaskFailure` or succeed into a terminal path that skips provision.
4. Never resume provision for `accept_recommended` — that decision ends the run
   without executing AI-generated SQL.

Marked in code: `PredictionPipelineService` docstring and the
`DiscoverSchema` Comment in `infra/stepfunctions/migration_workflow.asl.json`.

---

## Prompt templates

Versioned files (bump version; do not silently edit in place):

- `backend/app/prediction/prompts/prediction_v1.txt`
- `backend/app/prediction/prompts/recommendation_v1.txt`

`model_version` on each prediction is
`bedrock:{model_id}|prompt:{prompt_version}`.

---

## Verification

From `backend/` (needs `DATABASE_URL`; uses mock Bedrock — no live model access):

```bash
cd backend
alembic upgrade head
python scripts/verify_phase9_ai_prediction.py
```

The script checks:

1. sqlglot policy analysis (block, severity-by-row-count, parse failure)
2. Prediction + recommendation with hybrid confidence (weak retrieval reduction)
3. Transition to `awaiting_approval`
4. Wrong-state approval rejection
5. Block override requiring rationale
6. `accept_recommended` → completed without shadow
7. Cancel → failed
8. One bounded repair retry on malformed model output

API smoke (with mock injected via `app.state.bedrock_client` or live model ids):

```text
POST /runs
POST /runs/{id}/predict
POST /runs/{id}/approve
```
