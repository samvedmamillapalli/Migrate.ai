# UI Audit and Shadow Visualization Spec

Observations from screenshots of the running app, plus the target design for
the shadow execution view. Everything in the Findings section is observed from
the UI, not from code. Verify each against the codebase before acting.

---

## Part A: Findings

### A1. Blockers. Fix before any judge or demo viewer sees this.

**Duplicate floating shadow panel.** The Shadow Execution page renders a
floating "SHADOW VISUALIZATION" card that duplicates the page content almost
line for line, layered on top of it and covering the right side. Two copies of
the same six steps and the same PRED to ACTUAL block are on screen at once.
This reads as a rendering bug. Decide on one surface: either a persistent
floating watcher that follows you across pages, or a full page view, never both
showing the same content simultaneously.

**Clerk development toast.** "You've created your first user! Configure your
application" is visible in every screenshot. This is Clerk's dev mode banner. It
must not appear in the demo build.

**Raw Clerk user ID in the sidebar.** "Owner identity: user_3H7aHu1OSDoMI4iQY13"
is shown with the caption "Scoped to your signed-in account." The raw ID means
nothing to a viewer and looks like leaked internals. Show the display name, keep
the ID available on hover or in a detail view if it is needed for debugging.

**Chaos and test runs on the landing page.** The Recent list shows
`chaos_abort_flag`, `definitely_missing_xyz`, and `idx_customers_region_abort`,
several marked FAILED. These are deliberate failure tests. They belong in a
diagnostics view, not on the first screen a judge sees. Either filter them from
Recent, or tag them visibly as chaos tests so the failures read as intentional
verification rather than a broken product.

### A2. Correctness. These are wrong, not just ugly.

**Accuracy metrics do not reconcile.** Overview reports GRADED 11,
ACCEPTED 9 / 69 at 13 percent, and SUCCEEDED 0 / 0. Meanwhile a completed run
shows Grade 1.000, class clean_ok, success yes. Determine what each denominator
counts, whether corpus entries are leaking into the accuracy sample (they must
not, per the integrity rule), and why succeeded is 0/0 when at least one run
succeeded. Then label each metric so the denominator is self explanatory.

**Confidence shows the raw value, not the adjusted one.** Headline reads 62%.
Body prose reads "0.62 raw, 0.82 adjusted." The locked design is that the model
proposes a raw confidence and deterministic code clamps it using four measurable
signals. The adjusted value is the system's actual confidence. Show the adjusted
number as the headline, show the raw alongside it, and list which of the four
signals fired and in which direction. That reasoning is a differentiator and it
is currently buried in a paragraph.

**Storage measurement may be meaningless at this scale.** A run reports
predicted 0.2 MB against actual 0.0 MB, with the note "small DDL often shows
~0 MB on approximate disk stats." If storage cannot be measured reliably for
small DDL, grading it as within band is generous rather than honest. Consider
marking storage unverifiable below a measurement floor, the same way a timeout
makes duration unverifiable rather than a pass.

**Redundant lifecycle steps.** Step 5 "Tear down cluster" and step 6 "Torn down"
are the same event, one as an action and one as its completion. Every other step
already carries a status. Collapse to five steps.

### A3. Density. Real content, badly presented.

The Assessment panel renders two long prose blocks back to back, the second
running well over two hundred words, in a narrow left column with the entire
right half of the screen empty. Retrieved memory cards have the same problem.
The content is good. Nobody will read it in this form.

---

## Part B: the database attach flow

### B1. What it looks like now

The Current Migration page presents the migration SQL first, then a section
labeled "2. ATTACH YOUR DATABASE" containing two competing inputs, a read only
database URL and a Secrets Manager ARN, followed by a Discover schema button.
Below it, "3. PREDICTION" reads "Attach and discover schema first."

### B2. Why this is the hardest part of the product to get through

To use this app a person must produce a read only connection string to a
database that already contains the tables their migration references. That is a
significant amount of setup, and the UI currently offers no help with any of it.
Specific problems:

1. **Two inputs, no guidance.** Nothing explains when to use the URL versus the
   ARN, or which is preferred. Two paths to one outcome, presented as equals.
2. **Placeholder text reads as a real value.** The URL field shows a complete,
   plausible looking connection string. It is not obvious it is a placeholder.
3. **No escape hatch.** There is no demo or sample database option. A judge with
   no CockroachDB instance of their own cannot get past this screen. This is the
   single highest impact gap in the entire product.
4. **No connection test.** Discover either works or does not. There is no
   intermediate step that says the credentials are valid and read only.
5. **No help creating a read only user.** The product asserts production is
   never written, but does not help the user create the credential that
   guarantees it.
6. **Ordering is backwards.** SQL is presented before the database. The schema
   is the context that makes the migration meaningful, and prediction cannot run
   without it. The database should come first.
7. **Section numbering is inconsistent.** The migration section carries no
   number while the following sections are numbered 2 and 3.

### B3. Target flow

Reorder to: connect, then discover, then write the migration, then predict.

**Step 1, connect.** One primary input, not two. Default to the read only
connection URL, since that is what most people will have. Offer the Secrets
Manager ARN behind a secondary control labeled as the option for a credential
already stored in AWS. Placeholder text must be visibly a placeholder.

Beside the input, a short expandable block: how to create a read only user, with
the exact GRANT statements to copy. This converts the biggest friction point
into a solved problem instead of an obstacle.

**A demo database option, prominent and always available.** A single button that
connects to a prepared database with a realistic schema and enough rows for a
measurable migration. This is not a shortcut for lazy users, it is the path
every judge will take. Label it clearly as the demo database so nobody mistakes
it for their own.

**Step 2, discover.** On submit, show progress rather than a spinner: connecting,
authenticating, reading schema, done. Then render the discovered schema, tables
with row counts, column types, indexes, and approximate sizes. Distinguish three
failure modes with distinct actionable messages: credentials rejected, host
unreachable, and connected but permissions insufficient.

The discovered schema is also the left side of the shadow diff. Build it once,
use it twice.

**Step 3, migration SQL.** Now that tables are known, the editor can reference
them. At minimum, list the discovered table names next to the editor. Flag when
the SQL references a table that discovery did not find, since that is a
guaranteed failure and currently only surfaces after a full run.

**Step 4, predict.** Unlocks only when both a schema and SQL exist.

---

## Part C: shadow execution, target design

### C1. What the timings actually are

A recorded complete run: provision 4.2s, cluster ready 8.2s, seed 11.8s,
execute 2.4s, teardown 3.5s, torn down 3.5s. Roughly 33 seconds total.

Two consequences. First, the whole run is watchable in real time, so no
compression or replay trickery is needed for a demo. Second, the most important
moment, the migration actually executing, is 2.4 seconds inside a 33 second
window. If the view treats all six steps equally, the payload moment vanishes.

### C2. What CockroachDB gives you that you are not using

CockroachDB runs schema changes as background jobs. As soon as a DDL statement
is accepted, the database returns a notice containing the background job ID.
That job exposes:

- `running_status`, a human readable string. A real captured example during an
  ADD COLUMN NOT NULL DEFAULT reads `populating schema`.
- `fraction_completed`, a float updated from 0.0 to 1.0 while the job runs,
  always 1.0 on success.
- `status`, `description` (the DDL echoed back), `error`.

This is the database narrating its own work. It is the strongest possible
content for a live view because none of it is invented.

Caveat: bare `SHOW JOBS` has been reported to take over 30 seconds to return
while an add or drop column schema change is active, which is exactly the moment
you need it. Capture the job ID from the notice and poll `SHOW JOB <id>` for
that specific job. Never poll bare `SHOW JOBS` during execution.

### C3. Layout

One surface, not two. Three horizontal bands.

**Band 1, the lifecycle rail.** Five stages: provision, seed, execute, measure,
teardown. Always visible. Completed stages show real elapsed duration. The
active stage shows a counter ticking client side between polls so it reads as
live at any polling interval. This band is the map and it does not change shape.

**Band 2, the stage.** The content here changes depending on which stage is
active. This is the central idea. Do not build one static panel with a spinner
over it.

- Provisioning: cluster identity materializing. Name, region, tier, provider,
  each appearing as it becomes known.
- Seed: tables appear one by one, then row counters tick up per table. This is
  where the left side of the diff gets built, live. Label rows as synthetic and
  tier capped at the moment the number first appears, not in a footnote.
- Execute: the job panel. Job ID, the DDL echoed back by CockroachDB, the live
  `running_status` string, and a bar driven by `fraction_completed`. Give this
  stage more visual weight than the others, because 2.4 seconds needs help to
  register.
- Measure: the right side of the diff resolves against the left.
- Teardown: cluster identity dissolves, ending on an explicit statement that the
  cluster no longer exists, with its total lifetime.

**Band 3, the event log.** Append only, timestamped, monospace. Every poll that
yields new information appends a line. This band never stops producing output,
which is what prevents any stage from feeling frozen. It is also the artifact
an engineer judge will read to decide whether this is real, and it screenshots
better than anything else in the product.

### C4. The schema diff

Left is the schema before, right is after, from real captured snapshots of the
shadow cluster.

Colour means structural change, not quality. A migration usually does not
improve anything, so green must not mean better:

- green, added: column, index, constraint
- red, removed
- amber, changed in place: type, nullability
- grey, untouched, so the change reads at a glance

Beneath the diff, a measured cost strip: duration, storage delta, jobs run,
success or failure, timed out or not. That strip is the blast radius definition
made visible.

Honesty split, stated in the UI:

- Schema shape changes are real and match what would happen to the user's
  production database.
- Row counts and duration are shadow tier measurements, not production scale.

### C5. Polling

Adaptive by stage, because the stages move at different speeds.

- provision and seed: every 2 to 3 seconds
- execute: every 1 second, because `fraction_completed` actually moves
- elapsed counters tick client side between polls
- back off after the first minute, hard stop on terminal status, hard stop at a
  ceiling past the longest configured timeout, cancel on unmount

### C6. Two rules

**Never a bare spinner.** Every waiting state names the specific current action
and shows elapsed time. "Provisioning cluster, 4s" is both better UX and more
truthful than a rotating circle.

**Never fabricate progress.** If `fraction_completed` is unavailable for a given
job type, show `running_status` alone and no bar. An invented progress bar in a
product whose entire pitch is measured truth is the single worst detail a judge
could notice.

### C7. Persist every polled state

Write each polled state to the run record. A completed run can then be replayed
from stored data, clearly labeled as a replay of a real recorded run. This makes
finished runs as informative as live ones, which matters because a judge
clicking into a past run currently sees only a static result.

---
---

# Verification Report + Combined Build Plan (added 2026-07-28)

This section was produced by reading the actual code against every finding
above, plus folding in an earlier planning pass (`docs/SHADOW_LIVE_REPRESENTATION_PLAN.md`)
that researched external live-dashboard/migration-UX patterns (SSE vs polling,
CockroachDB's own Jobs page conventions, Neon/PlanetScale ephemeral-branch UX,
gh-ost/Bytebase/Atlas precedent). Nothing below has been implemented. Every
finding was checked against real code, file:line evidence is cited throughout,
and every place the two source documents disagree is called out explicitly
rather than resolved silently, per instruction.

`docs/backendfix.md` holds the locked architectural decisions and must be
treated as authoritative for anything not re-litigated here — one stale line in
it is flagged in §0 below.

## 0. A locked-decision conflict found during investigation (flag before anything else)

`docs/backendfix.md` — "Identity and auth" — states **"No real authentication.
No Clerk."** This is stale. The frontend has fully live Clerk auth wired:
`app/layout.tsx:21-39` (`ClerkProvider`), `app/dashboard/layout.tsx:11,19-22`,
`@clerk/nextjs@^6.39.6` in `package.json`. This isn't a hypothetical — it's the
direct cause of two of the A1 blockers (the dev-mode toast and the raw Clerk
user ID in the sidebar, see §1 below). `backendfix.md` needs its "Identity and
auth" section corrected to reflect that Clerk is real and in use before the
next task reads it and gets misled. Not fixed here since this pass is
plan-only; flagged so the next work session updates the doc, not the code.

## 1. Verification results — Part A

| # | Finding | Verdict | Evidence |
|---|---|---|---|
| A1.1 | Duplicate floating shadow panel | **REAL** | `app/dashboard/layout.tsx:35` mounts `<ShadowExecutionWindow/>` unconditionally on every dashboard route, including the dedicated shadow page. `shadow-execution-window.tsx` has no `usePathname()` check — its only visibility gate is `open`/`runId` from `shadow-watch-context.tsx`, persisted to `localStorage` so it survives navigation. Both the floating window and the dedicated page (`app/dashboard/migrations/current/shadow/page.tsx:467-474` vs `shadow-execution-window.tsx:258-268`) render the identical `<ShadowLivePanel>` from the same data. The dedicated page's own "Start shadow test" / "Watch live" buttons call `openWatch()`, which is what triggers the duplicate. |
| A1.2 | Clerk development toast | **REAL, not app-controllable** | Standard `ClerkProvider` with no suppression prop exists in Clerk's API for this banner — it's inherent to any Clerk **development-instance** key (`pk_test_...`). Only fix is a Clerk **Production** instance, which requires a verified custom domain. This is an infra/ops item, not a code change. |
| A1.3 | Raw Clerk user ID in sidebar | **REAL** | `components/owner-identity-field.tsx:24-29,42-45,57-58` — when Clerk-locked, the field's `value` is set directly to `userId` (`user_...`) and rendered read-only with caption `"Scoped to your signed-in account (Clerk user id)."` No display-name substitution, no hover-to-reveal. Mounted in the sidebar footer at `components/app-sidebar.tsx:88`. |
| A1.4 | Chaos/test runs unfiltered on landing Recent list | **REAL** | `app/dashboard/page.tsx:99-104` — `listRuns({limit:5, owner_identity})` is the only filter, and only applied if an owner happens to be set. **No mechanism exists anywhere to distinguish a chaos/test run from a real one** — `backend/app/database/models/migration_run.py` has no tag/kind/is_chaos column at all. This isn't a filtering-logic bug, it's a missing data model field. |
| A2.5 | Accuracy metrics do not reconcile | **REAL — and it's a query/data-scope bug, not a display bug** | See §2 for the full trace; summary: `GRADED` (11) is a correctly-scoped, corpus-excluded query (`memory/metrics.py:51-69`, `_GRADE_OK` predicate correctly checks `grade_summary.integrity.kind`). `ACCEPTED`/`SUCCEEDED` (9/69, 0/0) come from a **completely different, unrelated query** (`metrics.py:96-125`) over *all runs from all owners*, joined through `approvals`/`recommendation_outcome.linked_evidence` — a field that has nothing to do with grade or execution success and is legitimately almost always empty. Three unrelated populations are shown under one "Accuracy" heading with generic labels as if they share a denominator. |
| A2.6 | Confidence shows raw as headline | **ALREADY FIXED at the headline, target design only half-satisfied** | `lib/api/map-run.ts:401-426` (`mapConfidence`) — `percentLabel` is built from `confidence_score` (the **adjusted** value), not `raw_confidence_score`. The only render site (`current-migration-workspace.tsx:465-467`) shows `percentLabel`. No component anywhere renders the raw value as prose — the audit's literal screenshot claim ("0.62 raw, 0.82 adjusted" in body text) doesn't reproduce against current code, so it was likely captured from an older build. What the locked design still asks for and current code doesn't do: show raw **alongside** the adjusted headline (currently raw is computed but never rendered anywhere), and the four-signal adjustment list exists correctly (`adjustments[]` with `reasonCode`/`reason`/`amount`) but is behind a collapsed "Show details" toggle rather than adjacent to the headline as a differentiator. |
| A2.7 | Storage measurement may be meaningless at small scale | **REAL, exact match, no floor logic exists** | `backend/app/grading/engine.py` — duration has an explicit `duration_unverifiable = timed_out` concept (scored 0 rather than credited when true). **Storage has no equivalent field anywhere in `NumericGradeResult`.** `grading.yaml`'s `small` tier `storage.max_abs_mb: 32.0` means a 0.2 MB vs 0.0 MB delta trivially "passes" for any small-DDL prediction, regardless of whether the underlying disk-stat measurement can even resolve sub-MB deltas. The frontend already *knows* this is likely noise (`map-run.ts:1045-1048` has a special-cased string for `actualMb === 0`) but still reports it as graded "OK" — confirming the fix belongs in `grading/engine.py`, not the display layer. |
| A2.8 | Redundant lifecycle steps (Tear down / Torn down) | **REAL** | `lib/api/map-run.ts` `mapShadowLiveStages` — `destroying` and `destroyed` pull their duration label from the **identical** `timingKeys` list (`["teardown_ms","cleanup_ms","teardown","cleanup"]`, lines 722-723), and the moment `status` flips to `"destroyed"`, every stage (not just step 6) flips to `"complete"` simultaneously (line 780). The only thing distinguishing the two steps is static hint text — no independently measured data separates them. |
| A3 | Assessment panel density | **REAL** | `current-migration-workspace.tsx` — `AssessmentPanel`/`RetrievalPanel` sit in a single-column full-width `Section` (page wrapper has no `grid-cols-2` anywhere, `:1140`). The two prose blocks are individually capped at `max-w-2xl` (~672px) and stacked with nothing placed beside them (`:491`, `:505`) — the empty space is a real layout gap, not a rendering illusion. |

## 2. Accuracy metric deep trace (the most important finding)

`GET /runs/metrics/accuracy` → `backend/app/api/routes/runs.py:100-105` →
`fetch_accuracy_metrics()` in `backend/app/memory/metrics.py`.

- **GRADED (11)** — `scalar_accuracy_trend` (`metrics.py:51-69`): joins `grades` →
  `migration_runs`, filtered by `_GRADE_OK` (`metrics.py:28-49`), which
  correctly excludes corpus rows via a correlated subquery into
  `migration_memories.grade_summary->'integrity'->>'kind'` against
  `'open_source_documented_incident'` / `'synthetic_seed'`. **This part
  correctly honors the integrity rule at the SQL layer.**
- **ACCEPTED (9/69, 13%)** — a *different* subquery (`metrics.py:96-125`,
  `recommendation`): `LEFT JOIN approvals`, **no `_GRADE_OK` filter, no owner
  scoping, no join to `grades` at all**. The denominator (69) is "every
  migration run in the whole database, any owner, any status, that ever got a
  recommendation" — including chaos/test runs and other owners' runs. Corpus
  rows specifically do *not* leak in here (corpus seeding never sets the
  `recommendation` column — `memory/open_source_corpus.py:370-383`), but the
  query is still the wrong population: it isn't "graded," it's "recommended,"
  a strictly larger and unrelated set.
- **SUCCEEDED (0/0)** — same `recommendation` subquery, counting
  `recommendation_outcome.linked_evidence.status == 'success'`
  (`metrics.py:108-113`). This field tracks whether a **later, separate,
  explicitly-linked follow-up run** (re-attempting a recommended strategy)
  succeeded — it has no relationship to `grade.outcome_class` or
  `execution_result.success`, the fields that make an individual run show
  "Grade 1.000, success yes." Nothing in the current demo path
  (predict→shadow→grade→memory) ever populates `linked_evidence`, so 0/0 is
  legitimate for that field — it's just the wrong field to be labeling
  "Succeeded" on an Overview page.
- **One more bug not in the original audit:** `GET /runs/metrics/accuracy`
  takes **no `owner_identity` parameter at all** (`runs.py:100-105`), while the
  "Recent" list on the same page *is* owner-scoped. The Accuracy section is
  silently global/cross-owner next to a per-owner list, with no visual
  indication they're different scopes.

**Where the fix belongs:** the query/aggregation logic first (rescope
`accepted` to the same graded, corpus-excluded, owner-scoped population as
`GRADED`, or stop presenting it as related to accuracy at all), and only
secondarily the labels once the underlying numbers mean something coherent.
See §6 open question on how "Succeeded" should be redefined.

## 3. Verification results — Part B (database attach flow)

**B1/B2 ordering and numbering claims — REAL, confirmed literally.**
`current-migration-workspace.tsx:1237` labels the SQL section `"1. Your
migration SQL"` in the empty state; once a run exists, `:1299` renders
`Section title="Migration"` (**no number**) followed by `:1306` `Section
title="2. Attach your database"` then `"3. Prediction"`. SQL genuinely renders
before the DB section in both states.

**Two competing inputs, no guidance — REAL.** `:1332-1350` (URL field,
plausible-looking placeholder `postgresql://readonly@host:26257/mydb?...`) and
`:1352-1367` (ARN field, labeled just `"Or secret"`) sit side by side under one
submit button with no stated preference order. `handleDiscover` (`:918-957`)
only validates that *at least one* is non-empty (`:924-928`); nothing prefers
URL over ARN except accidental precedence in the backend handler (see below).
No read-only-user help text exists anywhere near this form.

**No connection test, opaque single call — REAL.** `handleDiscover` sets one
static status string (`"Discovering schema (read-only)…"`) and awaits one HTTP
call. There is no `/test-connection` endpoint. Notably, **predict already has
the staged-progress treatment this page needs** — `getPipelineProgress` polls
every 400ms during predict (`:959-991`) — so the pattern to copy for discover
already exists and is proven, it just wasn't applied here.

**"Attach and discover schema first." gating text — confirmed verbatim**
(`:1467-1472`), exactly as screenshotted.

**Three distinct failure messages — MOSTLY ALREADY BUILT, spec undersold
this.** The backend already has 7 distinct, precisely-triggered error paths —
401 (bad credentials), 403 (writable credentials / not read-only), 404
(database not found), 408 (timeout), 400 (SSL / bad connection string), 503
(host unreachable), 422 (malformed request) — each raised as its own `AppError`
subclass (`backend/app/schema_analysis/errors.py`, `read_only.py`) and **already
mapped to distinct frontend copy** via `discoverErrorHint`
(`lib/api/map-run.ts:1109-1132`). **What's actually missing is the staged
progress UI (connecting → authenticating → reading schema → done), not error
differentiation** — the errors are already good, they're just delivered as a
single opaque failure at the end of one spinner instead of a step that lit up
red.

**Discover response is already rich — worth noting for planning.** The backend
already returns full schema metadata per table: row counts, column types (with
UDT/precision), indexes (with definitions), constraints, and approximate sizes
(`backend/app/schema_analysis/models.py`, `DatabaseMetadata`/`TableMetadata`).
Building B3's Step 2 ("render tables, row counts, column types, indexes,
approximate sizes") is a frontend rendering task against data that already
exists — not a backend gap.

## 3a. The demo database — investigated in depth (highest priority item)

**The mechanics already exist; the gap is entirely operational/deployment,
and it's a deliberate decision, not an oversight.**

- `backend/scripts/prepare_judge_demo_db.py` already does the real work: creates
  an idempotent read-only role `judge_ro` (SELECT-only, explicit
  INSERT/UPDATE/DELETE/CREATE revokes), creates/seeds a `customers` table to
  ~5000 rows, and prints a ready-to-use read-only connection URL. This is
  exactly the GRANT-statement logic B3 wants surfaced as copyable help text.
- `POST /runs/debug/demo-with-db` (`runs.py:108-154`) already reads
  `DEMO_READONLY_DATABASE_URL` (env var, production-ready) or falls back to a
  local gitignored file, creates a run with a hardcoded sample migration, and
  runs **real** discovery against it — not a stub.
- `handleDemoWithDb` in the frontend already wires this end to end.
- **But**: both the backend endpoint's UI entry point and the fake-migration
  entry point are gated behind `NEXT_PUBLIC_ENABLE_DEBUG_TOOLS`, and
  `demo/DEMO_DAY.md:28` / `demo/DEPLOY_CHECKLIST.md:21` **explicitly instruct
  operators to leave this flag off on the judge-facing deployment**. There is
  also **no standing, checked-in, shared CockroachDB Cloud cluster or
  credential anywhere** — `customer_demo` in `backendfix.md`'s walkthrough log
  was an ad hoc database inside whichever cluster the operator's `DATABASE_URL`
  happened to point to during one specific 2026-07-25 session, produced by a
  script that must be rerun for it to exist again.
- No docker-compose, no seed-SQL fixture, no local-container path exists as an
  alternative (`Glob` for `docker-compose*.yml` — zero matches).

**Confirms the audit's claim exactly:** a judge with no CockroachDB instance
cannot get past the first screen, by explicit configuration choice on the
current deployment path, not because the capability doesn't exist.

**Smallest honest implementation** (what would need to be built, since the
hard parts already exist):
1. Provision one always-on CockroachDB Serverless (free-tier fits the
   project's existing cost-consciousness — `SHADOW_MAX_CONCURRENT=2` etc.)
   cluster using `prepare_judge_demo_db.py`'s exact role/table pattern —
   possibly widened to 2-3 tables so discovery output reads as more real.
2. Set `DEMO_READONLY_DATABASE_URL` as durable config on the judge-facing
   deployment (the code path for this already exists, it's just never been
   populated there).
3. Give the demo-database button its **own always-visible surface**, clearly
   labeled "Demo database — not your data," separate from the actual
   `NEXT_PUBLIC_ENABLE_DEBUG_TOOLS`-gated developer tools panel it currently
   lives inside.
4. Decouple the endpoint from its hardcoded sample migration so clicking it
   lands the user at "connected + discovered, SQL editor empty" — fitting
   B3's connect → discover → write SQL → predict order — rather than
   pre-filling a canned migration for them.

## 4. Verification results — Part C (5 investigation questions)

**Q1 — Schema before/after snapshots: NO.** Only a scalar storage-byte delta is
measured (`crdb_internal.table_span_stats`, called twice —
`shadow/orchestrator.py:105,112`, `migration_runner.py:76-78,115-119`). A real
structural comparator exists (`shadow/schema_compare.py`, `compare_snapshots`)
but it's used exactly once, to verify the **seed load matches the pre-migration
expected snapshot** — never to diff the shadow cluster's shape *after* the
migration runs. **This is the single fact that determines Task 3 is backend
plus frontend, confirmed**: the diff panel in C4 needs new introspection calls
both before and after `_migrate()`, plus new fields to persist them, none of
which exist today.

**Q2 — Job ID capture at execution time: NO.** Migration SQL is executed via
plain `await conn.execute(text(statement))`
(`orchestrator.py:216`, `migration_runner.py:87`) with no notice inspection
anywhere in the repo (a repo-wide grep for `notice`/`NOTICE` returns zero
functional hits). `job_watch.py`'s `snapshot_schema_jobs()` runs strictly
*after* the migration transaction has already resolved and has no link between
"which DDL statement" and "which job."

**Q3 — job_watch mechanics, precisely.** `snapshot_schema_jobs()`
(`shadow/job_watch.py:24-44`) runs:
```sql
SELECT job_id::string, job_type, status, description, created::string
FROM [SHOW JOBS]
WHERE job_type IN ('SCHEMA CHANGE','NEW SCHEMA CHANGE','CREATE INDEX','ALTER TABLE')
ORDER BY created DESC LIMIT 10
```
— a single bare snapshot, called exactly once per `run_migration()`, always
*after* the migration has already succeeded or failed. `mcp_tool_attribution()`
returns a static, hardcoded narrative string (not dynamic per-run telemetry).
**No targeted `SHOW JOB <id>` polling exists anywhere in the repo** — confirmed
by direct grep. Everything the live view would need for C2/C3's "execute"
panel (job ID, live `running_status`, `fraction_completed`) has to be built
from scratch.

**Q4 — pipeline-progress: predict-stage-only, in-memory, not reusable
as-is.** `GET /runs/{id}/pipeline-progress` (`runs.py:246-278`) is hard-gated
to `MigrationRunStatus.PREDICTING` and force-clears otherwise. Storage is a
**process-local Python dict** (`pipeline_progress.py:13`), not the database —
meaning it cannot be written to from the Step-Functions Lambdas at all (they're
separate processes/invocations). The one code path that incidentally emits
shadow-stage-shaped progress (`local_shadow_verify_service.py`, the dev-only
in-process shortcut) is invisible to the endpoint anyway because it flips
`run.status` to `RUNNING` before writing progress, and `RUNNING != PREDICTING`
triggers the clear. **A shadow-execution lifecycle rail needs a new,
DB-persisted, Lambda-writable mechanism — this cannot be extended, it has to be
built alongside.**

**Q5 — Persistence of polled states: NO, last-write-wins.** `status` is a
single mutable enum column (`transition()`,
`shadow_cluster_service.py:128-159`, overwrites in place — the prior value only
survives as an ephemeral log line, not queryable state). `stage_timings`
supports a **shallow top-level-key merge** (`merge_timings()`,
`shadow_cluster_service.py:176-187` — different stages contribute disjoint
keys and coexist) but is **not** an append-only log: nested values like
`job_watch`'s array are fully replaced on write, not appended. No events table,
no JSONB array-of-observations, exists anywhere for this entity. **C7's
"persist every polled state for replay" requires a genuinely new data
structure** (new table or an array-shaped JSONB column) plus new write paths in
every Lambda handler and the orchestrator — not a tweak to the existing model.

### A technical wrinkle Q1/Q2 surface that the spec doesn't address

CockroachDB schema-change DDL statements block the initiating SQL connection
until the job completes — the statement doesn't return early. That means:
capturing the job ID via a notice callback and then polling `SHOW JOB <id>`
"while execution is happening" requires a **second, concurrent database
connection** (or an async task) running alongside the one that's blocked on the
DDL statement, since a single synchronous connection can't run two queries at
once. This is a real architecture addition to the `ExecuteMigration` Lambda
(open a polling connection, capture the job ID off a notice handler on the
primary connection as early as possible, poll the secondary connection until
the primary's statement returns), not a minor code change. Flagged as a spike
item in the build plan below (§5, Phase C-1) rather than assumed solved.

Separately: the recorded example run shows a 2.4-second execute stage. At a
1-second poll interval that's at most 2-3 observable samples — real, but thin.
The job panel's static content (job ID, echoed DDL, `running_status` string)
will likely carry more of the "this is real" weight than a smoothly animating
`fraction_completed` bar at shadow-tier row counts. Worth setting expectations
accordingly rather than promising a rich animated progress fill.

## 5. Combined design direction for Part C (spec + earlier plan)

`docs/SHADOW_LIVE_REPRESENTATION_PLAN.md` (written earlier this session, before
this spec existed) proposed 7 independent directions (A–G): SSE transport,
typed stage-timing contract, job-level `fraction_completed` progress, queue/
admission visibility, diff pairing, a fleet/history view, and ephemerality
framing. The spec in Part C above is far more specific on layout (3-band:
lifecycle rail / stage-dependent center panel / event log), on the CockroachDB
job mechanics (targeted `SHOW JOB <id>`, never bare `SHOW JOBS` mid-run), on
color semantics for the diff, and adds one idea the earlier plan didn't have at
all: **C7, full replay of a finished run from persisted poll history.**

Per instruction, taking the more specific of the two wherever they overlap:

| Topic | Earlier plan (A-G) | Spec (Part C) | Resolution |
|---|---|---|---|
| Typed stage timings | Direction B: typed contract | Implied by C3/C4 needing real fields | **Spec wins on shape** (5-stage rail: provision/seed/execute/measure/teardown), but the underlying typed-contract work from Direction B is still the correct implementation approach — adopt B's *mechanism*, spec's *stage names*. |
| Job-level progress | Direction C: surface `fraction_completed` | C2/C3 execute panel: job ID, `running_status`, `fraction_completed` bar | **Spec is far more specific and CockroachDB-native** (targeted `SHOW JOB <id>`, notice-based ID capture) — adopt spec wholesale, Direction C was a lighter sketch of the same idea. |
| Schema diff | Direction E: pair live view with a diff | C4: full before/after diff with structural color semantics + honesty split | **Spec wins**, much more developed (color meaning, honesty framing). |
| Ephemerality framing | Direction G: explicit "cluster no longer exists" copy | C3 teardown band: "ending on an explicit statement that the cluster no longer exists, with its total lifetime" | **Same idea, spec's wording is fine to use directly.** |
| Replay/persistence | Not present | C7: persist every polled state, replay finished runs | **Spec-only, adopt as-is** — this is a genuinely new, good idea. |
| Queue/admission visibility | Direction D: show "waiting for a shadow-cluster slot" | Not addressed | **Earlier plan-only.** Cheap (concurrency cap already exists server-side via `shadow/concurrency.py`, just invisible client-side) — fold in as a small addition to the lifecycle rail's "provision" stage rather than a new band. |
| Fleet/history view | Direction F: cross-run admin page | Not addressed | **Earlier plan-only, and lower priority than everything else here** — recommend explicitly deferring past this build given the Aug 18 deadline noted in `backendfix.md`. |
| **Transport (polling vs push)** | Direction A: move to SSE, cited external research (SSE is the standard recommendation for one-directional dashboard/log-tail updates over polling) | C5: explicit **adaptive REST polling** with concrete per-stage intervals (2-3s provision/seed, 1s execute), elapsed counters ticking client-side between polls, backoff/ceiling rules | **This is a real conflict, not resolved here — see §6 Q1.** The spec was clearly designed assuming polling continues (it prescribes exact intervals); adopting SSE would make those interval numbers moot (replaced by "coalesce push events at roughly this rate" instead of "poll at this rate"). Both are legitimate; picking one changes the shape of Phase C-3/C-4 in the build plan below. |

## 6. Build plan, ordered by what unblocks the most

Nothing below is being executed now — this is sequencing for when you say go.

**Workstream 1 — Blockers, no backend changes needed except where noted (A1).**
Highest visibility-to-effort ratio; do this first regardless of what else gets
picked.
- Resolve duplicate floating panel: default proposal is to make the floating
  window auto-suppress (or auto-minimize to a pill) while `usePathname()`
  matches the dedicated shadow page, so it remains a genuine cross-page
  "something is running" indicator elsewhere but never duplicates the full
  panel content on the page that already shows it. Needs your confirmation —
  see §7 Q2, since the spec frames this as "choose one surface," which could
  also mean removing the floating window entirely in favor of the full page
  only.
- Swap the sidebar identity field to show a Clerk display name /
  email (`useUser()` already available via Clerk) with the raw ID moved to a
  tooltip or a details view. Frontend-only, low risk.
  Clerk dev-mode toast: not a code fix — needs a Production Clerk instance +
  verified custom domain before demo day. Flagging as an ops task, not
  scheduling engineering time against it here.
- Chaos-run filtering: needs a real schema field (see §7 Q3) before it can be
  done properly — sequence this after a "yes, add the column" decision, don't
  try to hack a name-pattern filter as a permanent fix.

**Workstream 2 — Correctness fixes (A2), backend-first.**
- Accuracy metrics: rescope the `recommendation` query in `memory/metrics.py`
  to the same owner + `_GRADE_OK`-equivalent population as `GRADED`, or stop
  presenting `accepted`/`succeeded` as accuracy-adjacent at all. Needs the
  redefinition decision in §7 Q1 before writing the query.
- Confidence: show raw alongside adjusted (small `map-run.ts` +
  `current-migration-workspace.tsx` change), consider promoting the four-signal
  adjustment list out of the collapsed "Show details" toggle since
  `backendfix.md` calls this reasoning "a differentiator."
- Storage unverifiable floor: mirror `duration_unverifiable` in
  `grading/engine.py` + `grading.yaml`. Needs a threshold decision (§7 Q4).
- Redundant lifecycle steps: fold into Workstream 4 rather than fixing twice —
  the spec's Part C already redesigns the lifecycle rail down to 5 stages, so
  fixing this in `mapShadowLiveStages` today and then rebuilding the same rail
  for Part C shortly after would be wasted motion. Do this as the first step of
  Workstream 4 instead.

**Workstream 3 — Database attach flow + demo database (Part B).**
Second-highest priority after Workstream 1 given "highest impact gap in the
entire product" framing.
- Reorder `current-migration-workspace.tsx` sections: connect → discover →
  write SQL → predict.
- Single primary input (URL) + ARN as a secondary/expandable option; visibly
  distinct placeholder styling; copyable GRANT block sourced from
  `prepare_judge_demo_db.py`'s existing role logic.
- Staged discover progress: extend the *same* `pipeline_progress` mechanism
  already proven for predict — instrument `SchemaDiscoveryService` with
  `set_progress` calls at connect/authenticate/read-schema/done, and relax the
  route's hard status gate to also serve progress during discovery (currently
  gated to `PREDICTING` only).
- Client-side check flagging SQL that references tables discovery didn't find
  (static string/name match against `schema_snapshot.tables`, surfaced next to
  the SQL editor — the backend's `missing_referenced_table` policy flag already
  exists but only fires after a full predict run; this is a earlier, cheaper
  frontend-only warning on top of it).
- Demo database: provision the standing cluster, wire
  `DEMO_READONLY_DATABASE_URL` into the judge-facing deployment, un-gate a
  dedicated "Demo database" affordance from `NEXT_PUBLIC_ENABLE_DEBUG_TOOLS`,
  decouple from the hardcoded sample migration. Needs the ownership/cost
  decision in §7 Q5.

**Workstream 4 — Shadow execution live view (Part C).** Largest workstream,
phase it rather than one big change:
- **Phase C-0 (spike, do this before committing UI work):** confirm the
  notice-handler-based job ID capture actually works against this app's DB
  driver while the DDL connection is blocked, and sanity-check
  `fraction_completed` actually reports meaningfully for the specific DDL types
  this app's grading corpus runs (ADD COLUMN, CREATE INDEX, etc.) at shadow-tier
  row counts. This determines whether C2's execute panel can be built as
  specified or needs a fallback (running_status text only, no bar — which C6
  already allows for).
- **Phase C-1 (backend):** capture job ID at execution time; build targeted
  `SHOW JOB <id>` polling (new concurrent-connection pattern in the
  `ExecuteMigration` Lambda, per the wrinkle in §4).
- **Phase C-2 (backend):** before/after schema-shape snapshots around
  `_migrate()`, persisted for the diff panel.
- **Phase C-3 (backend):** replace the in-memory `pipeline_progress` mechanism
  with something DB-persisted and Lambda-writable for shadow stages; this is
  also where C7's append-only replay log gets built (new table or JSONB
  array column) — do these together since they're the same underlying "durable
  event stream" problem.
- **Phase C-4 (transport decision, blocks C-3's exact shape):** resolve the
  SSE-vs-polling conflict from §5 before finalizing how C-3 delivers updates to
  the frontend.
- **Phase C-5 (frontend):** the 3-band layout — lifecycle rail (5 stages,
  folding in the A2.8 fix and the queue/admission visibility idea from §5),
  stage-dependent center panel, append-only event log, schema diff with color
  semantics, measured cost strip, elapsed-time ticking, honesty labels. Resolve
  the duplicate floating panel here too if not already done in Workstream 1.
- **Phase C-6 (frontend):** replay view for finished runs, built once C-1/C-3
  persistence exists.

## 7. Ambiguities and proposed defaults — need your answers

1. **Transport: SSE or continued adaptive polling for the shadow live view?**
   This is the one place the spec and the earlier plan genuinely conflict (§5).
   My default lean: adopt SSE (`sse-starlette`, no new infra, small backend
   dependency) since it removes the need to hand-tune per-stage polling
   intervals and is the standard recommendation for this exact
   one-directional-dashboard use case — but the spec was clearly designed
   around polling and you may prefer to keep one less moving part for a
   hackathon deadline. **Your call.**
2. **Floating panel: suppress-on-dedicated-page, or remove one surface
   entirely?** Proposed default: keep both but auto-suppress the floating one
   while on the dedicated page (§6 Workstream 1). If you'd rather have only
   ever one surface (e.g. kill the floating window, rely on a lightweight
   nav-badge instead), say so — it's a smaller change.
3. **Chaos-run tagging:** add a real `run_kind`/`is_chaos` field to
   `migration_runs` (schema change, small) so Recent can filter correctly and
   permanently, vs. a cheaper but fragile name-pattern filter. Recommend the
   schema field. **Confirm.**
4. **"Succeeded" accuracy metric redefinition:** should it become "graded
   runs with `outcome_class = success` / total graded" (same population as
   `GRADED`, always has real numbers, matches what a judge would intuitively
   expect "Succeeded" to mean), or should the recommendation-linkage metric be
   kept but relabeled to something like "Recommendation follow-through" and
   moved out of the primary Accuracy card since it measures something
   different? **Recommend the first option** — it's simpler and immediately
   meaningful — but this is a product framing choice, not a technical one.
5. **Storage-unverifiable floor threshold:** propose "predicted AND actual
   both under 1 MB → mark storage unverifiable rather than within-band,"
   mirroring how timeout already handles duration. **Confirm the number** (1
   MB, or something else, given `grading.yaml`'s small-tier `max_abs_mb: 32.0`
   for context).
6. **Demo database hosting/ownership:** propose one CockroachDB Serverless
   free-tier cluster, provisioned once, credential stored as
   `DEMO_READONLY_DATABASE_URL` in the judge-facing deployment's env. Given
   `backendfix.md` says "Team: two people, Samved owns all backend and
   infrastructure" — confirm you're the one provisioning/owning this, and flag
   if there's a reason not to stand up a permanent cluster (cost, account
   limits).
7. **"Measure" as a real backend lifecycle state or a frontend overlay?** The
   spec's 5-stage rail (provision, seed, execute, **measure**, teardown)
   doesn't map onto the existing `ShadowClusterStatus` enum
   (`provisioning/ready/seeding/migrating/destroying/destroyed/failed` — no
   `measuring` state, and storage-delta measurement currently happens *inside*
   the migrate step). Introducing a real new enum state means touching the
   locked state machine (`ALLOWED_TRANSITIONS`, every Lambda handler) — a
   bigger, riskier change than treating "measure" as a synthetic frontend
   sub-stage overlaid on the tail of migrating / head of destroying, driven by
   whether the schema-diff-after snapshot (Phase C-2) has landed yet. **Default
   recommendation: frontend-only pseudo-stage, no new backend enum value.**
   Confirm you're OK not touching the locked state machine for this.

## 8. Things in the spec worth reconsidering, given what the code actually contains

- **Part B's "three distinct failure messages" ask is already ~90% built.**
  The backend has 7 precisely-triggered error paths already mapped to distinct
  frontend copy. Don't spend build time re-deriving error differentiation —
  spend it on the staged-progress UI, which is the actual gap.
- **A2.6's literal screenshot ("62% headline, 0.62/0.82 in prose") doesn't
  reproduce against current code.** The headline already shows the adjusted
  value. Worth a quick re-screenshot before starting Workstream 2 to confirm
  what's actually left to fix here (raw-shown-alongside + promoting the
  four-signal list), rather than assuming the full original bug still exists.
- **The Part C spec doesn't budget for the connection-concurrency wrinkle**
  in job-ID capture + targeted polling (§4) — worth treating Phase C-0 as a
  real spike with a go/no-go outcome before committing to the full execute-panel
  design, rather than assuming it's guaranteed to work as described.
- **Direction F (fleet/history view) from the earlier plan is not in the spec
  and I think that's correct** — recommend explicitly deferring it past this
  build; it doesn't serve the "judge watches one run" demo narrative Part C is
  optimizing for.

---

## TL;DR — simplified, high-level version

**Verified:** almost every finding in Parts A and B is real. The one exception
is the confidence "raw as headline" bug — that one's already fixed in code, the
screenshot was stale. The accuracy-metrics bug is real and it's a backend query
problem (comparing unrelated populations), not a frontend label problem. The
demo-database gap is real and deliberate — the code to fix it already exists,
it's just switched off for judges and has no permanent cluster to point at.

**Task 3's big question is answered: it's backend AND frontend, substantially.**
Nothing needed for the target shadow live view exists yet — no before/after
schema diff capture, no job-ID capture, no targeted job polling, no persisted
history for replay. This is the largest workstream by far.

**Suggested order:**
1. Fix the cheap, high-visibility blockers first (duplicate panel, Clerk ID,
   dev toast) — no backend risk.
2. Fix accuracy metrics and storage grading at the query/grading-engine level
   (root cause, not display).
3. Rebuild the DB-attach flow and turn on a real demo database — this is the
   thing standing between a judge and using the product at all.
4. Rebuild the shadow live view last, in backend-first phases (job capture →
   schema diff → durable progress storage → 3-band UI → replay), because
   everything the UI needs to show has to exist in the database first.

**Before any of this starts, seven decisions are needed from you** (§7 above):
transport (SSE vs polling), floating-panel resolution, chaos-run tagging
approach, what "Succeeded" should mean, the storage-unverifiable threshold,
who owns the demo cluster, and whether "measure" becomes a real backend state
or stays a frontend-only overlay. Also: `backendfix.md`'s auth section is
stale (says no Clerk, code has Clerk) and should be corrected the next time
that file is touched.