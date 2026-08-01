# Row-Level TTL + Follower Reads — full integration plan

Status: **planning only, nothing implemented yet.** Written after reading
`docs/backendfix.md` in full and re-reading the real current code (not
assumptions) for every file this touches. Verified against CockroachDB's
actual documented TTL and follower-read mechanics, not memory of the feature
names.

## Bottom line up front

Both features are real, both are worth doing, and neither is a one-line
`ALTER TABLE`. Each has a genuine gap that would make a naive implementation
either silently wrong or silently misleading, which conflicts with this
project's own "never fabricate, never mislead" rule (`docs/backendfix.md`
"The corpus" section). The gaps and the fixes for them are below.

- **Row-Level TTL** is straightforward for the delete mechanics but has one
  real bug-shaped gap: a `ShadowCluster` that fails *during teardown* never
  gets `destroyed_at` set (confirmed at
  [`shadow_cluster_service.py:163-164`](../backend/app/services/shadow_cluster_service.py) —
  `destroyed_at` is only stamped on transition to `DESTROYED`, never `FAILED`),
  so a naive `destroyed_at`-only expiration expression would let those rows
  live forever. Fixed below with a `CASE` expression that falls back to
  `updated_at` for terminal-but-never-destroyed rows.
- **Row-Level TTL** also has a product-correctness gap: once a `shadow_clusters`
  row is deleted, the Shadow Execution page's rich replay (event log, row
  samples, schema diff) for that old run silently has nothing to show. Today
  `GET /runs/{id}/shadow-cluster` 404s with "No shadow cluster recorded" —
  which is exactly the message shown for a run that **never had a shadow**.
  After TTL ships, that same message would incorrectly describe a run that
  *did* have a shadow, whose detail just expired. That is a misleading UI
  state by this project's own standard and must be fixed as part of this work,
  not left as a side effect.
- **Follower Reads** is real and genuinely a good fit for this app's
  read-heavy dashboard queries, but the user's framing ("faster dashboard
  loading") needs one honest correction: this deployment is single-region
  (`us-east-1` only, confirmed at `docs/backendfix.md:114`). Follower reads'
  headline benefit — avoiding a cross-region hop to the leaseholder — does not
  apply here. The real, still-legitimate benefit in a single-region cluster is
  spreading read load off the leaseholder replica so heavy dashboard queries
  (accuracy metrics, run history, memory browser) don't queue behind writes
  and other reads on the same replica. That's a real win, worth doing, just a
  different one than "faster" implies. If this app ever goes multi-region,
  the latency win becomes real too, for free, since the query pattern doesn't
  change.
- **Follower Reads must not be applied uniformly.** Doing so would quietly
  break two things this session already built: the SSE shadow-cluster stream
  (which is explicitly supposed to be near-real-time — follower reads would
  make "live" data ~4.8s stale) and the read-your-writes flows (create a run,
  then immediately fetch it — a stale follower read could return 404 or an
  old status right after a write). Scoping is not optional polish here; it's
  required to not regress work already shipped this session.

---

## Feature 1 — Row-Level TTL

### 1.1 How CockroachDB TTL actually works (verified)

- Row-level TTL is a **table storage parameter**, set via `ALTER TABLE ...
  SET (...)` or at `CREATE TABLE ... WITH (...)`. It runs as a recurring
  background job, not an app-level cron.
- Two ways to define expiration, and they compose:
  - `ttl_expire_after = '<interval>'` — the simple mode. CockroachDB adds a
    hidden `crdb_internal_expiration` column and expires rows N time after
    that column's value (which defaults to row creation time).
  - `ttl_expiration_expression = '<SQL expression>'` — a custom SQL
    expression, evaluated per row, that must return `TIMESTAMPTZ`. This is
    what we need, since expiration must be based on `destroyed_at`
    (a data column), not row-creation time.
  - The two *can* coexist (`ttl_expire_after` provisions the hidden column and
    its mechanics; `ttl_expiration_expression` overrides what value is
    compared), but `ttl_expiration_expression` can also be used to define TTL
    on its own, referencing existing columns directly — no hidden column
    required. That's the mode this app should use: expiration is fully
    defined by `destroyed_at`/`updated_at`, no need for a second parallel
    "creation-based" clock.
  - **If the expression evaluates to `NULL` for a row, that row is exempt —
    it never expires.** This is exactly what's needed: every active shadow
    cluster (`destroyed_at IS NULL`) must never be touched by TTL, and this
    is the native, zero-extra-code way to guarantee that.
  - `ttl_job_cron` — standard cron syntax controlling how often the deletion
    job runs. `'@hourly'` matches what the user asked for.
  - `ttl_disable_changefeed_replication = 'true'` — suppresses TTL-issued
    deletes from being replicated through changefeeds. Not relevant today
    (this app has no changefeeds), but cheap to set now so it's not a
    surprise if one is added later.
  - Deletes are real SQL `DELETE`s executed by a background job as the `root`
    user, batched. They correctly clean up secondary indexes.
  - **Foreign-key interaction**: if another table has an inbound FK to a
    TTL'd table with `ON DELETE RESTRICT`, the TTL job fails outright when a
    referencing row exists. Confirmed via `grep` across
    `backend/app/database/models/` that **nothing has an inbound FK to
    `shadow_clusters.id`** — it is a pure leaf table (it has an *outbound* FK
    to `migration_runs`, the other direction). So this restriction does not
    apply here; TTL on `shadow_clusters` is safe from an FK standpoint.

Sources: [Row-Level TTL docs](https://www.cockroachlabs.com/docs/stable/row-level-ttl), [row-level TTL RFC](https://github.com/cockroachdb/cockroach/blob/master/docs/RFCS/20220120_row_level_ttl.md), [ttl_expiration_expression issue #76916](https://github.com/cockroachdb/cockroach/issues/76916).

### 1.2 Scope: `shadow_clusters` only, nothing else

The user's suggestion named `shadow_clusters` specifically, and that is
correct — do not extend TTL to any other table:

- `migration_runs`, `predictions`, `execution_results`, `grades`,
  `migration_memories` must **never** be TTL'd. `grades` and
  `migration_memories` are the accuracy/learning corpus this app's core
  differentiator (the closed-loop memory system) depends on — deleting them
  would delete the "brain." `migration_runs`/`predictions`/`execution_results`
  are what the Overview/History pages and the accuracy metrics endpoint read
  forever, scoped by owner.
- Neither `GradingPipelineService` nor `MemoryWriteService` reads from
  `ShadowCluster` to compute a grade or write a memory (confirmed: grading
  reads `Prediction` + `ExecutionResult`; memory writes read the graded
  outcome) — so deleting old `shadow_clusters` rows never corrupts a grade or
  a memory. It only removes the *rich replay artifacts* (event log, row
  samples, schema diff, cluster identity) for old runs. That is an acceptable,
  scoped, and correctly-isolated blast radius.

### 1.3 The expiration expression (the part that must not be half-baked)

Naive version (what the user's suggestion literally describes):

```sql
ALTER TABLE shadow_clusters SET (
  ttl_expiration_expression = 'destroyed_at + INTERVAL ''7 days''',
  ttl_job_cron = '@hourly'
);
```

This is **wrong on its own** because of the gap in 1.1: a `ShadowCluster`
whose teardown itself failed transitions to `FAILED` with `destroyed_at`
still `NULL` (`shadow_cluster_service.py:163-164`) — under the naive
expression, that row's expiration evaluates to `NULL` forever, so it never
gets cleaned up. It would sit in the table indefinitely, which is precisely
the kind of unbounded-growth problem TTL exists to prevent.

The correct expression accounts for both terminal paths:

```sql
ALTER TABLE shadow_clusters SET (
  ttl_expiration_expression = $$
    CASE
      WHEN destroyed_at IS NOT NULL THEN destroyed_at + INTERVAL '7 days'
      WHEN status = 'failed' THEN updated_at + INTERVAL '7 days'
      ELSE NULL
    END
  $$,
  ttl_job_cron = '@hourly',
  ttl_disable_changefeed_replication = 'true'
);
```

- `destroyed_at IS NOT NULL` → the common, clean path (`DESTROYED`).
- `status = 'failed' `→ backstop for teardown-failed clusters, using
  `updated_at` (bumped by `TimestampMixin`'s `onupdate=func.now()` on every
  service-layer write — confirmed at
  [`mixins.py:25-30`](../backend/app/database/mixins.py)) as the best
  available proxy for "when this row last changed," since no cleaner
  timestamp exists for that case.
- Every other status (`PROVISIONING`/`READY`/`SEEDING`/`MIGRATING`/`DESTROYING`)
  → `NULL` → never expires. An in-flight cluster can never be deleted out
  from under a live run, by construction, not by convention.

This does **not** overlap with `ShadowClusterSweeper`
(`backend/app/shadow/sweeper.py`): the sweeper tears down live *cloud*
resources past their lifetime deadline (`expires_at`) and is billing/hygiene
focused; TTL deletes *database rows* that are already fully terminal. They
operate on disjoint concerns and disjoint columns (`expires_at` vs.
`destroyed_at`/`updated_at`) — no conflict, no need to change the sweeper.

### 1.4 The part that's easy to skip and shouldn't be: honest expiry in the UI

Once this ships, `GET /runs/{id}/shadow-cluster`
(`backend/app/api/routes/runs.py:491-500`) will 404 with "No shadow cluster
recorded for MigrationRun {id}" for two different situations that must not
look the same to a user:

1. This run never had a shadow verification at all.
2. This run had one, and its 7-day detail window has passed.

Distinguishing these is not optional — showing (2) as (1) is a fabrication of
absence, which is exactly what this project's integrity rules forbid. Fix:

- `ExecutionResult` is **never** TTL'd and already durably records whether a
  shadow ran and what it produced (`success`, `duration`, `storage`,
  `rolled_back`, `timed_out`). Its existence is proof a shadow ran.
- Backend: no new endpoint needed (per the standing "reuse existing
  connections/endpoints" convention). `GET /runs/{id}/shadow-cluster` keeps
  its current 404 behavior (still correct for case 1). The frontend already
  separately fetches `GET /runs/{id}/execution-result`
  (`ExecutionResultResponse`) — that's the disambiguating signal.
- Frontend: in `shadow-live-view.tsx` / `shadow-row-samples-panel.tsx`, the
  "no shadow_cluster" empty state needs a second branch: if
  `execution_result` exists but `shadow_cluster` 404s, render *"This shadow
  run's detailed history has expired (kept for 7 days after teardown).
  Outcome and timing are still available below."* instead of the current
  generic empty/waiting state — and still render the execution-result summary
  that already exists on that page. If `execution_result` also doesn't
  exist, keep today's "never ran" state as-is.

### 1.5 Migration

New Alembic revision, chained after the current head `l7g3d0e6f485`
(`backend/alembic/versions/l7g3d0e6f485_shadow_row_samples.py`), pure raw SQL
via `op.execute(text(...))` since this is a CockroachDB-specific storage
parameter with no SQLAlchemy DDL construct for it — same pattern already used
elsewhere in this codebase for CockroachDB-specific DDL. `downgrade()` runs
`ALTER TABLE shadow_clusters RESET (ttl_expiration_expression, ttl_job_cron,
ttl_disable_changefeed_replication)`.

Given the documented CockroachDB behavior that each DDL statement on this
cluster tier runs as its own async background job taking 20–90s
(`docs/backendfix.md`, Known environment issues) — this migration should be
run in the background and polled, not treated as hung if it takes a minute.

### 1.6 Open questions for you (Feature 1)

1. **Is 7 days right for a hackathon demo?** If judges review the project
   more than 7 days after a demo run, the rich replay for that specific run
   disappears (outcome numbers do not). Fine to ship as-is, or do you want a
   longer window (e.g. 30 days) until after judging, then tighten it?
2. Should the `FAILED`-without-`destroyed_at` backstop use `updated_at`
   (proposed above) — the best available signal — or would you rather that
   case never auto-expire and instead surface as a permanent "needs manual
   cleanup" item? (Current sweeper doesn't retry teardown, so these rows are
   otherwise just clutter.)
3. Confirm scope: only `shadow_clusters`, nothing else — matches the plan
   above unless you want it wider.

---

## Feature 2 — Follower Reads

### 2.1 How it actually works (verified)

- Syntax: `SELECT ... FROM t AS OF SYSTEM TIME follower_read_timestamp() WHERE
  ...`, or transaction-scoped: `SET TRANSACTION AS OF SYSTEM TIME
  follower_read_timestamp()` as the **first statement** in a read-only
  transaction, before any other statement runs in it.
- `follower_read_timestamp()` picks a timestamp far enough in the past
  (historically ~4.8s, tunable via `kv.closed_timestamp.target_duration`)
  that the read is guaranteed servable from *any* replica, not just the
  leaseholder — so the query can be routed to the nearest/least-loaded
  replica instead of always hitting the leaseholder.
- There's also a session-level default:
  `SET default_transaction_use_follower_reads = on`, which applies it
  automatically to implicit and explicit read-only transactions. Rejected for
  this app below — too coarse, would silently touch the live shadow stream.
- **Cost of being wrong**: any write executed against the same transaction
  after `AS OF SYSTEM TIME` is set fails — historical reads are strictly
  read-only. This means whatever session/transaction issues the follower read
  must be provably read-only for its whole lifetime, not just "happens not to
  write today."

Source: [Follower Reads docs](https://www.cockroachlabs.com/docs/stable/follower-reads).

### 2.2 Honest fit check for this app's actual deployment

This app runs a single-region CockroachDB Basic cluster in `us-east-1`
(`docs/backendfix.md:114`). Follower reads' headline pitch —
"read from the replica near you instead of crossing regions to the
leaseholder" — doesn't apply, because there's only one region. What still
applies and is still worth having:

- **Leaseholder load spreading.** Every read today goes through the single
  leaseholder replica for each range. Under concurrent dashboard traffic
  (Overview + History + Memory browser all polling/loading), those reads
  queue behind each other and behind writes on the same replica. Follower
  reads let CockroachDB serve them from *any* replica in the range, which
  reduces contention on the leaseholder without needing more regions.
- **This is a real, defensible improvement — just don't oversell it as
  "faster" in isolation.** It's a scalability/contention fix more than a
  latency fix on this specific topology. Worth stating plainly if this is
  described in a demo or judge-facing doc, since the app's own values
  (`backendfix.md` "never fabricate, never mislead") apply to how the team
  describes its own work, not just to migration predictions.

### 2.3 What must and must not get follower reads

**Real candidates** (dashboard reads, staleness-tolerant, confirmed via
`grep` as the actual frontend call sites):

| Endpoint | Frontend caller | Why it's safe |
|---|---|---|
| `GET /runs` (list) | `app/dashboard/page.tsx` (Overview "Recent"), `app/dashboard/migrations/history/page.tsx` (History) | Browsing historical/recent runs; a few seconds of staleness is invisible |
| `GET /runs/metrics/accuracy` | `app/dashboard/page.tsx` (accuracy charts) | Aggregate stats over historical grades; inherently a trailing-window view already |
| `GET /memories` (list), `GET /memories/health` | `app/dashboard/memory/page.tsx` | Memory browser, historical corpus view |

**Must not get follower reads** (confirmed via code, not guessed):

- `GET /runs/{id}/shadow-cluster` and `GET /runs/{id}/shadow-cluster/stream`
  (`backend/app/api/routes/runs.py:491,503`) — this session's SSE rebuild
  exists specifically to make this feel live; a 4.8s-stale follower read
  directly undermines that and must never be applied here.
  `stream_shadow_cluster` also already opens its own short-lived session per
  tick (`runs.py:539`) — a fundamentally different, latency-sensitive access
  pattern than the list/aggregate endpoints above.
  - `GET /runs/{id}/pipeline-progress`, `/execution-result`, `/model-traces`,
  `/grade` — all read *the specific run currently being watched* during an
  active workflow; a client may call these immediately after a write (e.g.
  right after `POST /predict`) and needs read-your-writes consistency.
  - `POST` routes and `GET /runs/{id}` itself — no follower reads on any
  single-run fetch, since a run can be fetched immediately after being
  created/mutated (e.g. `create_run` → client redirects to a page that
  fetches that exact run).
- `current-migration-workspace.tsx` (the active in-progress workflow page) —
  confirmed via `grep` it does not call `listRuns`, so no accidental exposure
  there either.

### 2.4 Implementation shape (planned, not built)

Given the locked architecture ("transaction boundaries owned by the service
layer," `get_db_session` in `backend/app/dependencies.py:40-48` is the one
shared per-request session dependency used by both reads and writes), the
cleanest way to add this **without** touching that shared dependency or
risking a write accidentally running inside a follower-read transaction:

1. Add `get_follower_read_session` alongside `get_db_session` in
   `backend/app/dependencies.py`: opens a session from the same
   `DatabaseSessionManager`, then immediately executes
   `SET TRANSACTION AS OF SYSTEM TIME follower_read_timestamp()` as the
   first statement before yielding it. Deliberately a separate dependency
   (not a flag on the existing one) so it's structurally impossible for a
   write-capable route to receive a follower-read session by accident — the
   route has to explicitly ask for it.
2. Wire it only into the three read-only routes in table 2.3:
   `list_runs`, `get_accuracy_metrics` (`backend/app/api/routes/runs.py`),
   and the memories-list/health routes. These already take `AsyncSession`
   directly or through a thin service — swap the dependency only at the
   route layer, not inside the shared repository/service classes those
   routes call (so the same repository code keeps working correctly for
   both regular and follower-read callers).
3. No ORM query changes needed — `AS OF SYSTEM TIME` is set once per
   transaction, not per-statement, so the existing `select(MigrationRun)...`
   ORM queries in `migration_run_repository.py` work unmodified once the
   session itself is in follower-read mode.
4. Do **not** set `default_transaction_use_follower_reads = on` globally —
   too coarse, would silently apply to routes added later without anyone
   deciding to.

### 2.5 Open questions for you (Feature 2)

1. Given the honest single-region caveat in 2.2, do you still want this
   framed as "faster dashboard loading" for judges, or as "reduced
   leaseholder contention under concurrent reads" (accurate) — or skip the
   performance claim in the demo narrative and just note it as a production-
   readiness/scalability feature exercised (matches the judging rubric's
   "Production Readiness" criterion from the feedback you graded against
   earlier)?
2. `follower_read_timestamp()`'s default staleness is ~4.8s. Acceptable for
   Overview/History/Memory during a live demo (i.e., a judge creating a run
   and then immediately checking the History page might not see it for up to
   ~5s)? If not, this should probably ship but be demoed carefully (create →
   wait a beat → check History), or scoped to History/Memory only and left
   off the Overview "Recent" list for the demo.

---

## Combined sequencing

Independent features, no shared code, safe to build/ship in either order or
in parallel. Suggested order: TTL first (smaller surface, the frontend
"expired" state fix is required regardless of Follower Reads), then Follower
Reads.

## What NOT to do (guardrails, restated from the investigation above)

- Do not TTL any table besides `shadow_clusters`.
- Do not use a bare `destroyed_at`-only expiration expression — it leaks
  teardown-failed rows forever.
- Do not ship TTL without the frontend "expired vs. never-ran" distinction in
  1.4 — that gap is a real misleading-UI bug, not a nice-to-have.
- Do not apply follower reads via a global session default.
- Do not apply follower reads to the shadow-cluster GET/stream routes, any
  single-run GET, or any route that can be called immediately after a write.
- Do not claim a cross-region latency win in any judge-facing copy — this
  deployment is single-region; the real win is leaseholder contention, say
  that instead.

---

## The proper prompt (ready to hand off when you're ready to implement)

Copy everything below this line as the implementation task when you want to
build this. It is self-contained and matches the investigation above.

> Read `docs/backendfix.md` and
> `docs/COCKROACHDB_TTL_AND_FOLLOWER_READS_PLAN.md` at the repo root before
> doing anything. Update `docs/backendfix.md` with a dated Change Log entry
> before you finish.
>
> TASK: implement Row-Level TTL on `shadow_clusters` and scoped Follower
> Reads on the three read-only dashboard endpoints, exactly as specified in
> `docs/COCKROACHDB_TTL_AND_FOLLOWER_READS_PLAN.md`. Both features must be
> fully wired end-to-end, not stubbed.
>
> === STEP 1: confirm before writing code ===
> 1. Re-confirm the migration chain head under `backend/alembic/versions/` is
>    still `l7g3d0e6f485` (it may have moved since this plan was written —
>    if so, chain the new revision after whatever the real head is).
> 2. Re-confirm `shadow_cluster_service.py`'s `transition()` still only sets
>    `destroyed_at` on `ShadowClusterStatus.DESTROYED` and not `FAILED`. If
>    that's changed, the TTL expression's `FAILED`/`updated_at` fallback
>    branch may no longer be needed — decide based on current code, not this
>    doc.
> 3. Re-confirm no model has an inbound FK to `shadow_clusters.id` (grep
>    `backend/app/database/models/` for `shadow_clusters.id` / `ForeignKey(\"shadow_clusters`).
>    If one now exists, check whether it's `ON DELETE CASCADE` (fine) or
>    `RESTRICT` (breaks the TTL job — needs escalation before proceeding).
>
> === STEP 2: Row-Level TTL ===
> 1. New Alembic revision (raw SQL via `op.execute(text(...))`, chained after
>    the real current head) that runs:
>    `ALTER TABLE shadow_clusters SET (ttl_expiration_expression = $$ CASE
>    WHEN destroyed_at IS NOT NULL THEN destroyed_at + INTERVAL '7 days' WHEN
>    status = 'failed' THEN updated_at + INTERVAL '7 days' ELSE NULL END $$,
>    ttl_job_cron = '@hourly', ttl_disable_changefeed_replication = 'true');`
>    with a `downgrade()` that runs `ALTER TABLE shadow_clusters RESET
>    (ttl_expiration_expression, ttl_job_cron,
>    ttl_disable_changefeed_replication);`. Run this migration in the
>    background (this cluster's DDL jobs take 20–90s each; do not kill it for
>    looking stuck — that has caused partial-apply problems in this project
>    before, documented in `docs/backendfix.md`).
> 2. Backend: in `backend/app/api/routes/runs.py`, the `get_shadow_cluster`
>    handler stays as-is (still correct for the "never had a shadow" case).
>    No endpoint changes required.
> 3. Frontend: in `shadow-live-view.tsx` and/or `shadow-row-samples-panel.tsx`
>    (whichever owns the "no shadow_cluster" empty state today), add the
>    second branch described in plan section 1.4: when the shadow-cluster
>    fetch 404s but `GET /runs/{id}/execution-result` succeeds, render "This
>    shadow run's detailed history has expired (kept for 7 days after
>    teardown). Outcome and timing are still available below," and still show
>    the execution-result summary. When execution-result also doesn't exist,
>    keep the current "never ran" empty state unchanged.
> 4. Verify for real: manually set a test row's `destroyed_at` to 8+ days ago
>    (or `status='failed'` with `updated_at` 8+ days ago), wait for/trigger
>    the TTL job, confirm the row is actually gone, and confirm the frontend
>    shows the new "expired" message for that run instead of "never ran."
>    Also confirm an **active** (non-terminal) shadow cluster is never
>    touched, including one artificially aged past 7 days in every timestamp
>    except `destroyed_at`/status.
>
> === STEP 3: Follower Reads ===
> 1. Add `get_follower_read_session` to `backend/app/dependencies.py`,
>    alongside (not replacing) `get_db_session`: opens a session from the
>    same `DatabaseSessionManager`, executes `SET TRANSACTION AS OF SYSTEM
>    TIME follower_read_timestamp()` as the first statement, yields it. Keep
>    it structurally separate so no write-capable route can receive it by
>    accident.
> 2. Wire it into exactly these three read paths and no others: `list_runs`
>    and `get_accuracy_metrics` in `backend/app/api/routes/runs.py`, and the
>    memories-list/health routes (find their current file — likely
>    `backend/app/api/routes/memories.py` or similar; confirm the real path
>    before editing). Do not touch `get_shadow_cluster`,
>    `stream_shadow_cluster`, `get_run`, `get_pipeline_progress`,
>    `get_execution_result`, `get_model_traces`, `get_grade`, `get_memory`
>    (singular), or any `POST`/`PATCH` route.
> 3. Do not set `default_transaction_use_follower_reads` anywhere.
> 4. Verify for real: confirm the three follower-read routes still return
>    correct data (compare against a plain non-follower-read query for the
>    same rows), confirm a write immediately followed by a read on a
>    follower-read-enabled route does not error (it shouldn't, since it's a
>    fresh separate session/transaction, but prove it rather than assume it),
>    and confirm the SSE shadow-cluster stream still updates within ~1-3s as
>    it did before this change (i.e., prove Follower Reads did not leak into
>    that path).
>
> === CONSTRAINTS ===
> - No new tables besides the TTL storage-parameter change on the existing
>   `shadow_clusters` table.
> - No changes to `ShadowClusterSweeper` — it is a separate, non-overlapping
>   concern (live cloud resources vs. terminal DB rows) and does not need to
>   know about TTL.
> - Do not apply Follower Reads or TTL to `migration_runs`, `predictions`,
>   `execution_results`, `grades`, or `migration_memories`.
> - Follow the existing prompt-versioning / "never fabricate" / connection-
>   reuse conventions already locked in `docs/backendfix.md` — this task
>   doesn't touch prompts, but do not invent placeholder text for the
>   "expired" UI state; use exactly the wording specified in Step 2.3, or
>   propose an alternative and ask rather than inventing on your own.
>
> === OUTPUT ===
> Before writing significant code, report: (1) your Step 1 confirmation
> findings, (2) any place the real current code has drifted from this plan's
> assumptions and how you're adjusting, (3) any remaining ambiguity. Then
> implement, run the real verification steps above (not just unit tests),
> and update `docs/backendfix.md` with a dated Change Log entry covering what
> changed, what was verified, and what a future task needs to know — matching
> the existing entries' format.
