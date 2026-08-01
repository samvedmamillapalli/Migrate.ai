# Shadow Cluster Data Visualization — Audit & Plan

Status: **implemented and verified against a real shadow run (2026-07-30).**
Backend correctness audit is in §0. Implementation notes and real verification
evidence are in §8.
Owner: Samved
Scope: the specific "box with before/after data, arrows, red/green highlights"
view of what the shadow cluster looked like before a migration and what it
looks like after — not the whole shadow-execution UI (lifecycle rail, event
log, cost strip are out of scope here; see `docs/SHADOW_LIVE_REPRESENTATION_PLAN.md`
and `docs/ai_audit.md` for those).

Every claim below is anchored to a file path, and most to a line number.
Anything not found in the code is marked as a gap, not inferred.

---

## 0. Backend correctness audit (added on follow-up)

The claim "no backend work, everything's frontend-only" from the original
pass was re-checked by reading every function that produces the before/after
data, not just the ones that shape it for display. Two things were verified
clean, and one real, independently-shippable backend bug was found.

### 0.1 Verified clean

- **The two execution paths don't diverge.** There are genuinely two code
  paths that can produce a shadow migration's before/after data —
  `backend/app/shadow/orchestrator.py` (`_migrate`, in-process, used by the
  local/dev/mock-provider path) and `backend/app/shadow/migration_runner.py`
  (`run_migration`, used by the real AWS Step Functions `ExecuteMigration`
  Lambda, `backend/app/lambdas/handlers/execute_migration.py`). This was a
  real risk to check — two independently-written implementations of the same
  capture logic would be a classic drift bug. They don't: both call the exact
  same shared functions in `backend/app/shadow/schema_snapshot.py`
  (`capture_shadow_snapshot`, `extract_referenced_tables`,
  `build_row_ids_for_matching`, `build_schema_diff`) with the same before →
  migrate → after sequencing. One source of truth, two callers.
- **The SSE stream and the plain GET route serialize identically.**
  `schema_diff` is computed on read, not persisted (`schemas/observability.py:98-100,128-130`,
  `build_schema_diff(schema_snapshot_before, schema_snapshot_after)` on every
  call). Checked whether the SSE generator (`runs.py:504-574`) bypasses this
  and serializes the raw entity instead, which would silently drop
  `schema_diff` from the live view while the polling GET still had it. It
  doesn't — `runs.py:549-551` calls the identical
  `ShadowClusterResponse.from_orm(...)`. Also checked the SSE loop for stale
  reads (a common async-SQLAlchemy bug: reusing one long-lived session/ORM
  identity map across ticks so later ticks return cached data): it opens a
  **fresh session per tick** (`runs.py:540-541`, `contextlib.aclosing`),
  so this isn't happening either.

### 0.2 A real bug: multi-statement migrations aren't actually rolled back on failure

`backend/app/shadow/job_progress.py::run_with_job_progress` (the function that
actually executes the migration SQL) wraps the statements in a client-side
transaction — `psycopg.AsyncConnection.connect(dsn)` (transactional by
default), loop `cur.execute(statement)` per statement, then `conn.commit()`,
or `conn.rollback()` in the `except` block on failure (`job_progress.py:154-167`).
The docstring one layer up, in `migration_runner.py:88-93`, states this
explicitly: *"Execute `migration_sql` inside one transaction on the shadow
cluster... On failure the transaction is rolled back, so nothing is left
half-applied and `rollback_required` is True."*

That guarantee does not hold on CockroachDB, and this codebase already knows
it in a different file: `backend/app/shadow/seeder.py:60-64` explicitly runs
its own DDL/DML under `isolation_level="AUTOCOMMIT"` with the comment *"This
is required on CockroachDB, which rejects a schema-change statement (e.g.
CREATE INDEX) that follows a write (INSERT) inside the *same* transaction."*
That's the same underlying fact stated from the other side: CockroachDB
schema-change DDL does not participate in ordinary client-side transactions
the way Postgres DDL does — **each schema-change statement commits on its
own, server-side, regardless of what transaction the client thinks it's
in.** `job_progress.py` wraps multiple DDL statements in exactly the kind of
client-side transaction `seeder.py` had to route around elsewhere in this
same repo. A client-side `conn.rollback()` after a later statement fails
cannot undo a schema change CockroachDB already durably committed for an
earlier one.

Concretely: if a migration is `ALTER TABLE users ADD COLUMN a TEXT; ALTER
TABLE users ADD COLUMN b TEXT NOT NULL;` and the second statement fails (say,
a NOT NULL violates existing rows), CockroachDB has **already committed**
column `a`. `job_progress.py` still calls `conn.rollback()` and the caller
still reports `success=False, rollback_required=True` — which reads as "the
shadow cluster is back to exactly how it was before," but it isn't: column
`a` is still there.

**Why this matters for the visualization specifically:** the after-snapshot
(`schema_snapshot_after`, `row_sample_after`) is captured *after* this failed,
"rolled back" migration (`migration_runner.py:125-131`,
`orchestrator.py:231-237` — both capture "after" unconditionally, success or
failure). For a multi-statement failure, that after-snapshot will correctly
and honestly show column `a` still present — the row-sample/diff data itself
is not lying. The lie is one level up: `rollback_required: true` and
`success: false` get shown elsewhere in the UI (grade, execution result,
cost strip) implying nothing changed, while the diff box the rest of this
plan is about to build would — correctly — show that something did.
**Building the "before/after" box on top of this without fixing the
rollback claim risks the box being the one place in the product that
visibly contradicts the "verified rollback-safe" framing everywhere else.**

**Scope of impact, checked:** grepped the migration corpus and grading
config for multi-statement examples (`;` followed by another DDL statement)
— found none; every migration this app currently exercises appears to be a
single DDL statement, where this bug is inert (a single statement either
fully applies or doesn't — there's nothing partial to roll back). But
**nothing prevents a user from typing a multi-statement migration** in the
SQL editor — `orchestrator.py:304-310`'s `_split_sql` docstring even
acknowledges multi-statement input is expected input, just imperfectly
parsed, not rejected. This is a live risk the first time anyone (a judge
included) pastes in a two-statement migration, not a hypothetical.

**Recommended fix (backend, not yet built, needs your call):**
- **Option A — validate and reject.** Cheapest, matches how the product is
  actually used today: if `extract_referenced_tables`'s underlying parse (or
  a simple statement count) finds more than one DDL statement, reject the
  migration at submission time with a clear error ("one statement per
  migration — CockroachDB commits DDL per-statement, so multi-statement
  rollback can't be guaranteed"), rather than silently mis-reporting rollback
  safety later. Small change, one validation function, one new error path
  in `app/schema_analysis/errors.py`'s style.
- **Option B — track partial application honestly.** Harder: record which
  individual statements committed before a failure (the loop in
  `job_progress.py:159-160` already executes one at a time — just capture an
  index), and change `rollback_required` to a real tri-state
  (`fully_rolled_back` / `partially_applied` / `not_attempted`) surfaced
  through grading and the diff box instead of a boolean that's wrong in the
  partial case.

No default is proposed here — this changes a locked correctness claim
(`rollback_required`) that grading and memory already consume
(`app/grading/engine.py`, `app/memory/writer.py`, `app/lambdas/handlers/persist_results.py`
all read `rollback_required`), so it's your call which option, and whether
it's in scope for this pass or a separate fix. Either way, this is
**backend-only** and independent of the four frontend decisions in §4 below —
it doesn't block that work, but it should probably land first or alongside
it, since §4's whole point is to make the before/after diff more visible,
which makes this gap more visible too.

### 0.3 Minor, not blocking

- `_split_sql` (naive `sql.split(";")`) is duplicated verbatim in both
  `orchestrator.py:303-310` and `migration_runner.py:64-65` instead of
  shared from one place. Not a correctness bug (both copies are identical
  today), just a small duplication smell worth folding into
  `schema_snapshot.py` alongside the other shared helpers if either copy is
  ever touched.
- The SSE endpoint accepts its bearer token via a `?token=` query parameter
  (`middleware_auth.py:66-67`), scoped only to this one route with a code
  comment explaining why (`EventSource` can't set headers). Query-param
  tokens can end up in server access logs or browser history. This is a
  known, common, accepted tradeoff for `EventSource`-based auth, not a bug —
  flagged here only because it's the kind of thing worth a second pair of
  eyes before a judge-facing deploy, not because it needs fixing for this
  plan.

---

## 1. The headline finding: most of this already exists

Before planning new work, the code was read end to end. The feature described
— "a box showing the columns replicated onto the shadow cluster, CSV-like,
before vs. after, with red/green highlights for data going in and out" — is
**already built**, landed in the last two commits (`19afb30`, `aeaff35`,
2026-07-28/29). It has just never been looked at with real data (see §3).

What exists today, grounded in code:

| Piece | File | What it does |
|---|---|---|
| Row-sample capture | `backend/app/shadow/schema_snapshot.py:41,106,228,288` | Captures up to **20 rows** per table, real column names/types/nullability, via a plain `SELECT * FROM table LIMIT 20` — captured once right before the migration runs and once right after, against the shadow cluster only. |
| Row matching | `schema_snapshot.py:107,288-375`, `build_row_ids_for_matching` | The "after" capture **re-fetches the exact same primary-key values** as the "before" capture when a table has a usable PK (`matched_by_pk: true`). This means before/after rows are already row-aligned, not just two independent samples — a precondition for cell-level diffing (§4.3) that already exists and requires no new backend work. |
| Persistence | `backend/alembic/versions/l7g3d0e6f485_shadow_row_samples.py` | Two new JSONB columns on `shadow_clusters`: `row_sample_before`, `row_sample_after`. |
| Structural diff | `backend/app/shadow/schema_snapshot.py` (schema_compare), `backend/app/schemas/observability.py` | Table/column/index/constraint level diff, classified `added`/`removed`/`changed`/`unchanged`. |
| Frontend mapping | `frontend/oracle/apps/web/lib/api/map-run.ts:897-1053` | `mapSchemaDiff`, `mapRowSamplePanel`, `mapRowSampleTables` — turn the raw JSONB into typed view models. Column coloring in the row-sample view **reuses** the schema-diff classification by column name (`map-run.ts:976-977`), so there's one source of truth for what counts as "changed," not two diff passes. |
| Rendering — row samples | `frontend/oracle/apps/web/components/shadow-row-samples-panel.tsx` | Two side-by-side blocks, **Before** / **After**, one card per table, real column headers (name + type + nullable), real cell values, green-tinted header + cell background for added columns (`:69-71,101-103`), amber/red/grey text for changed/removed/unchanged (`DIFF_TEXT` map, `:6-11`). |
| Rendering — structural diff | `frontend/oracle/apps/web/components/shadow-live-view.tsx:297-363` | `SchemaDiffPanel` — per-table card, green/red/amber/grey text exactly per the locked color rule ("color means structural change, never quality," `docs/ai_audit.md` §C4). |
| Rendering — table shape (no values) | `shadow-live-view.tsx:376-484` | A masked-cell variant (real columns/row-counts, every cell shown as `·`) for a "what does this table look like" glance before real samples are available. |
| Transport | `frontend/oracle/apps/web/lib/api/shadow-stream.ts`, `backend/app/api/routes/runs.py` (`/shadow-cluster/stream`) | Server-Sent Events, not polling — pushes updates as they happen, one connection, no repeated request cost. |
| LLM/token cost | — | **Zero.** Every piece above is a plain SQL query (`SELECT * ... LIMIT 20`, information-schema lookups) persisted as JSONB and rendered client-side. Nothing in this path calls Bedrock or any LLM. The only LLM calls anywhere in the app are prediction/grading/memory (separate feature, separate cost budget) — this visualization does not add to it, and never will unless something here is explicitly changed to summarize data with a model, which is not recommended (see §4.2 — curation is done by cheap column-name filtering, not by asking a model what's "important"). |

So the honest starting point for this plan is: **don't rebuild it — finish and
polish what's there.** The rest of this doc is about closing the gap between
"already built" and "actually looks like the box you described."

---

## 2. What "the box" looks like today vs. what was asked for

Screenshot evidence (`run-detail-pending.png`, captured live against the
running dev server, run `b5459e92`, 2026-07-30): the container UI (lifecycle
rail, section shells, dark monospace design system) is genuinely clean —
5-stage rail (PROVISION → SEED → EXECUTE → MEASURE → TEARDOWN), consistent
muted-gray/mono typography, graceful empty states everywhere. No visual
blockers in the shell itself.

But the **specific ask — one box, before|arrow|after, red/green — isn't quite
what's rendered.** Three concrete gaps between the ask and the current code:

1. **No arrow, no unification.** `ShadowRowSamplesPanel` renders Before and
   After as two independent stacked/side-by-side sections (`shadow-row-samples-panel.tsx:149-180`,
   a `grid lg:grid-cols-2`) — there's no visual connector between a table's
   before-state and its after-state, and it's a separate component/section
   from the structural diff and table-shape panels (three different panels,
   three different files, stacked vertically in `shadow-live-view.tsx:600-619`).
   The "Pred → Actual" comparisons block (`shadow-live-view.tsx:256-295`) is
   the only place in the app that actually uses a `→` glyph today.
2. **No curation.** `mapRowSampleTables` (`map-run.ts:966-1003`) returns every
   captured column and every captured row (up to 20) with no filtering —
   the render layer shows all of it (`shadow-row-samples-panel.tsx:94-115`).
   Nothing trims to "just the important parts."
3. **Column-level, not cell-level, highlighting.** Coloring is per-column
   (a whole column is added/removed/changed/unchanged), not per-value. Even
   though the data needed for cell-level diffing already exists
   (`matched_by_pk`, §1), nothing compares `before.rows[i]` against
   `after.rows[i]` today.

None of these are backend gaps — items 1–3 are frontend rendering/layout
work against data that's already fetched, already typed, and already color-classified.

---

## 3. The verification gap (do this first)

No migration run in the dev environment has ever completed a shadow
execution — confirmed live: `Past Migrations` lists three runs, all `Pending`
(never approved/executed), and opening one shows `SHADOW CLUSTER: Waiting`,
`0/5`, all downstream panels in their empty state (screenshot above; 404s on
`/shadow-cluster`, `/execution-result` etc. are the expected "nothing there
yet" response, not bugs).

This means **the row-sample and schema-diff panels have never been seen
rendering real data by anyone**, including whoever wrote them. Before
spending time on the visual redesign in §4, run one real migration through to
completion (Current Migration → attach a database → approve → the shadow
workflow runs for real, ~30s per the timing in `docs/ai_audit.md` §C1) and
look at what `row_sample_before`/`row_sample_after`/`schema_diff` actually
contain. This catches shape mismatches, empty-array edge cases, or
type-formatting issues (e.g. `formatCell` in `shadow-row-samples-panel.tsx:13-17`
JSON-stringifies objects/arrays — worth confirming that reads cleanly for
whatever CockroachDB actually returns for JSONB/array/timestamp columns)
before the redesign is built on top of assumptions instead of observed data.

---

## 4. The plan (decisions locked in)

Four design questions were resolved before writing this section:

### 4.1 Unify into one box per table

Replace the three separate panels (`SchemaDiffPanel`, `TableShapePanel`,
`ShadowRowSamplesPanel`) with **one card per table**, laid out as:

```
┌─ users ──────────────────────────────────────────────────┐
│  BEFORE                    →       AFTER                  │
│  id    email     ⋯                 id    email     status │
│  ─────────────────────             ──────────────────────│
│  1     a@x.com                     1     a@x.com   active │  ← new col, green
│  2     b@x.com                     2     b@x.com   active │
│  3     c@x.com                     3     c@x.com   active │
│                                                             │
│  3 of 240 rows · matched by primary key                   │
└─────────────────────────────────────────────────────────┘
```

- One table name, one card, one `→` glyph as the visual hinge between two
  compact tables (CSS grid, three columns: before-table / arrow / after-table;
  stacks vertically on narrow widths).
- `TableShapePanel`'s masked-cell view is kept as the **loading state** for
  this same card (real columns, `·` placeholders) while `row_sample_after`
  hasn't landed yet — not a separate section, a state of the same component.
- The structural-only cases (a table with no row samples captured, e.g.
  `note`/`error` set) fall back to the existing text notes
  (`shadow-row-samples-panel.tsx:28-36`) inside the same card shell.
- This is a **frontend-only restructuring** — no new backend endpoint, no
  new persisted field. `mapRowSamplePanel` + `mapSchemaDiff` already return
  everything the merged card needs; only the component tree and layout change.

### 4.2 Curate to the important parts

Default view per table:
- **Primary key column(s)** always shown (context — which row is which).
- **Only columns that are `added`/`removed`/`changed`** shown by default,
  using the diff classification that already exists (`diffKind`,
  `map-run.ts:939,977-992`) — no new logic, just a filter at render time.
  `unchanged` columns collapse into a `+N unchanged columns` label,
  expandable on click to the full set (data's already fetched either way,
  so "expand" costs nothing extra).
- **Row count capped to ~3–5** by default (data already limits to 20 server-side;
  this is a display-only slice of what's already in memory), with an
  "show all 20" toggle for anyone who wants the full sample.
- Curation is **pure column-name/diffKind filtering**, not model-driven —
  confirmed no LLM involvement per §1, and this keeps it that way. Do not
  route this through a model to decide what's "important"; the diff
  classification already answers that question deterministically and for free.

### 4.3 Cell-level highlighting

Since `matched_by_pk` rows are already row-aligned between before/after
(§1), add a client-side diff step: for each row index `i` where
`matched_by_pk === true`, compare `before.rows[i][col]` to `after.rows[i][col]`
per unchanged/changed column and highlight individual cells that actually
changed value (amber background on the "after" cell, similar to how added
columns already get a green tint). Where `matched_by_pk === false` (no usable
PK, or the table changed shape too much to re-match), fall back to
column-level highlighting only, with a small note ("rows not matched — showing
column-level differences only") so the UI never implies a per-row comparison
it can't actually back up.

This is **frontend-only** — no schema or backend change, since the exact
values needed are already present in `row_sample_before`/`row_sample_after`.

### 4.4 Verify before polishing

Per §3: run one real shadow migration end to end first. Concretely:
1. Pick or create a migration run against a real (or the judge-demo) database.
2. Approve it so the shadow workflow actually executes.
3. Watch `/dashboard/migrations/current/shadow` live, and afterward inspect
   the persisted `row_sample_before`/`row_sample_after`/`schema_diff` JSONB
   directly (e.g. via the `/runs/{id}/shadow-cluster` endpoint) to confirm
   real shape before building the merged-card UI against it.
4. Only then implement §4.1–§4.3.

---

## 5. What this plan deliberately does NOT include

- **No new charting/table library** (e.g. TanStack Table, AG Grid). Data
  volume is tiny by design (≤20 rows × a handful of columns × a handful of
  tables per run) — no sorting/filtering/virtualization need exists. A
  hand-rolled `<table>` (what's already there) is simpler, smaller, and
  matches the existing monospace design system. Pulling in a grid library
  here would be solving a problem this feature doesn't have.
- **No new backend work for §4's four UI decisions specifically.** Every gap
  identified in §2 is closed by restructuring/filtering data the backend
  already captures and already returns. `row_sample_before`,
  `row_sample_after`, `schema_diff`, `matched_by_pk` are all already there
  and, per the §0 audit, correctly computed and correctly served (identical
  logic on both execution paths, identical serialization on both the REST
  and SSE routes). This does **not** mean the backend has no open work at
  all — §0.2 found a real, independent correctness gap (multi-statement
  migrations aren't actually rollback-safe despite being reported as such).
  That's backend work, but it's about the trustworthiness of the underlying
  `rollback_required`/success reporting, not about the box described in this
  doc — see §0.2 for why it's still worth doing before or alongside §4.
- **No change to LLM/model usage.** Confirmed zero LLM involvement in this
  path today (§1); the curation approach in §4.2 is explicitly chosen to keep
  it that way.
- **No fleet/history view, no SSE-vs-polling rework, no job-progress bar** —
  those are real, already-scoped workstreams but belong to
  `docs/ai_audit.md` Workstream 4, not this doc. This plan is scoped
  narrowly to the before/after data box.

---

## 6. Suggested build order

0. **Decide on §0.2's fix (Option A or B) and ship it** — backend-only,
   independent of the rest, but do it first: it changes what "after" data
   *should* mean on a failed multi-statement run, and §4.1's merged box is
   exactly the surface that will make the current mis-reporting visible.
   Shipping it after the pretty box exists just means redoing the failure-
   state design once the semantics change.
1. **Verify** (§3/§4.4) — run one real migration, inspect the real JSONB shape. No code changes.
2. **Merge the three panels into one card component** (§4.1) — pure layout/restructuring, in `shadow-live-view.tsx` + a new/rewritten row-sample component; reuses existing mapped data.
3. **Curate columns/rows** (§4.2) — filter logic in the new merged component, or a small addition to `mapRowSamplePanel`.
4. **Cell-level highlighting** (§4.3) — a new small pure function (`diffRowCells(before, after, matchedByPk)`) plus the render change to apply it.

Each step (1–4) is independently shippable and testable against the same
real run captured in step 1. Step 0 stands alone and can happen in parallel
with step 1's verification run — in fact running the verification migration
as two statements would double as a live test of whichever fix is chosen.

---

## 7. Open items (from the original plan — historical, see §8 for what shipped)

- Once the merged card is built, confirm the mobile/narrow-width stacking
  behavior (before-table above arrow above after-table) still reads clearly —
  not addressed in detail here since it's a normal responsive-CSS concern,
  not a design decision.
- If a table has more than a handful of added/removed/changed columns (a
  large migration), the "unchanged columns collapsed" default in §4.2 should
  keep the card from becoming unreadably wide — worth a quick sanity check
  once real data is available in step 1 above, since no run so far has
  exercised a multi-column migration to see how wide this gets in practice.

---

## 8. Implementation notes (what actually landed, 2026-07-30)

### 8.1 §0.2 fix — shipped as Option A (reject, not track partial application)

`backend/app/services/migration_run_service.py`: `create_migration_run` now
rejects any `migration_sql` that parses (via the same sqlglot/postgres-dialect
convention already used by `app.policy.engine` and `app.shadow.schema_snapshot`)
to more than one statement, with a 422 and a message explaining why
(CockroachDB's per-statement DDL commit). This is the single funnel point
used by `POST /runs`, `POST /runs/debug/demo-with-db`, and any future caller —
verified directly against the running API:

- `ALTER TABLE users ADD COLUMN a TEXT; ALTER TABLE users ADD COLUMN b TEXT;` → `422`, rejected.
- `ALTER TABLE customers ADD COLUMN verify_col TEXT;` (single statement, trailing `;`) → `201`, accepted normally.

`create_debug_fake_migration` (the synthetic debug path) wasn't touched — it
builds its `MigrationRun` directly from `app.debug.fake_migration.pick_fake_migration()`,
which only ever generates single-statement templates, so it was never at risk.

### 8.2 Real end-to-end verification (not the mocked/theoretical kind)

Ran an actual migration through the real pipeline — schema discovery,
Bedrock prediction, approval, and `POST /runs/{id}/verify-local` (the same
Lambda-handler chain the production Step Functions workflow uses, backed by
a real scratch CockroachDB database via the mock provider, not a stub) —
against a purpose-built small table (`orders`, 25 rows) rather than the
control-plane's own 11-table schema, which turned out to matter: an earlier
attempt discovering against the full control-plane database picked the
"medium" scale tier (10,000 synthetic rows/table cap × ~10 tables) and the
seed stage never finished in a reasonable time. Killed it, dropped the
leftover scratch database it had created, and re-ran against a single small
table instead — a useful data point on its own: **schema breadth, not just
row count, drives shadow-run seed time**, and a demo/verification database
should stay narrow.

Confirmed real, persisted output matches exactly what §1–§4 assumed:
`schema_diff` correctly classified the new `priority` column as `added`;
`row_sample_before`/`row_sample_after` were real, PK-matched
(`matched_by_pk: true`), with `priority` absent from `before` rows and
present as `null` in the corresponding `after` rows — confirming cell-level
diffing (§4.3) needs no new backend work, exactly as planned.

Also incidentally re-confirmed the §0.2 fix is load-bearing: the very first
attempt at this verification (before the backend picked up the code change,
pre-restart) *did* let a two-statement migration through — direct evidence
the bug in §0.2 was real and reachable, not theoretical.

**A second, smaller real bug found and fixed during verification, unrelated
to the original ask:** `backend/scripts/prepare_judge_demo_db.py`'s `judge_ro`
role setup revoked database-level `CREATE` but not schema-level `CREATE` on
`public`. CockroachDB grants `CREATE` on the `public` schema to the implicit
`public` role by default, so on a **freshly created** database (unlike the
already-existing `migration_oracle` control-plane database this script has
always pointed at in practice, which apparently already lacked that default)
the resulting "read-only" role could still issue `CREATE TABLE` — which the
app's own read-only probe (`app/schema_analysis/read_only.py`) correctly
detects and rejects. Verified directly: a role provisioned by the
pre-fix script could `CREATE TABLE` successfully; after adding
`REVOKE CREATE ON SCHEMA public FROM ...` (both from `public` and the role
itself), the same probe correctly failed with `InsufficientPrivilege`. Fixed
in the script; re-ran it (idempotent) to apply the revoke to the existing
`judge_ro` role too.

### 8.3 Frontend — one component, no new libraries

`frontend/oracle/apps/web/lib/api/map-run.ts`: added `mapUnifiedTableDiff()`
and `isCellChanged()`. The mapper reuses `mapRowSamplePanel()`/`mapSchemaDiff()`
entirely (no new backend calls) and does one new thing: it pairs `before.rows`
and `after.rows` by primary-key value into a single `rows` array per table,
so the component never has two independently-ordered row lists to keep in
sync — before/after alignment is structural, not a rendering assumption.
Also added `primaryKey: string[]` to `RowSampleTableView` (present in the raw
JSON all along, just not previously surfaced to the frontend).

`frontend/oracle/apps/web/components/shadow-row-samples-panel.tsx`: rewritten
in place (same export, same single call site in the dedicated Shadow
Execution page) as one card per table: a shared `<table>` with a `before`
column group, a `→` divider column, and an `after` column group, driven by
the single paired-row array. Column set defaults to primary key +
added/removed/changed (`table.significantColumns`), with unchanged columns
collapsed behind a "+N unchanged columns" toggle; rows default to 4 with a
"show all N sampled rows" toggle. Cell-level highlighting
(`isCellChanged`) applies an amber background to an individual `after` cell
only when: the column is `unchanged`/`changed` (not `added`/`removed`, which
already read via whole-column green/red), the row is PK-matched on both
sides, and the JSON-stringified value actually differs.

No new frontend dependency was added — confirmed the existing hand-rolled
`<table>` approach (matching the design system used everywhere else in this
codebase) was sufficient once curation caps the visible surface, per the
original recommendation against pulling in a grid library.

Verified live in the browser against the real run from §8.2 (screenshot
evidence, not just code review): the box renders with real PK values on
both sides, the added `priority` column green-tinted on the `after` side,
"+4 unchanged columns" and "Show all 20 sampled rows" toggles both work
(clicked and confirmed re-render), zero console errors. Cell-level amber
highlighting exists in code and is exercised by `isCellChanged`'s logic but
wasn't visually exercised by this particular test migration (a plain `ADD
COLUMN`, which only creates new-column cells, not changed-value cells on an
existing column) — worth a second real-run check with a type-change
migration (e.g. `ALTER COLUMN ... TYPE ...`) before calling that path
pixel-verified, not just logic-verified.

### 8.4 Two more real bugs, found chasing a user-reported failure (2026-07-30)

A real run against the real `ccloud_api` provider (not the mock path §8.2
verified against) came back with row samples **and** the structural schema
diff both empty — `"Row sample capture was unavailable for this run
(connection issue, timeout, or...)"`. Root-caused by reproducing the exact
scenario (same table, same `medium` scale tier, same real cluster provider,
DEBUG logging) rather than guessing from code alone:

1. **`capture_shadow_snapshot` (`schema_snapshot.py`) had zero retries.** A
   freshly-provisioned CockroachDB Cloud cluster can have a brief connection
   hiccup in the seconds right after creation (real infra, not a code bug) —
   and the existing code gave up permanently on the first failed connection
   attempt. Added a bounded exponential-backoff retry (2 extra attempts,
   1s/2s), mirroring the resilience pattern `ccloud_api_provider.py` already
   uses for the Cloud API itself — this codebase already knew how to handle
   transient cloud flakiness, just not here.
2. **A second, concretely-reproduced bug independent of the first**, in
   `migration_runner.py`: the post-migration storage-measurement query and
   the job-watch query share one connection. When the storage query fails
   (it can — `crdb_internal.table_span_stats` is unavailable on some
   CockroachDB Cloud tiers, already a known limitation logged elsewhere in
   this app) the connection was left in an aborted-transaction state with no
   rollback, so the *next* query on that same connection (job-watch)
   necessarily failed too with `InFailedSqlTransaction` — confirmed with the
   exact stack trace in a reproduction run. Fixed by rolling back after the
   caught failure so the connection is usable again for whatever runs on it
   next.

Verified both fixes together against a fresh real cluster: job-watch went
from 0 jobs captured (cascading failure) to 7; `row_sample_before/after` and
`schema_snapshot_before/after` all populated. Neither bug is specific to the
visualization work in this doc, but both directly determine whether the data
this box renders shows up at all on a real (non-mock) run — worth recording
here since that's exactly the failure mode a judge or user would hit.
