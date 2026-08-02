# Pixel-Perfect Frontend Integration — What Was Connected

Companion to `PIXEL_PERFECT_CLONE_INTEGRATION_PLAN.md` (the analysis). This is
the record of what was actually built, what each feature is wired to, and what
is deliberately not there.

**Date:** 2026-07-31 · **Branch:** `Samved` · **State:** all changes staged, nothing committed.

**Tie-breaker applied throughout:** where the new design and the existing app
disagreed, the new design won. Where the new design simply had no opinion
(marketing site, per-run detail, shadow deep-dive, corpus browser), the
existing surface was kept and restyled.

---

## 1. Verification summary

| Check | Result |
| --- | --- |
| `npm run typecheck` (turbo, 2 packages) | **pass** |
| `npm run lint` | **0 errors** (warnings only, all pre-existing patterns) |
| `next build` production | **pass** — 16 routes, incl. both new ones |
| `pytest backend/tests/unit` | **33 passed** (covers the changed list/owner-scoping path) |
| Live click-through, all 8 dashboard surfaces | **pass**, 0 unexpected console errors |
| Live create → discover → predict → approve | **pass** against real CockroachDB Cloud + Bedrock |
| Marketing site `/` still renders | **pass** |

Backend ran on `127.0.0.1:8003` (the port `.env.local` names) against the live
CockroachDB Cloud cluster with AWS, Step Functions and Bedrock all healthy.

---

## 2. Backend work (unblocked the design's data needs)

### 2.1 Widened `MigrationRunSummaryResponse`
`backend/app/schemas/migration_run.py`, `repositories/migration_run_repository.py`

The design's history table wants duration, risk, confidence, shadow outcome,
approver and graded state per row. None were on the list response, so rendering
one page meant ~6 extra requests per row.

Added, flattened from the run's children: `compatibility_risk`,
`confidence_score`, `approval_decision`, `approver_identity`, `approved_at`,
`actual_duration_seconds`, `actual_storage_mb`, `execution_success`,
`execution_timed_out`, `outcome_class`, `scalar_accuracy_score`, `is_graded`,
`shadow_status`, `shadow_provider`, plus a computed `shadow_outcome`
(`pass|warn|fail|null`) derived **only** from measured facts — execution
success, timeout, cluster failure, grader outcome class. Never from risk or
confidence.

Loaded through a new narrow `load_summary_children` path: one batched
`selectinload` per relationship for the whole page — **4 extra queries per
page, not 4 per row.**

Verified live:
```
13d65d57 | risk: high | conf: 0.68 | duration: 5.4174s | approver: user_3H7a…
         | outcome_class: clean_ok | is_graded: true | shadow_outcome: pass
```

### 2.2 `GET /runs/activity`
`backend/app/services/activity_feed.py`, route in `api/routes/runs.py`

Merged, reverse-chronological, owner-scoped feed. One `UNION ALL` over real
persisted timestamps: run created, prediction written, memory retrieved,
decision recorded, shadow started, shadow measured, grade written, memory
stored. Excludes the reserved corpus identity and chaos/debug runs, matching
the Recent list's population. **Nothing is synthesized** — a stage that never
happened contributes no row.

Route is registered before `/runs/{run_id}` so `activity` isn't parsed as a UUID.

### 2.3 Retrieval aggregates on `explainability.memory`
`backend/app/prediction/memory.py`, `memory/retrieval.py`

`MemoryRetrievalResult.retrieval_aggregates()` adds `graded_count`,
`ungraded_count`, `succeeded_count`, `failed_count`, `success_rate`,
`mean_actual_duration_seconds`, `duration_sample_size`, `top_similarity`,
`mean_similarity`. `RetrievedMemory` now carries `outcome_class` and
`execution_success` so this can be computed honestly.

**Integrity rule:** rates cover graded shadow runs only. Open-source documented
incidents and synthetic seed rows land in `ungraded_count` and are excluded, so
a corpus of incidents can never read as a 100% success record. Verified live —
5 memories retrieved, all ungraded, `success_rate: null`.

### 2.4 Plumbing
- `openapi.json` regenerated from the live server: **27 → 33 routes**. It was
  stale by every `/auth/*` route, `demo-with-db`, `abort-workflow`,
  `teardown-now`, the SSE stream and `corpus-identity`. `gen:api` re-run.
- `listRuns()` now exposes the backend's existing `status` filter (one line;
  the decision queue needed it).
- Removed the stray root `@clerk/nextjs` dependency that pinned 7.6.1 against
  the app's 6.39.6 — now a single resolved version.
- `run_server.py` takes a port (`argv[1]` or `API_PORT`), so the API can be
  started on whatever `NEXT_PUBLIC_API_BASE_URL` names.
- `.playwright-mcp/` and `debug-*.log` gitignored and untracked (~60 files).

---

## 3. Design system

`packages/ui/src/styles/globals.css`, `packages/ui/src/components/ui-kit.tsx`

- Light tokens ported **verbatim** from the design source: warm off-white
  surface, burnt-orange `oklch(0.5534 0.1739 38.4)` primary, 8px radius,
  `section-label` utility.
- The design ships **no dark theme**, so one was authored: same hues, inverted
  lightness, primary lifted to stay legible on dark.
- The design uses raw Tailwind palette classes (`emerald-50`, `amber-200`,
  `red-600`…) for pass/warn/fail/shadow/model. Those are fixed light-mode
  colours, so they were replaced by semantic `--tone-*` tokens with light and
  dark values. `--oracle-*` are kept as aliases over them, so all existing
  dashboard code that references them keeps working and now theme-adapts.
- Workspace is **light-first**; dark is an explicit per-user opt-in
  (`theme-provider.tsx` `routeDefault`). Previously `/dashboard` defaulted dark,
  which would not have matched the design at all.
- New `ui-kit`: `PageHeader`, `Panel`, `Label`, `StatusPill`, `SqlBlock`,
  `ToneDot`, `Stat`, `EmptyNote`, `ErrorNote`, `toneText`, `statusMeta`.
  `StatusPill` maps **real** enum values (`pending | predicting |
  awaiting_approval | running | completed | failed`, plus approval decisions and
  shadow lifecycle states) — not the design's invented display strings.
- `motion` added to `packages/ui` deps (the primitives animate).

---

## 4. Feature-by-feature: what is connected to what

### Sidebar — `components/app-sidebar.tsx`
Design look, inside the existing `SidebarProvider` so collapse and the mobile
sheet still work.

| Element | Source |
| --- | --- |
| Nav sections (Overview / Migrations / Intelligence) | static, `usePathname()` for active state |
| **"Current Migration" badge** | `GET /runs?status=awaiting_approval&exclude_kinds=chaos,debug` → `total` |
| **"Agent Memory" badge** | `GET /memories` → `total` (verified live: **16**) |
| Owner identity block | Clerk `useUser()` — replaced the hard-coded "Samved Mamillapalli" |
| Collapse chevron | wired to the real `toggleSidebar()` (non-functional in the design) |

Badges render nothing at all when the count is zero or unavailable.

### Overview — `app/dashboard/page.tsx`

| Panel | Source |
| --- | --- |
| System Health ×4 (API / Shadow / Predictions / Memory) | `GET /health` → `status`, `integrations.sfn_ready`, `integrations.bedrock_configured`; **Memory** from `GET /memories/health` → `healthy` |
| Current Migration (SQL, stage, risk, confidence, measured duration) | pinned run via `oracle:current_run_id`, else oldest awaiting decision, else newest |
| Next Action strip | derived from `status` + `policy_decision` |
| **Decision Queue** + count | `GET /runs?status=awaiting_approval` — each row links through and pins the run |
| **Recent Activity** | `GET /runs/activity?limit=6` — real events, real timestamps |
| AI Insight | `memories/health.corpus_ready_count` + `metrics.migration_success_rate`; states plainly when there isn't enough evidence |
| Latest Migration + Recent list | `GET /runs?limit=5&exclude_kinds=chaos,debug` |
| Accuracy "Graded" | `metrics.scalar_accuracy_trend.length` |
| Migration Success Rate | `metrics.migration_success_rate` |
| Approval Decisions ×4 | `metrics.approval_breakdown` (1:1 with the design's four tiles) |
| Memory ready/pending | `metrics.memory_corpus` |

### Past Migrations — `app/dashboard/migrations/history/page.tsx`

| Element | Source |
| --- | --- |
| Accuracy Summary ×4 | `GET /runs` `total`; `metrics.scalar_accuracy_trend`; `migration_success_rate`; `approval_breakdown.cancel` |
| **Daily Volume chart** | bucketed client-side from `created_at`. The design's unlabelled `a`/`b` series became real categories: **succeeded** vs **failed-or-cancelled**, with a legend |
| Search / risk / outcome / approver filters | client-side over the loaded page (the API has no such params) — the footer says so explicitly rather than implying global filtering. Approver options are built from the data |
| Table: SQL/Table, Executed, Duration, Risk, Confidence bar, Shadow, Outcome, Approver, Graded | **all from the widened summary** (§2.1). Table name parsed from SQL via `primaryTableName()` |
| Pagination | server-side `limit`/`offset`/`total`, with ellipsis for long ranges |

Columns with no data yet render `—`, never a zero or a guess.

### Current Migration — `app/dashboard/migrations/current/`
Restyled into `Panel`/`Label`/`StatusPill`. **Every handler preserved**:
create, discover (+400 ms `pipeline-progress` poll), predict (+poll,
`AbortController` stop), approve, start-workflow, abort-workflow, sync-workflow
polling, demo-DB, connect-DB fields with the GRANT/REVOKE helper, the
unknown-table SQL warning, and the **override-rationale gate** required when
`policy_decision === "block"`.

New **Migration Details** grid. The design's grid had "Index Type" and "Lock
Mode" — neither exists anywhere in this system, so they were replaced with
fields that do: Stage, Risk, AI Confidence, Est. Duration, Est. Storage, Target
Table, Estimated Rows, Statement Types, Scale Tier, Policy.

Approval buttons restyled to the design's three, mapped to the real enum:
**Approve → `proceed`**, **Accept plan — skip shadow → `accept_recommended`**,
**Reject → `cancel`**. Verified live: the recorded approval row shows
`decision: proceed`, real approver identity, real timestamp.

Prediction-vs-actual uses the real `mapComparisons()` rows (Duration, Storage
with band checks), not the design's invented Lock time / Replica lag.

### New Migration wizard — `app/dashboard/migrations/new/page.tsx` *(new route)*
Five steps on the real `POST /runs` → `POST /discover` → `POST /predict` chain,
with live `pipeline-progress` bars on both long operations.

**Step order changed deliberately** to `SQL → Connect → Schema → Columns →
Review`. The backend cannot discover without a run and cannot create a run
without SQL, so the design's SQL-last order would have required creating a
placeholder run — inventing a migration the user never wrote.

**The design's "Preview — first 5 of 20 rows" step is not reproduced.**
Discovery is metadata-only and read-only by design; the product promise is that
customer rows are never read. There is no honest source for it. It is replaced
by a Review step over what discovery actually returned.

Connect offers three tabs: discrete connection fields (composed into a
`postgresql://…` URL client-side), paste-a-URL / Secrets-Manager ARN, and the
demo database. MySQL is shown as **unsupported** rather than offered and then
failing — `schema_analysis` is postgres-wire only.

### Agent Memory — two pages, deliberately
The design's `/agent-memory` and the existing corpus browser answer different
questions, so both exist.

**`/dashboard/migrations/current/memory`** *(new)* — "why is the AI confident
about *this* run":

| Element | Source |
| --- | --- |
| Confidence ring | `explainability.confidence.confidence_score`, with "clamped from X%" when reduced |
| Similar migrations | `explainability.memory.retrieved_count` |
| Success rate / Avg runtime / Failures | the new aggregates (§2.3) |
| "Why the AI reached this confidence" | built from **real signals**: retrieval strength, each confidence clamp with its stated reason, model-flagged uncertainty notes |
| Most similar migration + other matches | retrieval hits with real similarity scores and graded-vs-corpus provenance |
| View More | retrieved-set breakdown, retrieval attribution, corpus counts, vector-index note |

Verified live: ring 47% "clamped from 72%", 5 similar, success rate **—** with
"no graded matches" (rather than a fabricated 97.2%), avg runtime 10m 3s across
5, top match 52% badged "not graded".

**`/dashboard/memory`** — corpus browser, restyled: per-memory owner, tier,
type, embedding status, `embed_text` viewer, corpus-vs-graded badges, source
links, corpus health banner.

### Settings — `app/dashboard/settings/page.tsx`
Design layout; only backed controls.

Kept/real: signed-in identity (Clerk), owner identity, theme (light/dark,
persisted per user), execution policy **reported** from `/health` (shadow
execution, AI prediction + model id, manual approval always-on, shadow
provider), connection secret ARN, API base URL, CockroachDB version, corpus
counts.

**Not built, and why:** workspace name, email/Slack alerts, confidence
threshold and "clear agent memory" have no backing entity, service or endpoint.
**Auto-approve low risk was deliberately omitted, not merely unimplemented** —
a mandatory human gate is the product's thesis.

### Shadow surfaces
- `ShadowExecutionWindow` minimized state restyled into the design's floating
  **Shadow Watch** pill (dark slab, status dot, expand + dismiss). Values are
  measured only: real provider/region, real duration, real rollback/timeout
  state. The expanded state keeps the full live view (the design has no design
  for it).
- `/current/shadow` and `/dashboard/migrations/[id]` sections moved onto the
  new `Panel`/`Label` chrome. SSE (`useShadowStream`), teardown control,
  cluster comparison, event log and **model traces** all untouched.

### Chrome
`DashboardHeader` reduced to mobile-only — the design has no top bar, and on
desktop the sidebar is always present. Sign-out lives in the sidebar's Settings
menu.

---

## 5. Bugs found and fixed during live testing

1. **Sidebar hydration mismatch** — Clerk resolves client-side, so a "Not
   signed in" placeholder was swapped for the real email on hydration. Now
   gated on `isLoaded`.
2. **Stale header status** — Current Migration kept showing "Waiting for a
   migration…" over a loaded run. Now set from `decisionHeadline(run)`.
3. **Wrong confidence-clamp wording** — the per-run memory page said
   "Confidence raised by 0.1". The backend records each clamp as a positive
   magnitude *subtracted* from the raw score (0.72 − 0.10 − 0.15 = 0.47), so
   positive always means reduced. Corrected, and toned as a warning.
4. **Similarity bar colour** — the top match rendered green even when badged
   "not graded". Now amber for ungraded matches.
5. **Duplicate chart axis ticks** — a 0–1 range rendered `1,1,1,0,0`. Now
   distinct integer ticks.
6. **Noisy table timestamps** — rows older than 48 h fell back to a full locale
   string. Now stable `YYYY-MM-DD` + `HH:MM`.

---

## 6. Known environment issues (not code)

1. **The demo database credential is stale.** `.judge_ro_database_url` exists
   but the cluster rejects it — the wizard's "Demo database" tab surfaces
   *Authentication failed against the database* (which is `discoverErrorHint`
   working correctly). Refresh it via `backend/scripts/prepare_judge_demo_db.py`
   to make that path usable again.
2. **Production build needs Clerk keys.** `.env.local` only sets
   `NEXT_PUBLIC_API_BASE_URL`; dev uses Clerk's keyless mode, which prerendering
   can't use. `next build` fails on `/dashboard/memory` without
   `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` + `CLERK_SECRET_KEY`. **Pre-existing**,
   not a regression — supplying them makes the build pass.
3. **Two test runs were created** in the live database while verifying:
   `863e8740…` (standard, discovery rejected — it correctly refused a writable
   credential) and `833f4998…` (debug, predicted + approved, awaiting shadow
   start). The first will appear in Past Migrations as PENDING; there is no
   delete endpoint.

---

## 7. Not done

- **A live shadow run was not provisioned.** Approval was verified end to end
  and the Start control renders, but clicking it provisions a real CockroachDB
  Cloud cluster at real cost. That pipeline was not modified by this work and a
  full run (shadow → grade → memory) already succeeded on it earlier today.
- **Route prefix kept as `/dashboard/*`.** The design's flat routes (`/`,
  `/past-migrations`, …) would displace the marketing landing at `/`. Nothing
  about the design is lost by the prefix.
