# backendfix.md

Shared working memory for the Migration Oracle build. Every task reads this
first and updates it before finishing. If something in here is wrong, fix it
here rather than working around it silently.

## Project

Migration Oracle. CockroachDB x AWS hackathon submission.
Predicts the blast radius of a schema migration, verifies the prediction on a
real disposable shadow cluster, grades the prediction against measured reality,
and stores the graded outcome as memory that sharpens future predictions.

Deadline: August 18.
Team: two people. Samved owns all backend and infrastructure.

The differentiator, the thing no competitor does: the closed loop.
Predict, verify on real infrastructure, grade, remember. Existing tools
(Bytebase, Squawk) do static rule checks and stop there. Protect this loop
above all else. Anything that weakens it is the wrong tradeoff.

## Current state

- Backend: Phases 1 through 10 code complete.
- AWS: Shared stack `migration-oracle` is `UPDATE_COMPLETE` (redeployed
  2026-07-25). Physical sweeper Lambda is `migration-oracle-shadow-sweeper`
  (EventBridge scheduled). Manual invoke with `{}` returns
  `{swept_db_rows:[], swept_provider_clusters:[], errors:[], orphan_candidates:0}`
  — `require_run=False` is live.
- Bedrock: working. Prediction uses Haiku 4.5 (local `.env`); Titan embeddings
  work. Recommendation is a separate Bedrock call. Predict explainability includes
  `bedrock_traces.prediction` with `attempts` + `repair_retried`.
- Shadow: `SHADOW_PROVIDER=ccloud_api`, `SHADOW_MAX_CONCURRENT=2`,
  `SHADOW_APP_TAG=migration-oracle`. Real BASIC clusters provision with
  `labels.app` / `labels.run`, execute, and tear down (~58s visible lifetime).
  Mid-flight abort: `POST /runs/{id}/abort-workflow` stops SFN and runs cleanup
  explicitly (ASL Cleanup does not run on StopExecution alone).
- Legacy `/ui` StaticFiles mount **retired**. Operators use Next.js
  (`frontend/oracle`, `npm run dev` on :3000).
- New frontend wired through real predict → proceed → SFN shadow → grade →
  memory → second predict. Prefer matching `NEXT_PUBLIC_API_BASE_URL` to the
  live API port (8001/8002). CORS must include both `localhost:3000` and
  `127.0.0.1:3000`; set `CORS_ORIGINS` when a public frontend URL exists.
- Shadow UI: `ShadowLivePanel` shows real-time cluster lifecycle + prediction
  vs measured actuals (no mock verify fallback; fake-migration debug gated).
- Ops: `docs/DEMO_OPS.md` (Windows start, demo timing ~5–7 min, cost note,
  abort). Chaos driver: `backend/scripts/judge_chaos_checks.py` (fail-fast
  predict ceilings; `JUDGE_SKIP_DUAL=1` to avoid dual-cloud spend).
- Demo readiness: **demo-ready for the closed-loop beat**. Remaining human items:
  public frontend URL for CORS; exact USD from Cockroach invoice.

## Decisions already locked. Do not relitigate these.

Policy layer
- Deterministic rules are strictly static. Severity is never tuned by memory.
  Auditability wins over a slightly better learning narrative.
- Rules live in a YAML file in the repo, not hardcoded and not per user in the DB.
- SQL parsing uses sqlglot, not regex. Regex cannot reliably detect table
  rewrites or backfill candidates.
- policy_decision=block is strongly worded but overridable, always with a
  recorded rationale. It is never a hard stop.

Prediction
- Units are absolute seconds and MB. Grading becomes tier aware by segmenting on
  ShadowCluster.scale_tier after the fact, not by normalizing beforehand.
- Predictions target the shadow run only, never the user's production database.
  Production prediction is ungradeable and out of scope.
- Rollback risk is a three value enum: low, medium, high.
- Confidence is hybrid. The model proposes a raw value, then deterministic code
  clamps it based on four measurable signals: weak retrieval, size mismatch,
  uncommon migration type, unusual risk flags.
- Prediction and recommendation are two separate Bedrock calls with
  independently versioned prompt templates.

Recommendation engine
- Output is described steps plus illustrative SQL snippets. NEVER fully
  generated executable migration SQL.
- The shadow cluster only ever executes the user's own original migration_sql.
  AI generated SQL is never executed. This is a hard safety line.

Identity and auth
- No real authentication. No Clerk. owner_identity is a plain string passed
  through, matching the approver_identity pattern.
- Retrieval scopes to the requesting owner plus the reserved corpus identity
  __migration_oracle_corpus__. That constant must exist in exactly one place in
  the codebase and be imported everywhere else.

Human in the loop
- Approval is POST /runs/{id}/approve with a persisted decision record.
- Three options: proceed, accept_recommended, cancel. There is no "reject".
- Status transitions: proceed leads to running, accept_recommended leads to
  completed with no shadow run, cancel leads to failed.
- Step Functions does not pause for approval. Approval gates at the DB and API
  layer, and the workflow only starts after a human has approved. A
  waitForTaskToken pause is deliberately deferred.

Infrastructure
- Provisioning is a ZIP Lambda calling the CockroachDB Cloud REST API
  (SHADOW_PROVIDER=ccloud_api). NOT a container image, NOT the ccloud CLI. The
  CLI is interactive browser auth only and cannot authenticate in Lambda.
- Grading and memory writing hook into the persist results path so the loop
  closes automatically, plus a manual POST /runs/{id}/grade for testing.
- Prediction is API side, not a Step Functions state. The ASL is:
  discover, provision, load, execute, collect, persist, cleanup.
- Region is us-east-1 for all AWS services.

## Frontend and backend vocabulary mismatch

RESOLVED for the Next app via an explicit mapping module:
`frontend/oracle/apps/web/lib/api/map-run.ts`.

Backend remains the source of truth. The UI no longer invents statuses.

### Final mapping decisions

| UI concern | Backend source | Mapping |
|---|---|---|
| Status badge | `MigrationRun.status` | Show backend enum + human label (`pending` → Pending, …). Never invent EXECUTING / REJECTED / APPROVED. |
| Workflow line | `workflow_status` | Shown beside status (`not_started` … `aborted`). |
| Process strip | derived from status (+ workflow) | create → predict → approve → shadow → grade → remember via `mapProcessStages`. |
| Assessment | `explainability.prediction`, `explainability.confidence`, top-level `recommendation`, `policy_decision`, `risk_flags`, `compatibility_risk` | `mapAssessment`. No fabricated benefits / four-way riskBreakdown. |
| Confidence reduction | `explainability.confidence.adjustments[]` | Show each `reason_code` + `reason` + `amount` when `wasReduced`. |
| Retrieval | `explainability.memory` | Ranked memories, similarity, attribution signals, `empty_vs_never_attempted` / `weak_retrieval`. Plain-text DVI callout. |
| Actions | ApprovalDecision | Proceed / Accept recommended plan / Cancel. Optional override rationale; required when `policy_decision=block` and decision is proceed (UI also asks for accept_recommended). `start_workflow: false` on approve; separate Start shadow button. |
| Shadow path | `/health.integrations.sfn_ready` | If true: `start-workflow` + poll `sync-workflow`. Else (or on config failure): `verify-local`. |
| Outcome | grade + execution-result + shadow-cluster + memory | `mapComparisons` for predicted vs actual; no invented deltas. |
| Dual DB chrome | none | Removed. Model is SQL + connection secret ARN + shadow CRDB. |
| Identity | `owner_identity` | Sidebar + Settings localStorage field. Approver uses the same string. |
| Polling | no streaming | `usePolling`: 2.5s, backoff after 60s to 8s, 30m ceiling, pause when tab hidden, stop on terminal. |

### Historical mismatch table (for context)

| Old mock frontend expected | Backend actually has |
|---|---|
| EXECUTING, VERIFIED, APPROVED, REJECTED | pending, predicting, awaiting_approval, running, completed, failed, plus workflow_status |
| assessment, riskBreakdown, benefits, concerns | prediction, recommendation, explainability, policy_decision, risk_flags |
| Approve / Reject buttons | proceed / accept_recommended / cancel |
| A phase machine: provisioning, cloning, executing | SFN status + pipeline-progress + shadow-cluster + execution-result |
| Live streaming updates | No streaming. Polling only. |
| Clerk style OAuth login | Soft owner_identity plus optional X-API-Key |
| Postgres to Cockroach source/target selection | SQL plus connection plus shadow CRDB |

## Known endpoints

Verify against the live OpenAPI spec rather than trusting this list.
Committed snapshot: `frontend/oracle/apps/web/lib/api/openapi.json`.
Regenerate types: from `apps/web`, `npm run gen:api` (after refreshing openapi.json
from a running API or `app.openapi()`).

GET /health
POST /runs
GET /runs
GET /runs/{id}
PATCH /runs/{id}
POST /runs/debug/fake-migration
POST /runs/{id}/discover
POST /runs/{id}/predict
POST /runs/{id}/approve
POST /runs/{id}/start-workflow
POST /runs/{id}/sync-workflow
POST /runs/{id}/verify-local
POST /runs/{id}/closed-loop
GET /runs/{id}/pipeline-progress
GET /runs/{id}/model-traces
GET /runs/{id}/grade
GET /runs/{id}/memory
GET /runs/{id}/execution-result
GET /runs/{id}/shadow-cluster
GET /runs/metrics/accuracy
GET /memories
GET /memories/health

Note: GET /runs/{id} does **not** embed a top-level `prediction` object.
Prediction numbers live under `explainability.prediction` and confidence under
`explainability.confidence`. The ORM prediction row is not serialized on the run.

## The corpus

Source list lives in githubs.md. It is a list of repos and documented
incidents, not data. The ingestion pattern already exists and works:

1. Pick one migration plus a documented outcome (GitHub issue or blog post).
2. Store it as JSON under backend/data/open_source_corpus/.
3. ensure_open_source_corpus() seeds it into memory with a Titan embedding on
   API startup.
4. scripts/seed_open_source_corpus.py --verify-retrieval confirms it is
   retrievable.

Currently seeded: multiple open-source corpus JSON entries under
backend/data/open_source_corpus/ (Temporal, Airflow, Superset, PG patterns,
etc.), integrity-labeled and excluded from accuracy metrics.

IMPORTANT INTEGRITY RULE: corpus entries are real documented incidents but they
are NOT graded runs. Nobody predicted them and measured the error. They must be
clearly distinguishable from genuine graded outcomes, excluded from accuracy
metrics, and labeled as such in the UI. Do not let them inflate any number that
implies the system has verified history it does not have.

Memory list/detail API now surfaces `not_a_graded_run`, `source_url`,
`ui_label`, `integrity_kind` from `grade_summary.integrity` so the UI can badge
corpus rows without guessing from owner alone.

## The demo beat that must work

Retrieval must be able to surface a memory that shares a MECHANISM with the
current migration despite sharing almost no SQL vocabulary. Example pair:

  ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
  CREATE INDEX idx_orders_region ON orders (region)

Different statement type, different table, near zero lexical overlap, but both
trigger a full row backfill and both scale with row count the same way.

This only works if the embedded text is composed from the migration summary,
the risk narrative, the lessons learned, and the surprise note, with raw DDL as
a minority component at most. If embedding text is DDL dominant, retrieval
matches on vocabulary instead of meaning and this beat falls flat.

## Known defects to verify and fix

- Possible owner_identity mismatch. An older seeding path may have written rows
  as 'demo-corpus' instead of the reserved constant, making them invisible to
  retrieval. Check for both values. (Seeding path now rekeys legacy demo-corpus.)
- Table naming: real table is `migration_memories`.
- Rows may exist without embeddings, or without scale_tier and migration_type,
  which degrades hybrid retrieval to pure vector similarity. Memory health UI
  surfaces these loudly.
- Graded runs now exist for `judge-demo` after the 2026-07-25 PATH1 loop;
  accuracy overview must still stay honest for owners with zero grades.
- `GET /runs/{id}/pipeline-progress` clears once the run leaves `predicting`
  (no stale predict progress during shadow).
- Missing-table SQL emits deterministic risk flag `missing_referenced_table`
  with policy `block` when a schema snapshot exists.

## Working rules for every task

- Read this file before starting. Update it before finishing.
- Never fabricate data. No placeholder memories, no synthetic similarity
  scores, no invented history. Empty states must read as genuinely empty.
- Everything must behave correctly with zero memories and zero graded runs, and
  degrade visibly rather than silently.
- Read the actual code before assuming a path, a shape, or a convention.
- If earlier phase code needs changing, do it, and flag the change and the
  reason in the Change Log below.
- Prefer fixing the root cause over adding a workaround.

## Change Log

### 2026-07-25 — Live shadow box + no mock verify in UI

What changed
- New `ShadowLivePanel`: live cluster lifecycle from `shadow.status` +
  `stage_timings` (provision → ready → seed → migrate → teardown), cluster
  facts, and prediction-vs-measured comparison while the workflow runs.
- Current Migration, Shadow Execution page, and run detail poll
  `sync-workflow` + `shadow-cluster` + `execution-result` mid-flight.
- Removed silent fallback to `verify-local` mock shadow; Start shadow requires
  real Step Functions. Fake-migration UI gated behind
  `NEXT_PUBLIC_ENABLE_DEBUG_TOOLS=true`.
- Landing ProductPreview metrics labeled as illustration-only sample.

What was verified
- Typecheck passes. Live completed run `d0bd7fd8-…` has real provider
  `cockroachdb_cloud_api`, stage timings in ms, execution actuals, and grade
  bands — UI maps these (no invented numbers).

### 2026-07-25 — Remaining demo gaps (sweeper, policy, abort, /ui)

What changed
- SAM redeploy: stack `UPDATE_COMPLETE`; sweeper physical name
  `migration-oracle-shadow-sweeper`; EventBridge schedule live; empty-event
  invoke succeeds (no `event.run_id is required`).
- Policy: `missing_referenced_table` rule (`block`) when SQL references tables
  absent from the schema snapshot.
- Pipeline progress: cleared unless run status is `predicting`; also cleared on
  approve / start-workflow.
- Abort: `POST /runs/{id}/abort-workflow` + Next Abort control; StopExecution
  plus explicit cleanup handler teardown.
- Legacy `/ui` StaticFiles mount removed; docs/README/`scripts/dev.py` point at
  Next.js. Windows: prefer `backend/_run_api_reload.py` / `scripts/dev.py`.
- Ops notes: `docs/DEMO_OPS.md`. Chaos script fail-fast predict ceilings +
  `JUDGE_SKIP_DUAL`.

What was verified live
- missing_table → policy `block` + flag `missing_referenced_table`.
- Abort mid-shadow → run `failed` / workflow `aborted`; Cloud cluster torn down.
- Bedrock traces: `attempts` + `repair_retried` on fake-migration predict.
- Dual shadows: both start-workflow admitted (`SHADOW_MAX_CONCURRENT=2`); abort
  both; Cloud list can lag ~15–30s after destroy — poll then confirm zero
  `labels.app=migration-oracle` leftovers.
- Sweeper Lambda invoke OK.

### 2026-07-25 — Judge walkthrough (real shadow + fixes)

What was driven (not claimed from unit tests)
- Full PATH1 on real `ccloud_api` + SFN: discover RO `customer_demo.customers`
  (5000 rows) → predict → proceed → start-workflow → Cloud cluster
  `mo-d0bd7fd8bc124520` with `labels.app=migration-oracle` → teardown → grade +
  memory → second similar migration retrieved first graded memory (closed loop).
- PATH2: concurrency cap DB probe `[True,True,False]` + slot timeout; local
  sweeper clean; tag confirmed on live cluster. No deliberate orphan / mid-flight
  kill / three live shadows.
- PATH3: bad ARN 422, unreachable DB 408, accept_recommended completed with no
  shadow, cancel → failed, DROP TABLE block + override rationale on
  `GET /runs/{id}/approval`. Invalid SQL now `policy_decision=block`.
- PATH4/5 Playwright: pages render; corpus badged; no fake auth chrome.

Real stage timings (PATH1 run `d0bd7fd8-…`)
- create 2.2s · discover 19.5s · predict 59.7s · approve 11.6s · shadow wall
  ~107s · second predict 56.9s
- Shadow stage_timings ms: provision 3857 · ready 8093 · seed 7633 · migrate
  8061 · teardown 2933 · cluster lifetime ~58s

Per-run shadow cost
- Not determined in USD (BASIC plan / serverless RU billing). Lifetime ~58s.

What changed (fixes)
- `RetrievedMemory.memory_id` + UI graded/corpus labels on retrieval cards.
- `parse_failure` policy decision `allow_with_warning` → `block`; PolicyEngine
  re-reads YAML each analyze (`get_policy_file_fresh`) because uvicorn reload
  does not watch `.yaml`.
- Next UI: `getApproval` + recorded decision / override rationale panel.
- Windows helpers: `backend/_run_api.py`, `backend/_run_api_reload.py`.
- Judge drivers: `judge_path1_live.py`, `judge_path3_failures.py`, artifacts.

What remains open (see Open Questions + WALKTHROUGH.md)
- SAM redeploy for sweeper; missing-table risk flag; stale pipeline-progress
  during shadow; mid-flight kill / dual shadow / Bedrock repair UI not fully
  browser-proven.

### 2026-07-24 — Wire Next.js frontend end-to-end

What changed
- New API layer under `frontend/oracle/apps/web/lib/api/`:
  client (`NEXT_PUBLIC_API_BASE_URL`, default `http://127.0.0.1:8000`),
  OpenAPI snapshot + generated `schema.ts` (`npm run gen:api`),
  typed `endpoints.ts`, `map-run.ts` mapping module, owner/localStorage helpers,
  `usePolling`.
- Current Migration workspace: create (SQL / fake-migration), discover,
  predict + pipeline-progress, assessment, retrieval transparency (DVI note +
  DDL side-by-side), three real approvals, shadow start (SFN or verify-local),
  outcome (grade / memory / shadow / execution).
- Overview, history, run detail (`/dashboard/migrations/[id]` with lifecycle +
  model traces), memory browser + health, settings (owner + ARN + API base).
- Shell honesty: removed Clerk-style auth routes (redirect to dashboard), fake
  sidebar user, broken `/docs` links, coming-soon repo/compare methods, dual
  Postgres→Cockroach chrome, mock CURRENT_MIGRATION data.

Backend schema touched (and why)
- `MemoryResponse` / `MemoryListItem`: added `not_a_graded_run`, `source_url`,
  `ui_label`, `integrity_kind` via shared `integrity_fields()` so the memory
  browser can distinguish corpus rows without inventing client-side heuristics.
- CORS was already env-configurable (`CORS_ORIGINS`); documented deployed-origin
  placeholder in `.env.example`. No wildcards.

Frontend features removed (and why)
- Sign-in / sign-up / OAuth / get-started decorative auth — backend has no auth.
- Fake `operator@migrationoracle.dev` sidebar user.
- `/docs` nav (no route).
- Coming soon: Connect Repository, Compare Schema.
- Mock assessment fields (benefits, fabricated riskBreakdown).
- Dual database source/target selector.
- Hardcoded dashboard command-center / CURRENT_MIGRATION / live shadow mocks.

What was verified
- `npm run typecheck` in apps/web passes.
- OpenAPI export from FastAPI + `openapi-typescript` generation succeeds.
- Mapping and endpoint modules align with live schemas.

What was NOT fully verified (testing task needs to know)
- Full real Bedrock predict → approve → SFN shadow → grade → memory on the
  Next UI against a live API (needs `scripts/dev.py restart` + AWS/Bedrock).
- Discover against a real customer DB / Secrets Manager ARN (error mapping is
  coded from backend status codes; not live-exercised here).
- Deployed frontend origin not added to CORS — local defaults only; set
  `CORS_ORIGINS` when a public URL exists.
- Orphaned unused auth form components (`login-form.tsx`, `signup-form.tsx`)
  remain on disk but routes redirect away.
- Legacy `/ui` intentionally untouched and still the proven fallback.

Next task should
- Run a full closed loop through the Next console (fake-migration path first,
  then real SFN if configured).
- Confirm memory health + corpus badges with seeded corpus.
- Confirm accuracy overview with zero graded runs stays honest.
- Only after a successful end-to-end Next run: decide whether to retire `/ui`.

## Open Questions

Anything you hit that needs a human decision. Do not guess and move on.

- Deployed frontend URL for CORS (when known).
- Whether to delete orphaned login/signup form components after judges never
  need them (harmless today).
- Exact per-run USD from Cockroach Cloud invoice / BASIC RU pricing for the
  demo script voiceover.
