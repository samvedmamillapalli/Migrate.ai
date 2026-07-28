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
- Shadow UI: `ShadowLiveView` (2026-07-28 rebuild) — SSE-driven 3-band live
  view (lifecycle rail / stage panel / event log) + schema diff + cost strip;
  doubles as the replay view for finished runs (no mock verify fallback;
  fake-migration debug still gated, demo-database button is not). Full
  Shadow Execution page also has a real before/after row-sample panel
  (2026-07-29) — up to 20 real synthetic rows per referenced table, matched
  by primary key across before/after.
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
- CORRECTED 2026-07-28 (was stale): Clerk auth is real and live
  (`SessionAuthMiddleware`, `app/api/middleware_auth.py` — Bearer token
  required on non-public routes whenever `AUTH_ENABLED` or Clerk keys are
  configured; frontend wires `@clerk/nextjs`). owner_identity is still a plain
  string end to end (set from the verified Clerk JWT, or passed through
  directly when auth is off), matching the approver_identity pattern.
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
GET /runs/{id}/shadow-cluster/stream (SSE; ?token= for EventSource auth)
GET /runs/metrics/accuracy (?owner_identity=)
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

### 2026-07-29 — Prediction/recommendation summaries still too long + a Turbopack/OneDrive gotcha

Follow-up to the 2026-07-28 "plain language" prompt change: a user-provided
screenshot showed the model still writing a multi-paragraph, markdown-formatted
essay into `risk_explanation`/`rationale` despite the v2 prompt asking for
1-2 short sentences — models don't reliably obey length instructions alone.

What changed
- Prompts bumped to v3 (`prediction_v3.txt`, `recommendation_v3.txt`): much
  more explicit — exactly 3-4 sentences (not "1-2", per direct user
  instruction), plain text only with markdown explicitly forbidden
  (`**bold**`, headings, numbered/bulleted lists all called out by name), and
  an explicit instruction to put any extra reasoning into `key_assumptions`/
  `uncertainty_notes`/`rollout_steps`/`monitoring_checklist` instead, since
  those already render under "Show details."
- **Added a frontend safety net that doesn't depend on the model complying**:
  `clampProse()` + `stripMarkdownDecoration()` in `map-run.ts` — strips stray
  markdown decoration and hard-caps `risk_explanation`/`rationale` to 4
  sentences for the always-visible summary, moving anything past that into
  the existing "Show details" section instead of ever rendering an unbounded
  essay inline. This means the display is now correct by construction even
  if a future prompt version or model swap doesn't fully comply again.

Environment finding (unrelated to source code, worth knowing)
- This project's frontend lives inside a live OneDrive-synced folder. Next.js
  16 (Turbopack) dev mode writes `.next/dev/types/routes.d.ts` frequently as
  routes are visited, and this collided with OneDrive's sync layer, twice
  producing a **corrupted file** (correctly-closed content followed by a
  stray duplicate tail fragment) that broke `npm run typecheck` with
  confusing syntax errors unrelated to any real source change. Separately,
  Turbopack's dev-mode typed-routes manifest only registers a page **after
  it's been visited at least once** — `npm run typecheck` will report a
  route literal like `/dashboard/migrations/current/shadow` as invalid until
  something actually requests that URL once against the running dev server.
  If `npm run typecheck` ever fails with errors inside `.next/dev/types/*`
  that don't correspond to anything in `app/`/`components/`/`lib/`: it's
  this, not real source breakage. Fix: `rm -rf .next`, restart `npm run dev`,
  curl/visit every route once, then re-run typecheck. Also found (and
  cleaned up) two orphaned `node.exe` dev-server processes left listening on
  ports 3000/3001 from earlier stop attempts in this session — Windows
  doesn't always kill detached child processes when the wrapping shell task
  is stopped; check `netstat -ano | grep :3000` and `taskkill //F //PID` if
  a "port already in use" surprise shows up.

What was verified
- `npm run typecheck`: 0 errors (after clearing the corrupted cache and
  visiting all routes once).
- `npm run lint`: 0 errors, 19 pre-existing-pattern warnings.
- `python -m pytest tests/unit`: 33/33 pass. `python -c "import app.main"`: clean.
- One dev server left running cleanly on port 3000 (the orphaned duplicates
  were killed).

### 2026-07-29 — Real before/after row samples on the Shadow Execution page

Task: capture a small real row sample from the shadow cluster before and
after the migration runs, and show it in a new panel above the lifecycle
timeline on the full Shadow Execution page.

Investigation findings (see docs/ai_audit.md task write-up for the full
report)
- A before/after capture point already existed — `capture_shadow_schema_snapshot()`
  in `app/shadow/schema_snapshot.py`, called from `migration_runner.py`
  around the migration statement. This task extends that exact point rather
  than adding a new one.
- That function opened its own connection separate from the one running the
  DDL. Reworked it to open one connection and do structure introspection +
  row sampling together (`SchemaAnalyzer.analyze_open_connection`), so this
  task adds zero new connections to the pipeline.
- Table names come from parsing `migration_sql` with `sqlglot` (Postgres
  dialect, `find_all(exp.Table)`), mirroring the exact convention already
  used in `app.policy.engine` rather than inventing a second one.
- Deliberately **not** attached to `ExecutionResult`: that model is scalar-only
  (no JSONB) and is written by `PersistResults`, a *different* Lambda later
  in the pipeline with no shadow-cluster connection — getting row data there
  would mean threading potentially-large JSON through Step Functions state,
  risking the 256KB per-transition payload limit. Attached to `ShadowCluster`
  instead, same place as `schema_snapshot_before/after`, same Lambda, no new
  endpoint (served by the existing `GET /shadow-cluster` + SSE stream).
- Confirmed the real (`ccloud_api`) production seed step
  (`load_schema.py` → `ShadowSeeder().seed_rows_only()`) does insert
  synthetic rows by scale tier, so "before" samples have real data there.
  The local/dev orchestrator fallback path only recreates structure
  (`ShadowSchemaLoader`, no rows) — wired the same capture into that path
  too for consistency, but it will honestly show 0 rows; not fixed, since
  changing that path's seed behavior is a separate, bigger decision.

What changed
- `app/shadow/schema_snapshot.py`: added `extract_referenced_tables()`,
  `capture_shadow_snapshot()` (structure + optional row sample, one
  connection — `capture_shadow_schema_snapshot()` kept as a thin
  structure-only wrapper for back-compat), `build_row_ids_for_matching()`.
  Row fetch is by primary key: "before" takes an ordered `LIMIT 20`; "after"
  re-fetches those exact primary-key values (`WHERE pk IN (...)`, composite
  PK via tuple `IN`) so the same conceptual rows are compared, not an
  arbitrary new sample — falls back to a fresh ordered sample (flagged
  `matched_by_pk=false` with a note) if the before sample had no usable PK
  values. Per-table capture failure is recorded on that table's `error`
  field and never raises — capture is enrichment, never blocks the run.
- `shadow_clusters` gained `row_sample_before` / `row_sample_after` (JSONB) —
  migration `l7g3d0e6f485`.
- `migration_runner.py` (real Lambda path) and `orchestrator.py._migrate()`
  (local path) both call the new capture function with `sample_tables` from
  `extract_referenced_tables(migration_sql)`, threading the before sample's
  PK values into the after call.
- `ShadowClusterService.set_schema_snapshot()` takes two new optional
  params (`row_sample_before`/`row_sample_after`); `execute_migration.py`
  passes them through.
- `ShadowClusterResponse` (`app/schemas/observability.py`) exposes both
  fields — automatically available on the existing GET + SSE stream routes,
  no new endpoint.
- Frontend: `mapRowSamplePanel()` in `map-run.ts` (waiting / unavailable /
  ready states; reuses `mapSchemaDiff()`'s per-table column classification
  for color-coding rather than a second diff pass) + new
  `components/shadow-row-samples-panel.tsx`, mounted on
  `shadow/page.tsx` directly above the `<Section title="Live">` block —
  compact-card `ShadowLiveView` (used elsewhere) is untouched. Integrity
  label ("Sample rows from the disposable shadow cluster. Synthetic data at
  the [tier] scale tier, not your production data.") is a visible
  medium-weight line at the panel top, not a footnote.

What was verified
- `python -m pytest tests/unit`: 33/33 pass.
- `python -c "import app.main"`: clean import.
- `npm run typecheck` / `npm run lint`: 0 errors (1 pre-existing unrelated
  warning).
- **Live-tested the actual row-sampling SQL against the real dev CockroachDB
  database** (not a mock): captured a real 3-row sample from `migration_runs`
  (real PK detection, real total-row-count via `SELECT count(*)`), then
  re-fetched the same rows by primary key for the "after" pass
  (`matched_by_pk=True`, 0 rows lost since nothing changed between calls),
  then confirmed the full payload round-trips through `json.dumps`/`json.loads`
  cleanly (UUIDs, timestamps, nested JSONB columns all coerce correctly via
  `_json_safe`). This is real proof the query generation, quoting, and
  PK-matching logic are correct against genuine CockroachDB — not proof of
  the full shadow-cluster-provisioning pipeline end to end (still blocked by
  the local Windows/Python 3.13 boot issue logged below).
- New `shadow_clusters` columns confirmed present via `information_schema`
  after the migration ran.

Known issue carried forward (not new, not fixed here)
- Local backend HTTP boot is still broken on this Windows Python 3.13
  install (ProactorEventLoop vs psycopg async — see the 2026-07-28 entry
  below for the full description). Everything in this task was verified via
  direct script execution with the correct event loop
  (`loop_factory=asyncio.SelectorEventLoop`), not via a running API server.
  A real shadow run through the deployed Lambda/SFN pipeline is still the
  one thing that needs a working environment to confirm end to end.

What the next task needs to know
- The row-sample panel only appears on the full Shadow Execution page by
  design (task requirement) — it is intentionally not part of the compact
  `ShadowLiveView` used in the floating window, the current-migration inline
  card, or the run-detail page.
- `capture_shadow_schema_snapshot()` (structure-only) still exists for any
  caller that doesn't want row sampling; prefer `capture_shadow_snapshot()`
  for anything new.

### 2026-07-28 — UI audit fixes (Parts A/B) + shadow live view rebuild (Part C)

Full scope: `docs/ai_audit.md` Parts A–C, combined with the earlier
`docs/SHADOW_LIVE_REPRESENTATION_PLAN.md` research pass. Decisions taken
per user answers: SSE transport (not polling), floating panel auto-hides on
the dedicated shadow page, chaos runs get a real `run_kind` field, accuracy
"Succeeded" redefined to % of graded runs that passed, storage-unverifiable
floor = 1 MB, demo database generalized (not judge-specific cluster — that's
still a followup task), "measure" stays a frontend-only pseudo-stage (no new
backend enum value).

What changed — blockers (A1)
- Floating shadow window (`components/shadow-execution-window.tsx`)
  auto-suppresses via `usePathname()` while on
  `/dashboard/migrations/current/shadow`, so the dedicated page's own live
  view is never duplicated on screen.
- Sidebar identity (`components/owner-identity-field.tsx`) now shows the
  Clerk display name/email, raw `user_...` id moved to the `title` tooltip.
- Clerk dev-mode banner: not a code fix — flagged as an ops task (needs a
  Clerk Production instance + verified custom domain before demo day).
- `migration_runs.run_kind` (`standard`/`chaos`/`debug`) added end to end
  (model, migration, service, repository filter, API `exclude_kinds` param);
  Overview "Recent" list and `judge_chaos_checks.py` runs now use it so
  deliberate failure tests stop appearing on the first screen a judge sees.

What changed — correctness (A2)
- `backend/app/memory/metrics.py`: rewrote the accuracy endpoint. `GRADED`
  was already correctly scoped; `ACCEPTED`/`SUCCEEDED` were querying a
  completely different, unrelated population (all runs any owner, via
  `recommendation_outcome.linked_evidence`, near-permanently 0/0). Replaced
  with `migration_success_rate` (% of the same graded population that
  actually passed) and an honest `approval_breakdown` (proceed / accept
  recommended / cancel / awaiting decision — real counts, not a rate). Also
  scoped every query to `owner_identity` when known, matching the Recent
  list's scoping. Found and fixed an unrelated latent bug in the same file:
  the high-risk-flag precision/recall query filtered on
  `outcome_class IN ('failure','partial','timeout')`, but those values never
  existed (`app.grading.engine.classify_outcome` only ever returns
  `clean_ok`/`warned_ok`/`bad`/`timeout`) — only `timeout` was ever matching,
  silently undercounting every non-timeout bad outcome.
- Confidence: raw was already not the headline in current code (that finding
  didn't reproduce — likely a stale screenshot). Added `rawPercentLabel`
  shown alongside the adjusted headline, and moved the four-signal
  adjustment list out of the collapsed "Show details" toggle to sit directly
  under the confidence number.
- Storage grading: added a real `storage_unverifiable` floor (1 MB) to
  `app/grading/engine.py` + `grading.yaml`, mirroring how `duration_unverifiable`
  already handles timeouts — below the floor, storage is graded unverifiable
  instead of a trivial "within band" pass. New `grades.storage_unverifiable`
  column (`storage_within_band` now nullable) via migration `k6f2c9d5e374`.
- Redundant lifecycle steps (Tear down / Torn down): fixed by the Part C
  rebuild below (5-stage rail, not fixed twice).

What changed — database attach flow (Part B)
- `current-migration-workspace.tsx` reordered: connect database first, SQL
  second, prediction third (previously SQL-first). New shared
  `ConnectDatabaseFields` component: single primary read-only-URL input with
  visibly-styled placeholder, ARN moved behind a secondary toggle, copyable
  GRANT/REVOKE help block sourced from `prepare_judge_demo_db.py`'s existing
  role pattern.
- Staged discover progress: extended the same `pipeline_progress` mechanism
  already used for predict — `app/schema_analysis/discovery.py` now takes an
  `on_stage` callback (connecting → authenticating → reading schema → done),
  wired through `SchemaDiscoveryService.discover_and_persist`;
  `/pipeline-progress` route relaxed to also serve progress while
  `status == pending` (previously predict-only).
- Client-side missing-table warning next to the SQL editor
  (`findUnknownTableReferences`, heuristic regex — not a real parser, the
  backend's `missing_referenced_table` policy flag is still authoritative).
- Demo database: un-gated the "Try the demo database" button from
  `NEXT_PUBLIC_ENABLE_DEBUG_TOOLS` — it's now a first-class, always-visible
  affordance on the connect step, clearly labeled "not your data." Backend
  endpoint (`/runs/debug/demo-with-db`) unchanged and was never itself
  debug-gated — it already reads `DEMO_READONLY_DATABASE_URL` /
  `.judge_ro_database_url`, so this works with whatever demo DB is configured.
  **Provisioning an actual standing judge-facing cluster is still open** —
  user said they'll configure that separately.

What changed — shadow live view (Part C), backend
- `app/shadow/job_progress.py` (new): captures the CockroachDB background
  job id via a psycopg3 notice handler on the connection running the DDL
  (fires before the blocking statement returns), then polls `SHOW JOB <id>`
  (never bare `SHOW JOBS`) on a second connection running concurrently.
  Never raises — reports failure via `JobProgressResult.succeeded`/`.error`
  so partial observations survive a migration failure. **Not live-validated
  against a real shadow cluster in this session** (would need a real SFN run)
  — degrades honestly to the existing post-hoc `job_watch` snapshot if the
  notice never arrives, per the "never fabricate progress" rule.
- `app/shadow/schema_snapshot.py` (new): before/after structural snapshots
  of the shadow cluster (write-capable connection, so read-only enforcement
  is intentionally skipped — that check protects the customer's DB, not this
  disposable one) + `build_schema_diff()` (added/removed/changed/unchanged
  per table/column/index/constraint, color-neutral — never implies quality).
- `shadow_clusters` gained `event_log` (JSONB array, appended on every status
  transition and timing merge — real replay history, not last-write-wins),
  `schema_snapshot_before`, `schema_snapshot_after` (migration `k6f2c9d5e374`).
- Wired into both execution paths: `migration_runner.py` (the real
  Step-Functions/Lambda path via `execute_migration.py`) and
  `orchestrator.py._migrate()` (the local/dev fallback path), so both
  capture job progress and schema snapshots the same way.
- `GET /runs/{id}/shadow-cluster/stream` (new, `sse-starlette`): SSE
  endpoint replacing polling for the shadow-cluster row specifically — emits
  on change plus a heartbeat, stops on terminal status or 30-minute ceiling.
  `sync-workflow` (SFN status) is intentionally NOT folded into this stream
  since it's a side-effecting AWS call, not a passive read; frontend keeps a
  separate slower poll for that. `SessionAuthMiddleware` now accepts the
  bearer token via a `?token=` query param on this one route only, since
  browser `EventSource` can't set custom headers.

What changed — shadow live view (Part C), frontend
- New `components/shadow-live-view.tsx` replaces the retired
  `shadow-live-panel.tsx` everywhere (dedicated shadow page, floating window,
  run-detail page, current-migration-workspace inline panel — 4 call sites).
  Three bands: 5-stage lifecycle rail (provision/seed/execute/measure/
  teardown — "measure" is a frontend-only pseudo-stage, current once
  `migrate_ms` is recorded but the cluster hasn't started tearing down),
  stage-dependent center panel (job id/description/`running_status`/
  `fraction_completed` bar when live observations exist, honest "no live
  progress observed" text when they don't — never a fabricated bar), and an
  append-only event log rendered from `shadow_clusters.event_log`.
- New `lib/api/shadow-stream.ts` (`useShadowStream`): SSE client via native
  `EventSource`, auto-reconnects (browser built-in), resolves the Clerk/
  legacy token for the `?token=` param.
- Same component doubles as the replay view for finished runs (`isLive=false`
  falls back to the persisted `shadow` + full event log instead of a live
  connection) — a judge clicking into a past run now sees the same rich view,
  not just static final numbers.
- `mapShadowLiveStages`/`ShadowLiveStage` (6-step mapper) removed, replaced
  by `mapShadowLifecycleRail` (5-step) + `mapExecutePanel` + `mapSchemaDiff`
  + `mapCostStrip` + `mapShadowEventLog` in `lib/api/map-run.ts`.

What was verified
- `npm run typecheck` (tsc --noEmit): 0 errors, both after Workstreams 1-3 and
  again after the full Part C rebuild.
- `npm run lint`: 0 errors; 20 warnings, all matching pre-existing
  `react-hooks/set-state-in-effect` / `react-hooks/purity` patterns already
  present throughout this codebase (not new rigor gaps).
- `python -m pytest tests/unit`: 33/33 pass (one test updated for the new
  `run_kind`/`exclude_kinds` service params).
- `python -c "import app.main"`: clean import with every change applied.
- Migration `k6f2c9d5e374` applied for real against the live dev CockroachDB
  Cloud database (see "known issue" below for how long that took and why).
  Confirmed via direct `information_schema` queries: `migration_runs.run_kind`
  + index, `shadow_clusters.event_log`/`schema_snapshot_before`/
  `schema_snapshot_after`, `grades.storage_unverifiable` +
  `storage_within_band` now nullable — all present. `alembic current` shows
  `k6f2c9d5e374 (head)`.
- Confirmed against the user's own already-running Next dev server (port
  3000, hot-reloaded): landing page 200, `/dashboard` 307 (expected auth
  redirect), no client errors from the reload.

Known issues discovered (not caused by this change, flagged for awareness)
- **CockroachDB schema-change DDL is genuinely slow on this cluster tier** —
  each `ADD COLUMN`/`ALTER COLUMN`/`CREATE INDEX` ran as its own background
  job taking 20–90s. A 6-statement migration took ~4 minutes wall clock.
  `alembic upgrade head` looked "stuck" from the CLI (no per-statement
  progress output) but was actually working — worth keeping in mind for any
  future multi-statement migration; consider a progress-logging wrapper or
  splitting large migrations.
- **Local backend boot is broken on this Windows Python 3.13 install**:
  `psycopg` async mode requires a `SelectorEventLoop`, but neither plain
  `uvicorn app.main:app` nor the project's own documented fix
  (`backend/_run_api.py`'s `asyncio.set_event_loop_policy
  (asyncio.WindowsSelectorEventLoopPolicy())`) actually prevents uvicorn from
  using `ProactorEventLoop` on this specific interpreter — `/health` reports
  `"database":"unhealthy"` with a `ProactorEventLoop` `InterfaceError` even
  through the documented launcher. Direct `psycopg` calls work fine when the
  event loop is set correctly by hand
  (`asyncio.run(..., loop_factory=asyncio.SelectorEventLoop)`), and `alembic`
  (sync driver) is unaffected — this is specifically a Python 3.13 + uvicorn +
  async-psycopg interaction, pre-existing and unrelated to this change. Not
  fixed here (out of scope); next session on this machine should investigate
  whether `_run_api.py`/`_run_api_reload.py` need a `loop="asyncio"` +
  explicit `loop_factory` passed into `uvicorn.run()` rather than relying on
  `set_event_loop_policy` alone, since that mechanism appears insufficient on
  this Python version. Because of this, the SSE endpoint and the full
  Part C job-progress/schema-diff pipeline could **not** be live-exercised
  end to end in this session — verified by code review, type/lint/unit-test
  checks, and direct DB introspection only.

What the next task needs to know
- Provisioning a real standing demo CockroachDB cluster (Part B's remaining
  item) and getting a live shadow run through the new job-progress/schema-diff
  pipeline are the two biggest open verification gaps — both need a working
  local boot (see known issue above) or a deployed environment.
- `docs/ai_audit.md` has the full verification trace (REAL/ALREADY
  FIXED/PARTIALLY RIGHT/WRONG per finding) this change log summarizes.

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
