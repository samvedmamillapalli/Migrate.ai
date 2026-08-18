# Pixel-Perfect Clone → Migration Oracle: Full-Stack Integration Reference

**Status:** Planning / reference document. No code changed by this document.
**Written:** 2026-07-31, against branch `Samved` @ `7774a70` + the pull that added `pixel-perfect-clone-64427-main/`.
**Audience:** whoever (human or agent) performs the integration. Read §9 before writing code.

---

## 0. TL;DR — the five things that matter

1. **The new frontend is 100% static.** `pixel-perfect-clone-64427-main/` contains **zero** network calls, zero `fetch`, zero API client, zero auth. Every number, SQL string, table, chart bar and timeline entry is a hard-coded literal in `src/lib/migration-data.ts` or inlined in the route file. It is a **visual design**, not a partially-wired app.
2. **The current frontend↔backend wiring is essentially complete** — 24 of 30 backend endpoints are consumed, and the 6 that aren't are deliberate (debug/legacy/duplicate). See §6 for the endpoint-by-endpoint audit. **Confirmed: yes, the present frontend and backend are hooked up end to end.**
3. **The two frontends are not the same product.** The clone is a *5-page workspace*. The current app is a *5-page workspace + marketing site + Clerk auth + a shadow-execution deep-dive subsystem*. Roughly **40% of what exists full-stack today has no home in the clone's design** (§8.2).
4. **Roughly 35% of what the clone renders has no backend behind it** (§8.1) — most importantly: the settings/policy engine, the 20-row data preview, the named shadow "checks", the daily-volume chart, per-run duration/approver/graded columns in the history table, and the "Defer" approval decision.
5. **The clone is TanStack Start + Vite. The current app is Next.js 16 App Router + Turborepo + Clerk.** Do **not** port the runtime. Port the *markup and design tokens* into the existing Next.js app. §9 explains why in detail.

---

## 1. Repository topology

```
CockroachDB_hackathon/
├── backend/                          FastAPI + SQLAlchemy async + CockroachDB (the real backend)
│   └── app/
│       ├── api/routes/               auth.py, health.py, runs.py, memories.py   ← ALL HTTP surface
│       ├── schemas/                  Pydantic request/response contracts
│       ├── services/                 orchestration (prediction, approval, workflow, grading…)
│       ├── shadow/                   shadow-cluster provisioning, MCP, schema diff, row samples
│       ├── prediction/ policy/ grading/ memory/     the AI + deterministic layers
│       └── lambdas/handlers/         Step Functions handler chain
├── frontend/oracle/                  ← THE CURRENT PRODUCTION FRONTEND (Next.js 16 monorepo)
│   ├── apps/web/                     the Next.js app
│   └── packages/ui/                  shared shadcn/base-ui component package (@workspace/ui)
├── pixel-perfect-clone-64427-main/   ← THE NEW DESIGN (TanStack Start + Vite, static)
├── framer-to-next-dream-main/        (a separate, earlier design import — not in scope here)
├── infra/                            SAM templates for the Step Functions workflow
└── docs/                             this file lives here
```

---

## 2. The new frontend — complete inventory (`pixel-perfect-clone-64427-main/`)

### 2.1 Stack

| Thing | Value |
| --- | --- |
| Framework | **TanStack Start** (`@tanstack/react-start` 1.168) + **TanStack Router** 1.170 (file-based, `src/routes/`) |
| Bundler | **Vite 8** via `@lovable.dev/vite-tanstack-config` (opinionated wrapper; adds tailwind, tsconfigPaths, nitro, React plugins automatically) |
| React | 19.2 |
| Styling | **Tailwind CSS v4** (`@import "tailwindcss"`, `@theme inline`), tokens in `src/styles.css` |
| Components | shadcn/ui "new-york", **48 files** in `src/components/ui/` (Radix-based) |
| Data layer | `@tanstack/react-query` v5 is **installed and a `QueryClient` is provisioned in `router.tsx` + provided in `__root.tsx`, but never used for a single query.** |
| Animation | `motion` (Framer Motion v12) |
| Charts | `recharts` installed, **never imported** (the volume chart is hand-rolled divs) |
| Icons | `lucide-react` 0.575 |
| Origin | Lovable project `dfdf27ce-25b9-43b8-b833-2c7474ed3d30`, cloning `https://migrationoracle-xmtku50.public.builtwithrocket.new/` |

### 2.2 Files that matter (everything else is stock shadcn)

| File | Lines | What it is |
| --- | --- | --- |
| `src/routes/__root.tsx` | 140 | Root shell: `<html>`, head/meta, `QueryClientProvider`, `<AppSidebar/>`, `<main className="md:pl-56">`, `<Outlet/>`, `<ShadowWatch/>`, 404 + error boundaries |
| `src/routes/index.tsx` | 283 | **Overview** page |
| `src/routes/new-migration.tsx` | 591 | **New Migration** 5-step wizard |
| `src/routes/current-migration.tsx` | 274 | **Current Migration** review + approval |
| `src/routes/past-migrations.tsx` | 342 | **Past Migrations** table + filters + chart |
| `src/routes/agent-memory.tsx` | 219 | **Agent Memory** confidence explainer |
| `src/routes/settings.tsx` | 201 | **Settings** |
| `src/components/app-sidebar.tsx` | 106 | Fixed 224px (`w-56`) sidebar, hidden below `md` |
| `src/components/ui-kit.tsx` | 92 | `PageHeader`, `Panel`, `Label`, `StatusPill`, `SqlBlock` — the design primitives |
| `src/components/shadow-watch.tsx` | 63 | Floating bottom-right toast/expander |
| `src/lib/migration-data.ts` | 328 | **All mock data** |
| `src/styles.css` | 109 | Tailwind v4 theme, oklch tokens, `@utility section-label` |

### 2.3 Design tokens (`src/styles.css`) — port these verbatim

```
--radius: 8px
--font-sans: "Geist"          --font-mono: "Geist Mono"      (loaded from Google Fonts in __root)
--background:  oklch(0.9845 0.0026 106.45)   warm off-white
--foreground:  oklch(0.2161 0.0061 56.04)    warm near-black
--card:        oklch(1 0 0)
--primary:     oklch(0.5534 0.1739 38.4)     ← burnt orange. THE brand colour.
--accent:      oklch(0.6461 0.1943 41.12)
--secondary:   oklch(0.9668 0.0054 95.1)
--muted:       oklch(0.9512 0.008 98.88)     --muted-foreground: oklch(0.5534 0.0116 58.07)
--border/--input: oklch(0.9218 0.0083 91.49)
--destructive: oklch(0.5771 0.2152 27.33)
--sidebar*:    same warm family
```

Plus a custom utility used everywhere:
```css
@utility section-label { font-size:11px; line-height:1; font-weight:600;
  letter-spacing:.08em; text-transform:uppercase; color:var(--muted-foreground); }
```

> ⚠️ **There is no dark theme.** `@custom-variant dark (&:is(.dark *))` is declared but **no `.dark` block exists**. The current app has a full light/dark system with a user-persisted preference. See §8.2-D.

Semantic colours are used as raw Tailwind classes throughout, **not** as tokens: `emerald-*` = pass/low-risk/success, `amber-*` = warn/medium/awaiting, `red-*` = fail/high/cancelled, `blue-*` = shadow activity, `violet-*` = AI/model activity.

### 2.4 Route-by-route: every element and its required data source

Legend for the "Backing" column: **✅ exists** = a current endpoint returns it; **🟡 derivable** = computable client-side or with a small backend addition; **❌ none** = no backend support at all today.

---

#### `/` — Overview (`index.tsx`)

| UI element | Mock value | Backing |
| --- | --- | --- |
| Header + "New Migration" CTA | — | ✅ links only |
| **System Health**: 4 dots — API, Shadow, Predictions, Memory — all hard-coded "Ready" | static | ✅ `GET /health` → `integrations.{api, sfn_ready, bedrock_configured}`. **"Memory" has no health flag in `/health`** — but `GET /memories/health` exists (🟡 second call) |
| **Current Migration** panel: SQL, `StatusPill`, stage, risk, confidence, est. duration, amber "Next Action" strip | static | ✅ `GET /runs/{id}` → `migration_sql`, `status`, `compatibility_risk`, `explainability.confidence.*`, `explainability.prediction.estimated_duration_seconds`. "Next Action" prose → 🟡 derive from `status` + `policy_decision` (`map-run.ts:decisionHeadline` already does something similar) |
| **Decision Queue** (4 rows: SQL, risk, "High/Medium confidence") + count badge | `queueItems` | 🟡 `GET /runs?status=awaiting_approval` — **but `listRuns()` in `endpoints.ts` does not expose the `status` param** even though the backend supports it (`runs.py:82`, alias `status`). One-line client fix. Per-row `risk`/`confidence` are **not on `MigrationRunSummaryResponse`** → needs either N× `GET /runs/{id}` or adding `compatibility_risk` + a confidence field to the summary schema. |
| **Recent Activity** feed (5 entries: time, kind, tone, text) | `activity` | ❌ **No activity/event-feed endpoint exists.** Nearest sources: `ShadowClusterResponse.event_log[]` (per-run, append-only), `stage_timings`, run/approval/grade `created_at`. Needs a new aggregating endpoint or client-side merge across runs. |
| **AI Insight** amber panel ("supported by 36 successful index migrations") | static | 🟡 `explainability.memory.retrieved_count` + retrieval hits from the current run |
| **Latest Migration** panel + "Set as current" + `Recent` list of 4 | `recentMigrations` | ✅ `GET /runs?limit=5&exclude_kinds=chaos,debug` — this is exactly what `app/dashboard/page.tsx` does today |
| **Accuracy**: "Graded 6" | static | ✅ `GET /runs/metrics/accuracy` → `scalar_accuracy_trend.length` |
| **Migration Success Rate** "6 / 6 · 100%" | static | ✅ same → `migration_success_rate.{numerator,denominator,rate}` |
| **Approval Decisions** 4 tiles (Proceeded / Accepted Plan / Cancelled / Awaiting Decision) | static | ✅ same → `approval_breakdown.{proceed, accept_recommended, cancel, awaiting_decision}` — **exact 1:1 match with the current dashboard** |
| **Memory** strip "36 ready · 0 pending" | static | ✅ same → `memory_corpus.{memories_ready, pending}` |

---

#### `/new-migration` — 5-step wizard (`new-migration.tsx`)

Steps: `Connect → Schema → Columns → Preview → SQL`. Local `useState` only; `setTimeout` fakes every async op.

| Step / element | Mock behaviour | Backing |
| --- | --- | --- |
| Tab: **Connect Database** vs **Upload SQL File** | local | ✅ both feasible |
| DB type cards: PostgreSQL / MySQL / CockroachDB (sets default port) | local | ⚠️ **MySQL is not supported by the backend.** `schema_analysis/` is PostgreSQL-wire only (`DatabaseConnection`, `SslMode`, default port 26257). Either drop MySQL or mark it "coming soon". |
| Discrete fields: **Host, Port, Database, Username, Password** | local | ⚠️ **Impedance mismatch.** `POST /runs/{id}/discover` takes `{connection_secret_arn?, database_url?}` — a *single URL string*. The 5 fields must be composed client-side into `postgresql://user:pass@host:port/db?sslmode=verify-full`. The current app asks for the URL directly. **Decision needed** (§10 Q2). |
| "Connect & Fetch Schema" button (1.1s `setTimeout`) | fake | ✅ real flow is `POST /runs` → `POST /runs/{id}/discover`. Note the **ordering problem**: the backend requires a *run* (and therefore SQL) to exist before discovery. The wizard collects SQL **last** (step 5). See §9.4. |
| Upload `.sql` file → `FileReader` → `sql` state, capped 4000 chars | local | ✅ purely client-side; keep as-is |
| **Step 2 — Schema**: table cards with name, "1.24M rows", "9 cols" | `schemaTables` | ✅ `MigrationRunResponse.schema_snapshot` → `schemas[].tables[]` → `{name, column_count, estimated_row_count, estimated_size_bytes}`. `map-run.ts:mapSchema()` already parses this. |
| **Step 3 — Columns**: table of Column / Type / Nullable / Key | `columnsByTable` | ✅ same snapshot → `ColumnMetadata{name, data_type, is_nullable, is_primary_key, is_unique}` + `foreign_keys[]` for `FK`. Key column = derive `PK`/`UNIQUE`/`FK`. |
| **Step 4 — Preview**: "first 5 of 20 rows", real-looking user rows | `previewRows` | ❌ **NO BACKEND SUPPORT.** Schema discovery is explicitly **metadata-only, read-only** (`schema_analysis/read_only.py`). The only row data anywhere is `ShadowClusterResponse.row_sample_before/after` — and those are **shadow-tier synthetic rows, never customer data** (documented in `observability.py`). Showing real production rows would violate the product's stated privacy guarantee ("Credentials are used only for schema introspection and are never stored"). **Recommend: cut this step, or repurpose it as a synthetic-preview labelled as such.** (§10 Q3) |
| **Step 5 — SQL**: textarea + upload + echo block + "Submit for AI Analysis" (1s fake → navigate) | fake | ✅ `POST /runs {migration_sql, owner_identity}` then `POST /runs/{id}/predict` |
| Right rail: "Secure Connection", "Supported Databases", "What happens next" (5 items, strike-through as steps complete) | static | ✅ presentational |

---

#### `/current-migration` (`current-migration.tsx`)

| UI element | Mock | Backing |
| --- | --- | --- |
| `StatusPill` "AWAITING APPROVAL" | static | ✅ `run.status` (needs a label map: `awaiting_approval` → `AWAITING APPROVAL`; `map-run.ts:statusLabel` exists) |
| Migration SQL + Copy button | static | ✅ `run.migration_sql` |
| **Next Action** prose paragraph | static | 🟡 derive from status/policy/confidence |
| **Approval Decision**: `Approve` / `Reject` / **`Defer`** | local state only | ⚠️ Backend `ApprovalDecision` enum = `proceed` \| `accept_recommended` \| `cancel`. **`Defer` has no backend equivalent** and there is no "un-decided / snoozed" state. Map `Approve→proceed`, `Reject→cancel`; **`Defer` must either be dropped or map to `accept_recommended`** (which means "keep the plan, skip the shadow" — semantically *not* "defer"). Also note the clone **omits the override-rationale flow**, which is *mandatory* when `policy_decision == "block"` (`current-migration-workspace.tsx:1329`). (§10 Q4) |
| **Shadow Execution Evidence**: "All checks passed", 3 tiles (Replica / Duration / Shadow Runs), then **6 named checks** — Lock escalation, Execution time, Deadlock detection, Row count delta, Replica lag, Memory usage — each pass/warn with prose | `shadowChecks` | ❌ **The backend produces no named check list.** What it *does* produce: `ExecutionResultResponse{success, actual_duration_seconds, actual_storage_mb, rollback_required, timed_out, error_message}`, `ShadowClusterResponse{status, stage_timings, event_log[], schema_diff, row_sample_before/after}`, `GradeResponse{*_within_band, outcome_class, high_risk_flags_present, dimension_details}`, and `shadow/blast_radius_investigator.py` (MCP tool-use traces). A checks list is **🟡 derivable** by writing an adapter (e.g. "Execution time" ← `duration_within_band`, "Row count delta" ← `schema_diff`), but *Replica*, *Shadow Runs = 3*, *Deadlock detection*, *Replica lag* and *Memory usage* have **no data source at all**. Either build them or cut them. (§10 Q5) |
| **AI Risk Analysis**: 94% confidence + 5 named risk factors with prose | `riskFactors` | 🟡 `run.risk_flags[]` gives `{rule_id, severity, explanation}` (real, deterministic, from `policy/engine.py`) and `explainability.prediction.{key_assumptions, uncertainty_notes, risk_explanation}`. Shape differs (rule ids vs. friendly names) but the content is there. Confidence ✅ `explainability.confidence.{score, raw_score, adjustments}`. |
| **Prediction vs Actual** (Runtime / Lock time / Replica lag) | static | ✅ **partially** — `map-run.ts:mapComparisons()` already builds exactly this for **Duration** and **Storage** from prediction + `ExecutionResultResponse` + `GradeResponse` bands. **Lock time and Replica lag do not exist.** Swap the rows. |
| **Migration Details** 8-field grid: Stage, Risk Level, AI Confidence, Est. Duration, Target Table, Estimated Rows, Index Type, Lock Mode | static | Mixed: Stage ✅, Risk ✅, Confidence ✅, Est. Duration ✅, Target Table 🟡 (parse SQL / `parsed_statement_types`), Estimated Rows ✅ (schema snapshot), **Index Type ❌**, **Lock Mode ❌** |
| **Activity Timeline** (4 entries, "by Shadow Engine / Agent Memory / Risk Model") | `timeline` | 🟡 `ShadowClusterResponse.event_log[]` + `stage_timings` + run timestamps. `map-run.ts:mapShadowEventLog()` and `mapLifecycle()` already do most of this. |

---

#### `/past-migrations` (`past-migrations.tsx`)

| UI element | Mock | Backing |
| --- | --- | --- |
| **Accuracy Summary** 4 tiles: Total Migrations, Graded, Shadow Pass Rate, Cancelled | static | ✅ Total = `GET /runs` `.total`; Graded = `metrics.scalar_accuracy_trend.length`; Pass rate = `metrics.migration_success_rate`; Cancelled = `metrics.approval_breakdown.cancel` |
| **Daily Migration Volume** bar chart, 7 days, two series (`a`, `b`) | `dailyVolume` | 🟡 **No endpoint.** Bucket `GET /runs` `created_at` client-side. The two series are undefined in the mock — decide what `a`/`b` mean (suggest: *completed* vs *cancelled/failed*). |
| Filters: search (SQL or table), risk, outcome, approver | client-side over mock | Search 🟡 client-side over `sql_snippet` (server has no search param). Risk ⚠️ `compatibility_risk` **not on the summary schema**. Outcome 🟡 map from `status`+approval. **Approver ❌ not on the summary schema** (`approvals` table has `approver_identity`, but the list endpoint never joins it). |
| Table columns: SQL/Table, Executed, **Duration**, **Risk**, **Confidence** (animated bar), **Shadow** (pass/warn/fail icon), **Outcome** pill, **Approver**, **Graded** badge | `pastMigrations` | ✅ SQL (`sql_snippet`), Executed (`created_at`). ❌ **Duration, Risk, Confidence, Shadow, Approver, Graded are ALL absent from `MigrationRunSummaryResponse`.** This is the single biggest backend gap in the clone: rendering this table for 50 rows currently requires **6 extra GETs per row** (`/grade`, `/execution-result`, `/approval`, `/shadow-cluster`, plus the full `/runs/{id}` for `explainability`). **Strongly recommend widening `MigrationRunSummaryResponse`** (§9.5). |
| Row checkboxes + header select-all | non-functional | ❌ no bulk action exists |
| Rows-per-page + numbered pagination | client-side | ✅ backend has `limit`/`offset` + `total` — wire server-side |

---

#### `/agent-memory` (`agent-memory.tsx`)

> ⚠️ **This page is a completely different concept from the current app's Agent Memory page.** The clone's page answers *"why is the AI confident about **this one** migration?"* The current app's page is a *corpus browser* listing all stored memories with embedding health. Both are legitimate; they are not substitutes.

| UI element | Mock | Backing |
| --- | --- | --- |
| "Corpus healthy" pill | static | ✅ `GET /memories/health` → `{healthy, problems[], total_memories, corpus_ready_count, missing_embeddings}` |
| SVG **Confidence ring** 94% | static | ✅ `explainability.confidence.score` |
| 4 stat panels: Similar migrations `36`, Success rate `97.2%`, Avg runtime `1m 58s`, Failures `1` | static | 🟡 `explainability.memory.retrieved_count` ✅. **Success rate / avg runtime / failure count *across the retrieved set* are not computed anywhere** — `retrieval.py` returns memories, not aggregates over them. Needs a small backend addition or client-side aggregation over the retrieved memory payloads. |
| "Why the AI is confident" — 4 reasons w/ ok/warn tone | `memoryReasons` | 🟡 `explainability.prediction.{risk_explanation, key_assumptions, uncertainty_notes}` + `confidence.adjustments[]` (which have `{reason_code, reason, amount}` — these map *beautifully* to the ok/warn tone list) |
| **Most similar migration**: 97% match bar, SQL, date, duration | static | ✅ retrieval hit #1 → `map-run.ts:RetrievedMemoryView{rank, similarityScore, migrationSummary, migrationRunId}` |
| **Other close matches** (2 rows, %) | static | ✅ retrieval hits #2, #3 |
| **View More** accordion: Historical runs / Learned patterns / Technical details (`work_mem = 256MB`, `lock_mode = SHARE`, `concurrently = true`) | static | 🟡 first two derivable; **the "technical details" values are pure invention — no source.** |

---

#### `/settings` (`settings.tsx`)

| UI element | Mock | Backing |
| --- | --- | --- |
| Workspace name / Owner / Contact email | uncontrolled `defaultValue` | ❌ **No workspace entity in the backend.** Owner ≈ `owner_identity` (currently localStorage, synced from Clerk in `clerk-owner-sync.tsx`). Email lives in Clerk. |
| Toggle **Shadow execution** | `useState` | ❌ no persistence. *Behaviourally* the closest thing is `approve(decision=accept_recommended)` = skip shadow, per-run. |
| Toggle **Auto-approve low risk** | `useState` | ❌ **does not exist and is a product-risk feature** — the entire premise (`BUILDING_AI_SYSTEM_THAT_DOESNT_TRUST_AI.md`) is a mandatory human gate. |
| Slider **Confidence threshold** 50–99 | `useState` | ❌ no persistence. `policy/config.py` has thresholds but they are server-side env config, not per-user. |
| Toggles **Email alerts** / **Slack alerts** | `useState` | ❌ no notification subsystem at all |
| **Current policy** summary card | mirrors local state | ❌ follows the above |
| **Danger zone: Clear agent memory** | no-op button | ❌ **no delete endpoint.** `POST /runs/memories/repair-embeddings` exists; deletion does not. |

**Every single control on this page is unbacked.** Meanwhile the current settings page has 4 *real* controls (identity, theme, API base URL display, connection-secret ARN) — **none of which appear in the clone.** See §8.2-D.

---

#### `ShadowWatch` (floating widget, `shadow-watch.tsx`)

Fixed bottom-right, dark pill, dot + "Shadow Watch" + "Finished — expand for results", expander shows `replica-03 · 1m 47s` / `0 deadlocks · no lock escalation`, dismissable.

Current-app equivalent: **`components/shadow-execution-window.tsx` (306 lines) + `shadow-watch-context.tsx` (93 lines)** — a real, live, SSE/polling-driven version of exactly this. The clone's is a static shell of it. **Keep the current logic, restyle the shell.**

---

## 3. The current frontend — complete inventory (`frontend/oracle/`)

### 3.1 Stack

| Thing | Value |
| --- | --- |
| Monorepo | **Turborepo**, npm workspaces (`apps/*`, `packages/*`) |
| App | `apps/web` — **Next.js 16.2.6, App Router**, React 19.2.4 |
| Shared UI | `packages/ui` = `@workspace/ui` — **`@base-ui/react` 1.6** (not Radix!) + shadcn 4, exports `./components/*`, `./globals.css`, `./lib/*`, `./hooks/*` |
| Auth | **Clerk** (`@clerk/nextjs` 6.39 in web, 7.6 at root — *version skew, see §9.7*), `middleware.ts` route matcher, `ClerkProvider` in root layout |
| Styling | Tailwind v4 + a full light **and dark** token set with `--oracle-*` semantic vars |
| Fonts | Geist, Geist Mono, **Bodoni Moda** (`--font-display`, used on marketing) |
| Extras | `@xyflow/react` (flow diagrams on landing), `motion`, `next-themes` |

### 3.2 Route map

| Route | File | Auth | Purpose |
| --- | --- | --- | --- |
| `/` | `app/page.tsx` | public | **Marketing landing** — `SiteHeader`, `HeroSection`, `MediaShowcase`, `PipelineSection`, `TechMarquee`, `SiteFooter` |
| `/our-journey` | `app/our-journey/page.tsx` | public | build-journal page |
| `/login/[[...rest]]` | Clerk `<SignIn>` | public | |
| `/get-started/[[...rest]]` | Clerk `<SignUp>` | public | |
| `/signup`, `/sign-in` | legacy shims | public | |
| `/dashboard` | `app/dashboard/page.tsx` (414) | **protected** | Overview |
| `/dashboard/migrations/current` | `current/page.tsx` → `current-migration-workspace.tsx` (**2086**) | protected | **The core workspace** |
| `/dashboard/migrations/current/shadow` | `current/shadow/page.tsx` (495) | protected | Shadow-execution deep dive |
| `/dashboard/migrations/history` | `history/page.tsx` (148) | protected | Past runs list |
| `/dashboard/migrations/[id]` | `[id]/page.tsx` (**866**) | protected | Per-run detail incl. **model traces** |
| `/dashboard/memory` | `memory/page.tsx` (294) | protected | Corpus browser |
| `/dashboard/settings` | `settings/page.tsx` (171) | protected | Real settings |

`app/dashboard/layout.tsx` composes: `DashboardProviders` → `TooltipProvider` → `ShadowWatchProvider` → `SidebarProvider` → (`AppSidebar` + `SidebarInset`(`DashboardHeader` + children)) + `ShadowExecutionWindow`. Server-side `auth()` guard redirects to `/login`.

### 3.3 The API layer (`apps/web/lib/api/`) — this is the asset to preserve

| File | Lines | Role |
| --- | --- | --- |
| `client.ts` | 114 | `api<T>(path, opts)` — base URL from `NEXT_PUBLIC_API_BASE_URL` (default `http://127.0.0.1:8000`), `X-API-Key` from `NEXT_PUBLIC_DEMO_API_KEY`, `Authorization: Bearer` from Clerk, `ApiError{status, detail}` with `detail` flattening |
| `endpoints.ts` | 298 | **One typed function per backend route** + `isSfnReady()`, `sfnNotReadyMessage()`, `hasRealSfnArn()` |
| `schema.ts` | **1930** | Generated from OpenAPI (`npm run gen:api`) |
| `map-run.ts` | **1770** | **The domain adapter.** ~45 exported types/functions turning raw API JSON into view models: `mapAssessment`, `mapSchema`, `mapProcessStages`, `mapComparisons`, `mapLifecycle`, `mapShadowLifecycleRail`, `mapClusterComparison`, `mapSchemaDiff`, `mapExecutePanel`, `mapCostStrip`, `mapShadowEventLog`, `mapShadowHold`, `mapRunListItem`, plus formatters (`formatDuration`, `formatStorage`, `formatPercent`, `formatRelativeTime`, `clampProse`, `statusLabel`, `policyLabel`, `riskTone`, `sqlFilename`, `discoverErrorHint`) |
| `poll.ts` | 126 | `usePolling()` — 2.5s → 8s backoff after 60s, 30-min ceiling, pauses on `document.hidden`, `shouldStop` terminal check |
| `shadow-stream.ts` | 91 | `useShadowStream()` — **SSE** against `/runs/{id}/shadow-cluster/stream`, token via query param (EventSource can't set headers) |
| `owner.ts` | 59 | localStorage: `oracle:owner_identity`, `oracle:current_run_id`, `oracle:connection_secret_arn` |
| `clerk-token.ts` / `auth-token.ts` | 25/24 | token resolution |

**`map-run.ts` is ~1800 lines of hard-won domain logic. It must survive the redesign untouched.** It is presentation-agnostic (returns plain view-model objects, no JSX).

---

## 4. Backend — complete HTTP surface

Base: FastAPI app in `backend/app/main.py`; middleware order = CORS → `DemoApiKeyMiddleware` → `SessionAuthMiddleware`; routers = `auth`, `health`, `runs`, `memories`.

| # | Method | Path | Response | Source |
| --- | --- | --- | --- | --- |
| 1 | GET | `/` | root | `main.py:225` |
| 2 | GET | `/health` | `{status, database, cockroachdb_version, aws, integrations{api,database,aws,bedrock_*,migration_workflow_arn_set,run_artifacts_bucket_set,sfn_ready,shadow_provider,local_verify_available,environment}}` | `health.py` |
| 3 | GET | `/auth/status` | `{auth_enabled, register_enabled, clerk_configured, auth_method}` | `auth.py` |
| 4 | POST | `/auth/register` | `AuthTokenResponse` | `auth.py` |
| 5 | POST | `/auth/login` | `AuthTokenResponse` | `auth.py` |
| 6 | GET | `/auth/me` | `AuthMeResponse` | `auth.py` |
| 7 | POST | `/runs` | `MigrationRunResponse` (201) | `runs.py:58` |
| 8 | GET | `/runs` | `MigrationRunListResponse{items[],total,limit,offset}`; params `status`,`owner_identity`,`run_kind`,`exclude_kinds`,`limit`,`offset` | `runs.py:78` |
| 9 | GET | `/runs/metrics/accuracy` | see §5.3 | `runs.py:123` |
| 10 | POST | `/runs/debug/demo-with-db` | `MigrationRunResponse` | `runs.py:141` |
| 11 | POST | `/runs/debug/fake-migration` | `MigrationRunResponse` | `runs.py:191` |
| 12 | GET | `/runs/{id}` | `MigrationRunResponse` | `runs.py:216` |
| 13 | PATCH | `/runs/{id}` | status update | `runs.py:227` |
| 14 | POST | `/runs/{id}/discover` | `MigrationRunResponse`; body `{connection_secret_arn?, database_url?}` | `runs.py:237` |
| 15 | POST | `/runs/{id}/predict` | `MigrationRunResponse` | `runs.py:266` |
| 16 | GET | `/runs/{id}/pipeline-progress` | `{run_id,stage,message,percent,history[]}` | `runs.py:280` |
| 17 | POST | `/runs/{id}/approve` | `MigrationRunResponse`; body `ApprovalCreateRequest` | `runs.py:318` |
| 18 | POST | `/runs/{id}/closed-loop` | `MigrationRunResponse` | `runs.py:348` |
| 19 | POST | `/runs/{id}/start-workflow` | `MigrationRunResponse` | `runs.py:363` |
| 20 | POST | `/runs/{id}/verify-local` | `MigrationRunResponse` (engineer-only mock) | `runs.py:398` |
| 21 | POST | `/runs/{id}/sync-workflow` | `MigrationRunResponse` | `runs.py:417` |
| 22 | POST | `/runs/{id}/abort-workflow` | `MigrationRunResponse` | `runs.py:430` |
| 23 | GET | `/runs/{id}/approval` | `ApprovalResponse` | `runs.py:447` |
| 24 | POST | `/runs/{id}/grade` | `MigrationRunResponse` | `runs.py:458` |
| 25 | GET | `/runs/{id}/grade` | `GradeResponse` | `runs.py:471` |
| 26 | GET | `/runs/{id}/memory` | `MemoryResponse` | `runs.py:482` |
| 27 | GET | `/runs/{id}/shadow-cluster` | `ShadowClusterResponse` | `runs.py:493` |
| 28 | POST | `/runs/{id}/shadow-cluster/teardown-now` | `ShadowClusterResponse` | `runs.py:505` |
| 29 | **GET (SSE)** | `/runs/{id}/shadow-cluster/stream` | `event: shadow` \| `heartbeat` \| `timeout` | `runs.py:549` |
| 30 | GET | `/runs/{id}/execution-result` | `ExecutionResultResponse` | `runs.py:622` |
| 31 | GET | `/runs/{id}/model-traces` | `{migration_run_id, traces}` | `runs.py:634` |
| 32 | POST | `/runs/memories/repair-embeddings` | `{repaired[]}` | `runs.py:654` |
| 33 | GET | `/memories/health` | corpus health dict | `memories.py:18` |
| 34 | GET | `/memories` | `MemoryListResponse{items[],total,limit,offset,health}` | `memories.py:27` |
| 35 | GET | `/memories/corpus-identity` | `{corpus_owner_identity}` | `memories.py:62` |

> ⚠️ **`frontend/oracle/apps/web/lib/api/openapi.json` is STALE.** It is missing: `/auth/*` (all 4), `/runs/debug/demo-with-db`, `/runs/{id}/abort-workflow`, `/runs/{id}/shadow-cluster/teardown-now`, `/runs/{id}/shadow-cluster/stream`, `/memories/corpus-identity`. Those endpoints are hand-typed in `endpoints.ts` instead. **Regenerate (`npm run gen:api` against a live server) before the integration** or the generated types will drift further.

---

## 5. Key response shapes (what you actually get to render)

### 5.1 `MigrationRunResponse` (full)
```
id, migration_sql, status, created_at, updated_at, owner_identity, run_kind, revises_run_id,
schema_snapshot (JSONB DatabaseMetadata), schema_discovered_at, schema_discovery_duration_ms,
schema_database_engine, schema_database_version, schema_discovery_status,
sfn_execution_arn, connection_secret_arn,
workflow_status, workflow_started_at, workflow_finished_at,
risk_flags[], compatibility_risk, requires_expand_contract, requires_manual_review,
policy_decision, parsed_statement_types[], recommendation{}, explainability{},
prediction_scale_tier, recommendation_outcome{}
```
`explainability` is the AI payload: `{prediction{estimated_duration_seconds, estimated_storage_mb, rollback_risk, risk_explanation, key_assumptions[], uncertainty_notes[], framing_note}, confidence{score, raw_score, adjustments[{reason_code, reason, amount}]}, memory{retrieved_count, memories[…]}, bedrock_traces{}}` — see `map-run.ts:mapAssessment` for the authoritative parse.

### 5.2 `MigrationRunSummaryResponse` (list item — **note what's missing**)
```
id, migration_sql, status, created_at, updated_at, owner_identity, run_kind, revises_run_id,
schema_discovered_at, schema_discovery_duration_ms, schema_database_engine, schema_database_version,
schema_discovery_status, sfn_execution_arn, workflow_status, workflow_started_at,
workflow_finished_at, policy_decision, requires_manual_review, prediction_scale_tier,
+ computed: has_schema_snapshot, is_terminal, sql_snippet
```
**Absent:** `compatibility_risk`, confidence, duration, approver, grade, shadow outcome.

### 5.3 `GET /runs/metrics/accuracy`
```
scalar_accuracy_trend[]        confidence_calibration[]
migration_success_rate{numerator, denominator, rate, note}
approval_breakdown{proceed, accept_recommended, cancel, awaiting_decision, total, note}
learning_by_scale_tier[]       memory_corpus{memories_ready, pending, mean_scalar_in_memory}
high_risk_flag_precision_recall{tp, fp, fn, tn, precision, recall}
retrieval_usefulness_vs_accuracy{}    integrity_note
```

### 5.4 Enums (use these exact strings)
```
MigrationRunStatus     pending | predicting | awaiting_approval | running | completed | failed
SchemaDiscoveryStatus  pending | succeeded | failed | rejected
WorkflowStatus         not_started | running | succeeded | failed | timed_out | aborted
CompatibilityRisk      low | medium | high
PolicyDecision         allow | allow_with_warning | block
ApprovalDecision       proceed | accept_recommended | cancel
Grade.outcome_class    clean_ok | warned_ok | bad | timeout
```

---

## 6. Wiring audit — is the current stack hooked up end to end?

**Verdict: YES.** 26 of 35 endpoints are consumed by the UI. Every one of the 9 unused ones is unused *on purpose*.

| # | Endpoint | Wired? | Where / why not |
| --- | --- | --- | --- |
| 2 | `GET /health` | ✅ | `dashboard/page.tsx:100`, `current-migration-workspace.tsx:1012`, `shadow/page.tsx:265` |
| 3–6 | `/auth/*` | ➖ **defined, unused** | `getAuthStatus`/`loginUser`/`registerUser` exist in `endpoints.ts` but **no component calls them** — auth is 100% Clerk. `/auth/me` isn't even in `endpoints.ts`. **Legacy.** |
| 7 | `POST /runs` | ✅ | `new-migration-dialog.tsx:95`, `workspace:1155` |
| 8 | `GET /runs` | ✅ | `dashboard/page.tsx:101`, `history/page.tsx:23` |
| 9 | `GET /runs/metrics/accuracy` | ✅ | `dashboard/page.tsx:106` |
| 10 | `POST /runs/debug/demo-with-db` | ✅ | `workspace:1205` |
| 11 | `POST /runs/debug/fake-migration` | ✅ | `new-migration-dialog.tsx:120`, `workspace:1185` (behind `NEXT_PUBLIC_ENABLE_DEBUG_TOOLS`) |
| 12 | `GET /runs/{id}` | ✅ | workspace, `[id]`, shadow page, shadow window |
| 13 | `PATCH /runs/{id}` | ❌ **unused** | raw status override; no UI needs it |
| 14 | `POST /runs/{id}/discover` | ✅ | `workspace:1252` |
| 15 | `POST /runs/{id}/predict` | ✅ | `workspace:1301` (with AbortController) |
| 16 | `GET /runs/{id}/pipeline-progress` | ✅ | `workspace:1244, 1292` — 400ms poll during discover & predict |
| 17 | `POST /runs/{id}/approve` | ✅ | `workspace:1349` |
| 18 | `POST /runs/{id}/closed-loop` | ❌ **unused** | scripted-demo convenience; UI does the steps explicitly |
| 19 | `POST /runs/{id}/start-workflow` | ✅ | `workspace:1395`, `shadow/page.tsx:279` |
| 20 | `POST /runs/{id}/verify-local` | ➖ **deliberately excluded** | `endpoints.ts:181` comment + `/health` returns `local_verify_available:false` |
| 21 | `POST /runs/{id}/sync-workflow` | ✅ | `workspace:1084`, `[id]:457`, `shadow:188`, `shadow-execution-window:124` |
| 22 | `POST /runs/{id}/abort-workflow` | ✅ | `workspace:1424`, `shadow:305` |
| 23 | `GET /runs/{id}/approval` | ✅ | `workspace:1040, 1360` |
| 24 | `POST /runs/{id}/grade` | ❌ **unused** | grading auto-runs in the workflow's `persist_results` handler |
| 25 | `GET /runs/{id}/grade` | ✅ | workspace, `[id]`, shadow, shadow window |
| 26 | `GET /runs/{id}/memory` | ✅ | same four |
| 27 | `GET /runs/{id}/shadow-cluster` | ✅ | same four |
| 28 | `POST …/teardown-now` | ✅ | `shadow-teardown-control.tsx:96`, `shadow-live-view.tsx:264` |
| 29 | `GET …/stream` (SSE) | ✅ | `shadow-live-view.tsx:424` via `useShadowStream` |
| 30 | `GET /runs/{id}/execution-result` | ✅ | same four |
| 31 | `GET /runs/{id}/model-traces` | ✅ | `[id]/page.tsx:420` |
| 32 | `POST /runs/memories/repair-embeddings` | ❌ **unused** | ops/CLI repair (`scripts/corpus_health.py`) |
| 33 | `GET /memories/health` | ➖ **redundant** | `getMemoriesHealth()` defined but unused — `GET /memories` already embeds `health` |
| 34 | `GET /memories` | ✅ | `memory/page.tsx:176` |
| 35 | `GET /memories/corpus-identity` | ❌ **unused** | constant hard-coded as `"__migration_oracle_corpus__"` in `memory/page.tsx:71` |

**Loose ends worth fixing during integration (not blockers):**
- `listRuns()` doesn't expose the backend's `status` filter → the Decision Queue needs it.
- `openapi.json` is stale by 8 routes.
- Clerk version skew: root `package.json` pins `^7.6.1`, `apps/web` pins `^6.39.6`.
- `endpoints.ts` still ships dead `/auth/*` helpers.
- The corpus-owner constant is duplicated client-side instead of read from endpoint 35.

---

## 7. Backend capabilities with **no UI in either frontend** (free wins)

- `GET /memories/corpus-identity` — would let the memory browser filter "shared corpus vs my runs" without a magic string.
- `high_risk_flag_precision_recall` + `confidence_calibration` + `learning_by_scale_tier` + `retrieval_usefulness_vs_accuracy` from `/runs/metrics/accuracy` — **four rich chart-ready datasets, entirely unrendered.**
- `shadow/blast_radius_investigator.py` MCP tool-call traces (`ModelTraceAttempt.tool_calls[]`) — surfaced only on `/dashboard/migrations/[id]`.
- `revises_run_id` — the run-lineage link is stored and returned but never visualised.
- `ShadowClusterResponse.row_sample_before/after` — real synthetic before/after rows; only `shadow-cluster-comparison.tsx` uses them (and `shadow-row-samples-panel.tsx` was **deleted** in the working tree).

---

## 8. The feature diff

### 8.1 In the CLONE, **not** backed full-stack today

| # | Feature | Where | Gap | Recommendation |
| --- | --- | --- | --- | --- |
| A1 | **Row data preview** (step 4, "first 5 of 20 rows") | `/new-migration` | ❌ none, and *contradicts* the read-only/metadata-only privacy guarantee | **Cut**, or relabel as synthetic shadow rows |
| A2 | **Settings: 7 persisted controls** (workspace name, shadow toggle, auto-approve, threshold slider, email/Slack alerts, clear memory) | `/settings` | ❌ no settings table, no notification system, no delete endpoint | **Cut or stub as visibly disabled**; auto-approve contradicts the product thesis |
| A3 | **6 named shadow checks** (lock escalation, deadlocks, replica lag, memory usage, shadow-run count, replica id) | `/current-migration` | ❌ 4 of 6 have no data source | Build an adapter for the 2 derivable ones; cut the rest |
| A4 | **"Defer" approval decision** | `/current-migration` | ❌ not in `ApprovalDecision` | Drop, or add a 4th enum value + migration |
| A5 | **Past-migrations columns**: Duration, Risk, Confidence, Shadow, Approver, Graded | `/past-migrations` | ❌ absent from list schema | **Widen `MigrationRunSummaryResponse`** (best fix) |
| A6 | **Filters**: risk / outcome / approver / SQL search | `/past-migrations` | ❌ no server params | Client-side over a widened payload, or add query params |
| A7 | **Daily volume chart** | `/past-migrations` | ❌ no endpoint | Bucket `created_at` client-side |
| A8 | **Recent Activity feed** | `/` | ❌ no cross-run event endpoint | New endpoint, or merge `event_log` + timestamps client-side |
| A9 | **Retrieval aggregates** (success rate / avg runtime / failures across matches) | `/agent-memory` | ❌ not computed | Aggregate client-side over retrieved memories, or extend `explainability.memory` |
| A10 | **Migration Details: Index Type, Lock Mode** | `/current-migration` | ❌ never parsed | 🟡 derive from `parsed_statement_types` + SQL, or cut |
| A11 | **Prediction vs Actual: Lock time, Replica lag** | `/current-migration` | ❌ not measured | Replace with the real rows: **Duration** and **Storage** |
| A12 | **MySQL support** | `/new-migration` | ❌ PostgreSQL-wire only | Remove the card or mark unavailable |
| A13 | **Bulk row selection** (checkboxes) | `/past-migrations` | ❌ no bulk endpoints | Cut |
| A14 | **Sidebar collapse button** | sidebar | non-functional in clone | ✅ the current app already has a *working* one (`SidebarProvider`/`SidebarRail`) — wire the clone's chevron to it |

### 8.2 Backed **full-stack today**, but **absent from the clone's design**

| # | Feature | Current location | Consequence if the clone replaces it wholesale |
| --- | --- | --- | --- |
| B1 | **Entire marketing site** — landing (`Hero`, `MediaShowcase`, `PipelineSection`, `TechMarquee`, `xyflow` diagrams, `SiteHeader/Footer`) + `/our-journey` | `app/page.tsx`, `components/landing/*` (~25 files) | Public site gone. **Must be preserved as-is; the clone has no `/` marketing route.** |
| B2 | **Clerk auth** — `/login`, `/get-started`, `<SignIn>/<SignUp>`, `middleware.ts`, `auth()` guard in dashboard layout, `clerk-owner-sync` | `app/login`, `app/get-started`, `middleware.ts`, `app/dashboard/layout.tsx` | **The clone has no auth whatsoever.** Absolute must-keep. |
| B3 | **`/dashboard/migrations/[id]` detail page (866 lines)** — Lifecycle, Shadow Cluster, Jobs observed, Execution Result, Grade, Memory, **Model Traces** (raw Bedrock prompts/responses/token counts/tool calls) | `[id]/page.tsx` | **The single strongest judging artefact ("we show the model's actual work") disappears.** The clone has no per-run detail route at all. |
| B4 | **Shadow-execution deep dive** `/current/shadow` (495) + `shadow-cluster-comparison.tsx` (568) + `shadow-live-view.tsx` (541) + `shadow-teardown-control.tsx` — production-vs-shadow column diff, live lifecycle rail, event log, cost strip, hold/teardown control | `current/shadow/*`, `components/shadow-*` | The clone's static "Shadow Execution Evidence" panel is a *screenshot* of this. Losing it loses the live SSE, the schema diff, row samples, and manual teardown. |
| B5 | **Real Agent Memory corpus browser** — per-memory cards with owner, scale tier, migration type, embedding status, `embed_text` viewer, corpus-vs-graded badges, source URLs, corpus health warnings | `memory/page.tsx` | The clone's `/agent-memory` is a *per-migration confidence explainer*, a different page. **Both are needed.** |
| B6 | **Connect-a-database UX** — read-only URL field, Secrets-Manager-ARN alternative, copyable `GRANT`/`REVOKE` helper SQL, "Try the demo database" | `ConnectDatabaseFields` in `workspace:306` | The clone's host/port/user/pass form has no ARN path, no GRANT helper, no demo DB. |
| B7 | **Override-rationale gate** — required free-text when `policy_decision === "block"` before proceeding | `workspace:1329, 1858` | Removing it lets a user silently bypass a policy block. **Compliance-relevant.** |
| B8 | **Live pipeline progress bars** — 400ms `pipeline-progress` polling during discover and predict, with stage messages + % | `workspace:1244, 1292` | Clone fakes with `setTimeout`. |
| B9 | **Abort / Stop controls** — `AbortController` on predict, `abort-workflow`, `teardown-now` | `workspace:1321/1418`, `shadow:305` | No abort anywhere in the clone. |
| B10 | **Unknown-table SQL warning** — client-side regex flags SQL referencing tables discovery didn't find | `workspace:106, 1757` | Lost. |
| B11 | **Schema disclosure** — per-table rows/size/columns/indexes inline | `SchemaTables` in `workspace:237` | Clone shows a flat 4-column table only. |
| B12 | **Assessment panel depth** — policy decision, confidence clamping (+ *why* it was clamped, with per-adjustment reasons), risk flags by rule id/severity, assumptions, uncertainty, rollout steps, monitoring checklist, rollback guidance, safer-alternative plan, prose clamping | `AssessmentPanel` in `workspace:663` | The clone shows 5 static bullets. **This is the AI-transparency story.** |
| B13 | **Retrieval panel** — "learning from N similar runs", empty-vs-never-attempted distinction, weak-retrieval warning, expandable memory cards with similarity + graded-vs-corpus provenance | `RetrievalPanel` in `workspace:611` | Reduced to a static "36 matches". |
| B14 | **Process-stage tracker** — create→predict→approve→shadow→grade→remember with per-stage state | `mapProcessStages`, `workspace:209` | Clone has a wizard stepper only on `/new-migration`. |
| B15 | **Dark theme + persisted preference** | `theme-provider.tsx`, `theme-toggle.tsx`, `lib/theme-preference.ts`, `--oracle-*` dark tokens | **Clone is light-only.** |
| B16 | **Settings that actually work** — owner identity, theme, API base URL display, connection-secret ARN | `settings/page.tsx` | Replaced by 7 non-functional controls. |
| B17 | **Debug tooling** — fake migration + demo DB behind `NEXT_PUBLIC_ENABLE_DEBUG_TOOLS` | `workspace:1638` | Lost; needed for demos without a live DB. |
| B18 | **Error surfacing** — `ApiError` messages, `discoverErrorHint(status,msg)`, `sfnNotReadyMessage(health)` with actionable setup instructions | `endpoints.ts:247`, `map-run.ts:1747` | Clone has no error states at all. |

### 8.3 Present in both — pure re-skin, logic reusable as-is

| Feature | Clone | Current | Note |
| --- | --- | --- | --- |
| Overview: system health, latest migration, recent list, accuracy, approval breakdown, memory counts | `/` | `/dashboard` | **Near-identical information architecture.** Highest-confidence port. |
| Past migrations list | `/past-migrations` | `/dashboard/migrations/history` | Clone is much richer visually; needs §8.1-A5 |
| Current migration review + approve | `/current-migration` | `/dashboard/migrations/current` | Clone is a simplification; keep the current logic |
| Agent memory | `/agent-memory` | `/dashboard/memory` | **Different concepts** — plan for *two* pages |
| Settings | `/settings` | `/dashboard/settings` | Different controls entirely |
| Floating shadow watcher | `ShadowWatch` | `ShadowExecutionWindow` + context | Restyle the shell, keep the logic |
| Sidebar (Overview / New / Current / Past / Agent Memory / Settings + owner identity block) | `app-sidebar.tsx` | `app-sidebar.tsx` + `nav-main` + `OwnerIdentityField` | Clone adds a **"New Migration"** nav item and count badges; current uses collapsible `SidebarProvider` |

---

## 9. Recommended integration strategy

### 9.1 Direction: port the *design* into Next.js. Do **not** adopt TanStack Start.

Reasons, concretely:
- Auth is Clerk + Next.js `middleware.ts` + server `auth()`. Re-implementing it on TanStack Start is a rewrite of the security boundary.
- The marketing site (§8.2-B1, ~25 components incl. `@xyflow/react`) is Next.js App Router with `next/font`, server components, and `next/link`.
- `packages/ui` is `@base-ui/react`; the clone's 48 shadcn files are **Radix**. Mixing is fine (they're independent), but replacing `@workspace/ui` wholesale would break `SidebarProvider`, `Collapsible`, `Tooltip`, `Dialog` usage across 30+ existing files.
- The clone's Vite config is a **Lovable-managed black box** (`@lovable.dev/vite-tanstack-config`) that silently injects plugins; it also ships Lovable error-reporting (`lib/lovable-error-reporting.ts`, `error-capture.ts`) that phones home. **Delete those three files** — do not port them.
- The clone's `src/server.ts` / `src/start.ts` are TanStack SSR/CSRF plumbing with no Next.js analogue.

**Therefore:** treat `pixel-perfect-clone-64427-main/` as a **design source**. Extract JSX + Tailwind classes + tokens. Discard the runtime.

### 9.2 Mechanical conversion rules (clone → Next.js)

| Clone | Next.js equivalent |
| --- | --- |
| `createFileRoute("/x")({component: C})` | `app/dashboard/x/page.tsx` default export |
| `Route.head(() => ({meta, links}))` | `export const metadata: Metadata` (or `generateMetadata`) |
| `import { Link } from "@tanstack/react-router"` | `import Link from "next/link"` |
| `<Link to="/x" activeProps={…}>` + render-prop `{({isActive}) => …}` | `<Link href="/x">` + `usePathname()` for active state (the current `nav-main.tsx` already does this) |
| `useNavigate()` → `navigate({to:"/x"})` | `useRouter()` from `next/navigation` → `router.push("/x")` |
| `__root.tsx` `RootShell`/`RootComponent` | split: `app/layout.tsx` (html/fonts/Clerk) + `app/dashboard/layout.tsx` (sidebar/providers) |
| Google-Fonts `<link>` for Geist | already loaded via `next/font/google` in `app/layout.tsx` ✅ |
| `@/components/*` alias | already configured in `apps/web/tsconfig.json` ✅ |
| Any `useState`-only interaction | replace with the real API call from `lib/api/endpoints.ts` |

### 9.3 Token/theme merge

The clone's palette (warm off-white + **burnt orange `oklch(0.5534 0.1739 38.4)`**) is a *different brand* from the current `--oracle-*` set (violet reasoning / emerald verified / red risk / amber warning).

**Recommendation:** adopt the clone's `--primary`/`--background`/`--card`/`--border`/`--muted` family into `packages/ui/src/styles/globals.css` `:root`, **but keep the `--oracle-*` semantic vars**, remapping their light values to the clone's emerald/amber/red usage. Then author a matching `.dark` block for the new palette (the clone ships none — you must design it). `@utility section-label` should be added to `globals.css` verbatim; it's used on nearly every panel.

### 9.4 The wizard's ordering problem (`/new-migration`)

The clone's flow is `connect → browse schema → pick table → preview → write SQL → submit`.
The backend's flow is `POST /runs (needs SQL) → POST /discover (needs a run) → POST /predict`.

Three ways out, pick one (§10 Q1):
- **(a) Reorder the wizard** to `SQL → Connect → Schema → Columns → Submit`. Smallest backend change, breaks pixel-fidelity of step order.
- **(b) Create the run with placeholder SQL** at step 1, `PATCH` it at step 5. **Requires a new endpoint** — `PATCH /runs/{id}` currently only updates `status`.
- **(c) Defer everything to step 5**: hold connection details in client state, then fire `POST /runs` → `POST /discover` → `POST /predict` in sequence on submit; render steps 2–4 from the discovery result of a *transient* discovery. Needs a run-less discovery endpoint. **Most work.**

> The existing `handleCreateFromSql()` (`workspace:1140`) already implements a version of (a)/(c): it creates the run and, if connection fields are filled, chains straight into `handleDiscover(created)`. **Reuse that.**

### 9.5 Recommended backend additions (in priority order)

1. **Widen `MigrationRunSummaryResponse`** with: `compatibility_risk`, `confidence_score`, `approver_identity`, `actual_duration_seconds`, `outcome_class`, `is_graded`, `shadow_status`. Unblocks §8.1-A5/A6 and the Decision Queue in one change. *(Requires joining `approvals`/`grades`/`execution_results`/`shadow_clusters` in `migration_run_repository.list_*`; watch the N+1.)*
2. **Expose the `status` filter** in `endpoints.ts:listRuns()` (backend already supports it) — one line.
3. **`GET /activity`** (or `/runs/activity?limit=N`) — merged, owner-scoped feed of run created / predicted / approved / shadow-started / shadow-finished / graded events. Unblocks §8.1-A8 and the clone's Activity Timeline.
4. **Extend `explainability.memory`** with aggregates over the retrieved set (`success_rate`, `mean_duration_seconds`, `failure_count`). Unblocks §8.1-A9.
5. *(Only if settings are kept)* **A `workspace_settings` table + `GET/PUT /settings`.** Scope carefully — do **not** ship auto-approve.
6. **Regenerate `openapi.json`** and re-run `npm run gen:api`.

### 9.6 Suggested phasing

| Phase | Work | Ships |
| --- | --- | --- |
| **0** | Regenerate OpenAPI; expose `status` in `listRuns`; align Clerk versions; delete `lovable-error-reporting.ts`/`error-capture.ts`/`error-page.ts` from anything ported | clean base |
| **1** | Merge design tokens + `section-label` into `packages/ui/globals.css`; author the dark variant; add `ui-kit.tsx` (`PageHeader`/`Panel`/`Label`/`StatusPill`/`SqlBlock`) into `packages/ui` | design system |
| **2** | Restyle `app-sidebar.tsx` to the clone's look **inside** the existing `SidebarProvider`; add the "New Migration" nav item; wire the collapse chevron | shell |
| **3** | Rebuild `/dashboard` with the clone's Overview layout. **Highest ROI** — the IA already matches (§8.3). Decision Queue + Activity feed initially degrade gracefully (empty states) until §9.5-1/3 land | Overview |
| **4** | Restyle `/dashboard/migrations/history` to the clone's table. Land §9.5-1 first or the columns stay blank | Past Migrations |
| **5** | Restyle `/dashboard/migrations/current`. **Keep every handler in `current-migration-workspace.tsx`.** Reskin the panels; keep the override-rationale gate, abort, progress bars, connect-DB UX, `AssessmentPanel`, `RetrievalPanel` | Current Migration |
| **6** | New `/dashboard/migrations/new` wizard (per §9.4). Route the existing `NewMigrationDialog` CTA to it | New Migration |
| **7** | Add the clone's `/agent-memory` as a **new** per-run confidence page (e.g. `/dashboard/migrations/current/memory`); restyle the existing `/dashboard/memory` corpus browser separately | Agent Memory ×2 |
| **8** | Restyle `/dashboard/settings` keeping the 4 real controls; add clone controls **only** where backed | Settings |
| **9** | Restyle `ShadowExecutionWindow` to the `ShadowWatch` shell; restyle `/current/shadow` and `[id]` in the new visual language | Shadow + detail |

### 9.7 Things that will bite you

- **`packages/ui` is `@base-ui/react`, the clone is Radix.** Don't copy the clone's `components/ui/*` over `packages/ui/src/components/*`. Add only the primitives you need, in a separate namespace, or restyle the base-ui ones.
- **Clerk version skew** (root `^7.6.1` vs `apps/web` `^6.39.6`) — resolve before touching auth.
- **Uncommitted working-tree changes** exist in 15 files including `shadow-execution-window.tsx`, `shadow-live-view.tsx`, `map-run.ts`, `globals.css`, and a **deleted** `shadow-row-samples-panel.tsx`. Commit or stash before a large refactor.
- **`.playwright-mcp/` has ~60 untracked log/yml artefacts** polluting `git status`. Add to `.gitignore`.
- **`framer-to-next-dream-main/`** is a *third* design in the repo. Confirm it's dead before anyone confuses the two.
- The clone hard-codes **"Samved Mamillapalli" / "samvedmamillapalli@g…"** in `app-sidebar.tsx:89` and `settings.tsx:108`. Replace with Clerk user data.
- The clone's `motion` v12 and current app's `motion` v12.42 agree — animations port cleanly.
- Tailwind v4 in both, but the clone uses `@import "tailwindcss" source(none)` + `@source "../src"`. The Next.js app uses `@tailwindcss/postcss`. Class syntax is identical; the config plumbing is not.

---

## 10. Open questions — answer these before writing code

| # | Question | Why it matters | Default if unanswered |
| --- | --- | --- | --- |
| **Q1** | **New Migration wizard ordering** — reorder to SQL-first (a), add a SQL-`PATCH` endpoint (b), or defer-and-chain at submit (c)? | Determines whether backend work is needed for the flagship new page | **(a)** — reuse the existing `handleCreateFromSql` chain |
| **Q2** | **Connection input** — keep the clone's 5 discrete fields (host/port/db/user/pass) and compose a URL client-side, or keep the current single read-only-URL field + ARN + GRANT helper? | The current UX carries real security guidance (§8.2-B6) | **Hybrid** — clone's visual, current app's fields |
| **Q3** | **Data preview step** — cut it, or show shadow-synthetic rows clearly labelled? | Showing real customer rows contradicts the stated privacy guarantee | **Cut** |
| **Q4** | **"Defer" button** — drop it, or add a 4th `ApprovalDecision` + DB migration? | Changes an append-only audit enum | **Drop** |
| **Q5** | **Shadow "checks" list** — build a derivation adapter for the 2 real ones, or cut the panel for the live view? | 4 of 6 checks have no data source at all | **Adapter for real ones only** |
| **Q6** | **Settings** — keep the clone's 7 unbacked controls as visible-but-disabled, cut them, or build the settings backend? | Auto-approve directly contradicts the product thesis | **Cut auto-approve; stub the rest** |
| **Q7** | **Do the marketing site, `/dashboard/migrations/[id]`, and `/current/shadow` stay?** (§8.2-B1/B3/B4) | The clone has no design for any of them | **Yes, all three stay** |
| **Q8** | **Dark mode** — port the current dark theme onto the clone's palette, or ship light-only? | Clone has no dark tokens; current app has a persisted preference | **Port** |
| **Q9** | **Agent Memory** — one page or two? | The two designs answer different questions | **Two** |
| **Q10** | **Route naming** — keep `/dashboard/*` prefix, or move to the clone's flat `/`, `/current-migration`, `/past-migrations`? | Affects `middleware.ts`, all `Link`s, and marketing-vs-app separation at `/` | **Keep `/dashboard/*`** (`/` is the marketing landing) |

---

## 11. Quick reference — file map for the integrator

**Read before starting:**
- `frontend/oracle/apps/web/lib/api/map-run.ts` — the domain adapter; know what's already solved
- `frontend/oracle/apps/web/app/dashboard/migrations/current/current-migration-workspace.tsx` — every handler you must preserve
- `backend/app/api/routes/runs.py` — the entire run lifecycle
- `pixel-perfect-clone-64427-main/src/lib/migration-data.ts` — the exact shape of every mock, i.e. the render contract

**Never port:**
- `pixel-perfect-clone-64427-main/src/lib/lovable-error-reporting.ts`
- `pixel-perfect-clone-64427-main/src/lib/error-capture.ts`
- `pixel-perfect-clone-64427-main/src/lib/error-page.ts`
- `pixel-perfect-clone-64427-main/src/{server,start,router}.ts`, `routeTree.gen.ts`, `vite.config.ts`, `.lovable/`

**Port verbatim:**
- `src/styles.css` tokens + `@utility section-label`
- `src/components/ui-kit.tsx`
- Every route file's JSX **body** (not its `createFileRoute` wrapper)

---

## 12. The integration prompt

Copy everything between the fences into a fresh session.

````text
You are integrating a new frontend design into the Migration Oracle full-stack app.

REPO: c:\Users\samve\OneDrive\Documents\ComputerScience\CockroachDB_hackathon (branch: Samved)

READ FIRST, IN FULL — do not start until you have:
  docs/PIXEL_PERFECT_CLONE_INTEGRATION_PLAN.md          (the complete analysis; sections referenced below)
  frontend/oracle/apps/web/lib/api/map-run.ts            (~1800-line domain adapter — REUSE, DO NOT REWRITE)
  frontend/oracle/apps/web/lib/api/endpoints.ts          (typed client, one fn per backend route)
  frontend/oracle/apps/web/app/dashboard/migrations/current/current-migration-workspace.tsx  (every handler to preserve)
  backend/app/api/routes/runs.py                         (the run lifecycle)
  pixel-perfect-clone-64427-main/src/lib/migration-data.ts  (the render contract of the new design)

GOAL
Replace the visual layer of the existing Next.js dashboard with the design in
pixel-perfect-clone-64427-main/, while keeping every existing backend integration working
end to end. The new folder is a STATIC MOCK — zero fetch calls, zero auth, all data hard-coded.
Treat it as a design source, not an app.

HARD CONSTRAINTS
1. Target stack stays Next.js 16 App Router + Turborepo + Clerk + @workspace/ui.
   DO NOT adopt TanStack Start/Router or Vite. Port JSX + Tailwind classes + design tokens only.
2. NEVER port these files: src/lib/lovable-error-reporting.ts, src/lib/error-capture.ts,
   src/lib/error-page.ts, src/server.ts, src/start.ts, src/router.tsx, src/routeTree.gen.ts,
   vite.config.ts, .lovable/.
3. Do not copy pixel-perfect-clone-64427-main/src/components/ui/* over packages/ui/src/components/*.
   The clone is Radix; @workspace/ui is @base-ui/react. Mixing them wholesale breaks
   SidebarProvider, Collapsible, Tooltip and Dialog usage in 30+ existing files.
4. These must survive untouched and keep working (see §8.2 for why each matters):
   - the marketing site at / and /our-journey (components/landing/*, ~25 files)
   - Clerk auth: /login, /get-started, middleware.ts, the server auth() guard in dashboard/layout.tsx
   - /dashboard/migrations/[id] including the Model Traces panel
   - /dashboard/migrations/current/shadow + shadow-cluster-comparison, shadow-live-view,
     shadow-teardown-control, and the SSE hook useShadowStream
   - /dashboard/memory (the corpus browser) — the clone's /agent-memory is a DIFFERENT page,
     a per-run confidence explainer. Build it as an additional route; do not replace the browser.
   - the override-rationale gate that is required when policy_decision === "block"
   - abort/stop controls (predict AbortController, abort-workflow, teardown-now)
   - the 400ms pipeline-progress polling during discover and predict
   - the connect-a-database UX: read-only URL field + Secrets Manager ARN option + copyable
     GRANT/REVOKE helper + "Try the demo database"
   - dark mode and the persisted theme preference
5. Never invent data. If the clone renders something with no backend source (§8.1), either
   derive it honestly from real fields, or omit it with an explicit empty state. Do not ship
   a hard-coded 94%, "replica-03", "36 matches", or a fabricated check result.

DESIGN TOKENS (port verbatim into packages/ui/src/styles/globals.css)
  --radius 8px; Geist / Geist Mono (already loaded via next/font)
  --background oklch(0.9845 0.0026 106.45)   --foreground oklch(0.2161 0.0061 56.04)
  --card oklch(1 0 0)                         --primary oklch(0.5534 0.1739 38.4)  [burnt orange]
  --accent oklch(0.6461 0.1943 41.12)         --secondary oklch(0.9668 0.0054 95.1)
  --muted oklch(0.9512 0.008 98.88)           --muted-foreground oklch(0.5534 0.0116 58.07)
  --border/--input oklch(0.9218 0.0083 91.49) --destructive oklch(0.5771 0.2152 27.33)
  plus @utility section-label { font-size:11px; line-height:1; font-weight:600;
       letter-spacing:.08em; text-transform:uppercase; color:var(--muted-foreground); }
  Keep the existing --oracle-* semantic vars; remap their light values onto the clone's
  emerald(pass)/amber(warn)/red(fail)/blue(shadow)/violet(AI) usage.
  The clone ships NO dark theme — you must author a .dark block for the new palette.

ANSWER THESE BEFORE CODING (defaults in brackets; ask me if you disagree)
  Q1 New-Migration wizard ordering        [reorder to SQL-first, reusing handleCreateFromSql's
                                           create-then-chain-discover flow]
  Q2 Connection input                     [clone's visual, current app's fields: read-only URL
                                           + ARN + GRANT helper — not host/port/user/pass]
  Q3 Step-4 row data preview              [CUT — contradicts the metadata-only privacy guarantee]
  Q4 "Defer" approval button              [DROP — ApprovalDecision is proceed|accept_recommended|cancel]
  Q5 The 6 named shadow checks            [adapter for the 2 derivable ones only; cut the rest]
  Q6 Settings' 7 unbacked controls        [cut auto-approve entirely; stub the others disabled]
  Q7 Keep marketing + [id] + /shadow      [YES, all three]
  Q8 Dark mode                            [port it onto the new palette]
  Q9 Agent Memory: one page or two        [TWO]
  Q10 Route prefix                        [keep /dashboard/*; / stays the marketing landing]

EXECUTE IN PHASES — one phase per commit, verify before moving on.
  Phase 0  Regenerate frontend/oracle/apps/web/lib/api/openapi.json from a live server and re-run
           `npm run gen:api` (it is stale by 8 routes: all /auth/*, /runs/debug/demo-with-db,
           /runs/{id}/abort-workflow, /runs/{id}/shadow-cluster/teardown-now,
           /runs/{id}/shadow-cluster/stream, /memories/corpus-identity).
           Expose the backend's existing `status` query param in listRuns() (one line).
           Align the Clerk version skew (root ^7.6.1 vs apps/web ^6.39.6).
           Add .playwright-mcp/ to .gitignore. Commit or stash the 15 dirty working-tree files first.
  Phase 1  Merge design tokens + section-label into packages/ui globals.css; author the dark
           variant; add ui-kit primitives (PageHeader, Panel, Label, StatusPill, SqlBlock) to
           packages/ui. StatusPill must map real enum values:
           pending|predicting|awaiting_approval|running|completed|failed.
  Phase 2  Restyle components/app-sidebar.tsx to the clone's look INSIDE the existing
           SidebarProvider. Add a "New Migration" nav item. Wire the collapse chevron to
           the real toggle. Replace the hard-coded "Samved Mamillapalli" identity block with
           Clerk user data + the existing OwnerIdentityField.
  Phase 3  Rebuild /dashboard with the clone's Overview layout. The information architecture
           already matches — map every tile to GET /health, GET /runs?limit=5&exclude_kinds=chaos,debug,
           and GET /runs/metrics/accuracy (approval_breakdown, migration_success_rate,
           scalar_accuracy_trend, memory_corpus). Decision Queue = GET /runs?status=awaiting_approval.
           Recent Activity has NO endpoint — render an honest empty state until Phase 10.
  Phase 4  Restyle /dashboard/migrations/history to the clone's filterable table + pagination.
           Duration/Risk/Confidence/Shadow/Approver/Graded are absent from
           MigrationRunSummaryResponse — do Phase 10 item 1 first, or render "—" for them.
           Wire pagination to the backend's limit/offset/total, not client-side slicing.
  Phase 5  Restyle /dashboard/migrations/current. KEEP EVERY HANDLER in
           current-migration-workspace.tsx. Reskin AssessmentPanel, RetrievalPanel,
           ComparisonsPanel, ProcessStages, SchemaTables and ConnectDatabaseFields into
           Panel/Label/StatusPill. Approve→proceed, Reject→cancel, and keep
           "Skip shadow (keep plan)"→accept_recommended. Replace the clone's fake
           "Prediction vs Actual" rows (Lock time, Replica lag) with the real ones from
           mapComparisons(): Duration and Storage.
  Phase 6  Build /dashboard/migrations/new as the 5-step wizard per the Q1 answer. Steps 2–3
           render from MigrationRunResponse.schema_snapshot via mapSchema(). Route the existing
           NewMigrationDialog CTA to it.
  Phase 7  Add the clone's /agent-memory as a NEW per-run confidence page, sourced from
           explainability.confidence + explainability.memory retrieval hits. Restyle the
           existing /dashboard/memory corpus browser separately.
  Phase 8  Restyle /dashboard/settings keeping the 4 real controls (owner identity, theme,
           API base URL display, connection-secret ARN). Add clone controls only where backed.
  Phase 9  Restyle ShadowExecutionWindow to the ShadowWatch shell (keep the SSE/polling logic),
           then /current/shadow and /dashboard/migrations/[id] in the new visual language.
  Phase 10 Backend additions, in this order:
           1. Widen MigrationRunSummaryResponse with compatibility_risk, confidence_score,
              approver_identity, actual_duration_seconds, outcome_class, is_graded, shadow_status
              (join approvals/grades/execution_results/shadow_clusters in
              migration_run_repository.list_* — watch for N+1). Unblocks Phase 4.
           2. GET /activity — owner-scoped merged feed of run created/predicted/approved/
              shadow-started/shadow-finished/graded. Unblocks the Overview Activity panel.
           3. Extend explainability.memory with aggregates over the retrieved set
              (success_rate, mean_duration_seconds, failure_count). Unblocks /agent-memory stats.
           Add an Alembic migration for any schema change. Re-run gen:api afterwards.

VERIFY AFTER EACH PHASE
  cd frontend/oracle && npm run typecheck && npm run lint && npm run build
  Start the backend (see docs/DEMO_OPS.md), then click through:
  create run -> attach demo DB -> discover -> predict -> approve -> start shadow -> watch live
  -> outcome -> memory. Confirm no page renders a hard-coded number where an API value belongs.

REPORT
  After each phase: what changed, what still renders an empty state and why, and any endpoint
  you found returning something the new UI can't display.
````

---

*End of document.*
