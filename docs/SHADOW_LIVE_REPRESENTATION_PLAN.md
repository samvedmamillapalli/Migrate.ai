# Shadow Cluster Live Representation — Planning Doc

Status: **draft for discussion** — not yet approved, nothing in this doc has been implemented.
Owner: Samved
Scope: how the app represents *live* shadow-cluster state to the user, end to end (data model → transport → UI).

---

## 1. Why this doc exists

The shadow-cluster system (provision → seed → migrate → measure → destroy) is functionally complete and demo-proven (`docs/PHASE_7_SHADOW_CLUSTERS.md`, `demo/SHADOW_PROOF.md`). But the *representation* of that live process — what the user sees while it's happening — was built incrementally on top of a generic REST-polling hook and a loose JSONB timing bag. It works, but it wasn't designed as a "watch a real cluster come alive and disappear" experience. This doc is step one of doing that intentionally: understand what exists, look at how comparable products represent similar processes, and lay out options before writing code.

Nothing here is committed. Section 7 has concrete questions that need your answers before a plan gets picked and executed.

---

## 2. Current state (verified against the code)

### 2.1 Data model

`backend/app/database/models/shadow_cluster.py` — one row per migration run (1:1 via unique FK):

| Field | Type | Notes |
|---|---|---|
| `status` | enum | `provisioning → ready → seeding → migrating → destroying → destroyed`, or `failed` from any stage |
| `cluster_id` / `cluster_name` | str, nullable | set once the provider returns an id; name is app-tagged, used by the sweeper |
| `provider` / `region` / `scale_tier` | str | e.g. `cockroachdb_cloud`, `us-east-1`, `small/medium/large` |
| `stage_timings` | **JSONB, untyped** | free-form dict — different Lambda handlers merge in different keys: `provision_ms`, `ready_ms`, `seed_ms`/`load_ms`, `migrate_ms`, `teardown_ms`, plus later-merged `job_watch` (array of `SHOW JOBS` rows) and `cockroachdb_tools` (attribution string) |
| `error_message` | text | set on failure |
| `expires_at` / `destroyed_at` | datetime | sweeper deadline / actual teardown time |

The JSONB bag is the single biggest structural weak point (detail in §4).

### 2.2 Backend orchestration

- `backend/app/shadow/orchestrator.py` — `ShadowClusterOrchestrator.run_lifecycle()` runs the whole thing in-process for local/engineer paths.
- **Production path is AWS Step Functions** (`infra/stepfunctions/migration_workflow.asl.json`): `DiscoverSchema → ProvisionShadowCluster → LoadSchema → ExecuteMigration → CollectMetrics → PersistResults → Mark(Succeeded|Failed) → Cleanup`. Each Lambda handler (`backend/app/lambdas/handlers/*.py`) writes status transitions + `stage_timings` merges to the DB via `ShadowClusterService`.
- `backend/app/shadow/job_watch.py` — snapshots `SHOW JOBS` on the *shadow* cluster during migration; this is the one place the app surfaces a genuinely CockroachDB-native live signal instead of a synthetic timer.
- Concurrency cap of 2 concurrent shadow clusters (`backend/app/shadow/concurrency.py`), invisible to the frontend today — a queued run just shows "provisioning" with no indication it's actually waiting on a slot.

### 2.3 API surface

`backend/app/api/routes/runs.py`:
- `POST /runs/{id}/start-workflow`, `/sync-workflow`, `/abort-workflow` — SFN control plane.
- `GET /runs/{id}/shadow-cluster` — **read-only**, returns `ShadowClusterResponse` (`backend/app/schemas/observability.py:76-112`): the full row above, JSON.
- `GET /runs/{id}/execution-result` — measured actual duration/storage/success once done.

No streaming endpoint exists anywhere in the backend. Everything is request/response.

### 2.4 Frontend

- `frontend/oracle/apps/web/lib/api/poll.ts` — `usePolling()`, the **only** live-update mechanism in the app: interval polling (1.5–2.5s), backs off to 8s after 60–120s, hard ceiling 30 min, pauses on tab-hidden. No WebSocket, no SSE, anywhere.
- `frontend/oracle/apps/web/lib/api/map-run.ts:682` — `mapShadowLiveStages()`: on every poll, re-derives a fixed 6-step UI timeline from `status` + `stage_timings`, guessing at timing keys per stage (`timingKeys` table at line 717 tries 2-5 aliases per stage because handlers aren't consistent about naming).
- `frontend/oracle/apps/web/components/shadow-live-panel.tsx` — the actual UI: a vertical step list (dot + label + "now"/"done" badge + duration + one-line hint), a small "Cluster" key/value box (status, region, scale, torn-down time), an error line, and a prediction-vs-actual comparison block. Reused in 3 places (dedicated shadow page, floating global watch window, historical run detail page).
- `frontend/oracle/apps/web/components/shadow-execution-window.tsx` + `shadow-watch-context.tsx` — a dismissible/minimizable floating panel, persisted across navigation via `localStorage`, so a shadow run stays visible while the user does other things.
- Run detail page (`app/dashboard/migrations/[id]/page.tsx:593-636`) also renders "Jobs observed" from `stage_timings.job_watch` and a raw stage-timings key/value dump for anything not otherwise mapped.

### 2.5 What this adds up to

The current representation is: **a 6-step vertical checklist with a spinner-equivalent (pulsing amber dot) on the active step, a duration once it's done, and a small facts panel.** It is functional and honest (no fake numbers), but it's a generic "job progress" widget — it doesn't lean into anything CockroachDB-specific or communicate the thing that's actually interesting: *a real, billable, ephemeral cluster is alive right now, doing a real migration, and here's the blast radius as it's measured, not guessed.*

---

## 3. External research

### Progress/timeline UI patterns
- Determinate vs. indeterminate progress: use a step/percentage indicator only when remaining work is actually knowable; otherwise an indeterminate indicator or real counters ("step 3/6", "record 5,200/10,000") read as more honest than a fake smooth bar. Naive linear ETAs are a known trust-killer. ([How-To Geek: Why Are Progress Bars So Inaccurate](https://www.howtogeek.com/139118/htg-explains-why-are-progress-bars-generally-inaccurate/), [codegenes.net](https://www.codegenes.net/blog/how-to-show-an-informative-real-time-progress-data-during-long-server-process/))
- Vercel's deployment log UI (closest analog to "watch infra come up") is step-based with color-coded status per phase and a follow-mode live tail, not a percentage bar — reinforces that infra-provisioning UX is usually communicated as **discrete phases + live log/detail**, not smooth progress. ([Vercel build logs](https://vercel.com/docs/deployments/logs))
- CockroachDB's own DB Console models cluster activity as a **Jobs page** (list of jobs with type/status/fraction-complete where knowable) plus a **Metrics/Overview dashboard** of time-series graphs — i.e., CockroachDB's own convention for "what's happening right now" is job rows, not a single progress bar. Since the app already samples `SHOW JOBS` (`job_watch`), leaning further into this is the most "native" direction available. ([DB Console Overview](https://www.cockroachlabs.com/docs/stable/ui-overview), [Jobs Page](https://www.cockroachlabs.com/docs/cockroachcloud/jobs-page), [SHOW JOBS](https://www.cockroachlabs.com/docs/v26.2/show-jobs))

### Transport: polling vs SSE vs WebSocket
- Consistent guidance across sources: **SSE is the right default for one-directional server→client live updates** (dashboards, log tailing, status streams) — simpler to operate than WebSocket, works over plain HTTP/2, browser auto-reconnects for free via `EventSource`. WebSocket is for bidirectional/low-latency needs (chat, collaborative editing) which this isn't. Polling remains fine when near-real-time is acceptable and infra simplicity matters most. ([SSE vs WebSockets vs Polling — Medium](https://medium.com/@pottavijay/server-sent-events-sse-vs-websockets-vs-polling-choosing-the-right-real-time-solution-aa36a58bab9f), [oneuptime.com SSE vs WS](https://oneuptime.com/blog/post/2026-01-27-sse-vs-websockets/view), [designgurus.io](https://www.designgurus.io/answers/detail/what-are-the-different-techniques-for-real-time-updates-websockets-vs-server-sent-events-vs-long-polling))
- FastAPI has first-class support for this via `sse-starlette`'s `EventSourceResponse` wrapping an async generator — small addition, no new infra dependency (no Redis/pubsub required at this scale, since it's one shadow run per user session in practice, and the concurrency cap is only 2). ([sse-starlette on GitHub](https://github.com/sysid/sse-starlette), [FastAPI SSE tutorial](https://fastapi.tiangolo.com/tutorial/server-sent-events/), [Pulkit: FastAPI SSE](https://www.pulkit.blog/blogs/sse-with-fastapi))

### Ephemeral-database-specific UX
- Neon and PlanetScale both surface branch/ephemeral-environment lifecycle as **named states with a visible timestamp and an explicit "this costs nothing once torn down" framing** — the pattern in this space is to make the *ephemerality itself* a visible, reassuring fact, not just a background detail. PlanetScale layers a **schema diff view** into its deploy-request flow before/alongside execution. Both are relevant precedents: (a) make lifecycle state emotionally legible ("this is temporary, it's already gone"), (b) pair execution with a diff, not just a timer. ([Neon ephemeral environments](https://neon.com/branching/ephemeral-environments), [PlanetScale branching](https://planetscale.com/docs/postgres/branching))

### Schema-migration-specific tooling
- gh-ost exposes a running "progress" heartbeat (rows processed / estimated rows) rather than a coarse phase list — where the app *can* get a real numerator/denominator (e.g. rows copied during seed, or bytes migrated), a counter reads as more trustworthy than a phase name. Neither gh-ost nor pt-osc ship a dashboard themselves — dashboarding is left to the operator, which is exactly the gap this project already fills. ([gh-ost](https://github.com/github/gh-ost), [Bytebase gh-ost vs pt-osc](https://www.bytebase.com/blog/gh-ost-vs-pt-online-schema-change/))
- Bytebase/Atlas both treat the **schema diff** as a first-class artifact shown alongside (not instead of) execution status — reinforces pairing the live timeline with a concrete "here's exactly what changed" view. ([Bytebase vs Atlas](https://www.bytebase.com/blog/bytebase-vs-atlas/))

---

## 4. Gaps identified (backend + frontend, verified)

1. **No push channel.** Every live surface polls. At 1.5–2.5s intervals this is fine for a demo but is the main thing standing between "live-ish" and actually live, and it's the highest-leverage change available (see SSE research above).
2. **`stage_timings` is an untyped JSONB bag with alias-guessing on the frontend** (`map-run.ts:717`, 2-5 candidate keys per stage because Lambda handlers were written independently). Any new stage or metric requires updating a guess-table on the client instead of a typed contract.
3. **No queue/wait visibility.** The concurrency cap (2 shadow clusters) is enforced server-side but invisible client-side — a queued run just looks like "provisioning" is stuck.
4. **`job_watch` (the one CockroachDB-native live signal) is under-leveraged** — it's rendered as a static list on the historical run-detail page only, not surfaced in the live panel or the floating watch window, and per `demo/SHADOW_PROOF.md` may require a redeploy to even be populated in prod.
5. **No real progress numerator for the long-running stages.** "Seeding" and "migrating" show only a pulsing dot + elapsed-adjacent hint text, no rows-copied / bytes-applied / fraction-complete, even though CockroachDB job status (`SHOW JOBS`, `crdb_internal.jobs`, `fraction_completed`) could supply this for schema-change jobs specifically.
6. **No diff / "what's actually being tested" context in the live view.** The user watches steps tick by without seeing the migration SQL or a schema diff alongside it — external precedent (Bytebase/Atlas/PlanetScale) treats that pairing as standard.
7. **No historical/fleet view.** There's no page listing all active or recently-expired shadow clusters across runs, even though the sweeper's `list_active`/`list_expired_active` already exist server-side and aren't exposed via any route.
8. **Ephemerality isn't made emotionally legible.** Unlike Neon/PlanetScale, there's no explicit "this cluster no longer exists / cost $0 ongoing" framing once torn down — currently just `destroyed_at` in a key/value row.

---

## 5. Design directions (not yet chosen — see §7)

These are options, not a decision. They're roughly ordered cheap→expensive and are independently adoptable (you could take #1 and #2 without #4).

### A. Transport: REST polling → SSE
Replace `usePolling()` + repeated `GET /shadow-cluster` calls with one `GET /runs/{id}/shadow-cluster/stream` SSE endpoint (`EventSourceResponse` wrapping a generator that polls the DB server-side every ~1s and only emits on change — cheap since it's in-process, no new infra). Client swaps to `EventSource`, same rendering code downstream. Falls back to existing polling automatically if `EventSource` fails (easy to keep the old hook as a fallback path). This is the single highest-leverage change per the research above and touches the fewest files (`poll.ts` → `stream.ts`, one new route).

### B. Typed stage-timing contract
Replace the free-form `stage_timings` JSONB alias-guessing with an explicit `StageTimings` Pydantic/TS type (`provision_ms`, `ready_ms`, `seed_ms`, `migrate_ms`, `teardown_ms` as real optional fields, `job_watch`/`cockroachdb_tools` as named sub-objects) — a schema migration on the JSONB *shape* (not a DB column migration, since it's already JSONB) plus updating the 5 Lambda handlers to write consistent keys and deleting the alias table in `map-run.ts`.

### C. Surface job-level progress
Pull `fraction_completed` (where CockroachDB reports it for schema-change jobs) into `job_watch` and render it as a real progress bar/percentage on the "migrating" step specifically, instead of a generic pulsing dot — this is the one stage where CockroachDB itself can tell us real progress, not just elapsed time.

### D. Queue/admission visibility
Add a `queued` pseudo-state (derived client-side from "run approved + workflow started but no `shadow_clusters` row yet + `count_active >= cap`") with copy like "Waiting for a shadow-cluster slot (2 running)" instead of a misleading "provisioning" dot.

### E. Pair the live view with a schema diff
Show the migration SQL / affected-table diff alongside the live timeline (collapsed by default, expandable) so the user can correlate "step 4 is running" with "on *these* tables."

### F. Fleet/history view
New read-only page + route (`GET /shadow-clusters?status=active`) listing all shadow clusters across runs — mostly wiring, since `list_active`/`list_expired_active` already exist in the repository layer.

### G. Ephemerality framing
Small copy/UI change: once `destroyed_at` is set, show something explicit like "Cluster destroyed — no longer running, no ongoing cost" instead of a bare timestamp, modeled on Neon/PlanetScale's framing.

---

## 6. Suggested sequencing (if you want a recommendation)

If I had to pick a first slice: **A (SSE) + B (typed timings)** together, because B is much easier to do correctly once you're not fighting the polling hook's existing shape, and A is the change that actually makes the word "live" true rather than "live-ish." **C (job-level progress)** is the highest-impact *visual* change and the most CockroachDB-native, but depends on confirming `fraction_completed` is actually populated for the schema-change jobs this app runs (needs a quick check against a real shadow run — see Q3 below) before committing UI to it. D/E/F/G are additive polish, doable in any order after.

---

## 7. Open questions for you

1. **Transport buy-in**: Are you OK adding `sse-starlette` as a new backend dependency (small, no new infra) to move off polling, or would you rather stay polling-only for now (simpler ops, one less moving part to explain to judges) and just fix the data model (B) and add job-level progress (C) on top of polling?
2. **Deployment reality check**: `demo/SHADOW_PROOF.md` says the `job_watch` UI needs a SAM redeploy to show in production — is that redeploy already done, or does this plan need to account for redeploying the Lambda/SFN stack as part of the work?
3. **`fraction_completed` availability**: Do you know offhand whether `SHOW JOBS` / `crdb_internal.jobs` returns a populated `fraction_completed` for the schema-change statements this app runs (some CockroachDB schema-change job types don't report it), or should I spike that against a real shadow cluster before designing direction C around it?
4. **Scope for this pass**: Is this doc meant to produce a full redesign of the shadow representation (all of A–G), or do you want me to scope down to 1-2 directions for an actual implementation plan next? Given the "plan it out, don't build yet" framing, I'd lean toward you picking 2-3 of A–G now and I turn those into a real implementation plan (files to touch, migration steps, rollout order) as a follow-up.
5. **Fleet view need (F)**: Is a cross-run "all active/expired shadow clusters" admin view actually useful for your demo/judging narrative, or is it out of scope (nice-to-have, not core to "watch this run's shadow cluster")?
6. **Any APIs to pull in?** None of directions A-G require new *external* APIs — everything comes from data already available in CockroachDB Cloud / SFN / the existing DB. If you had something specific in mind (e.g. CockroachDB Cloud's own metrics API, `crdb_internal` tables beyond jobs, AWS CloudWatch for Lambda-side timing), name it and I'll fold it into the plan.
