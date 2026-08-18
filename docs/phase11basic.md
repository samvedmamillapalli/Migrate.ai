# Phase 11: Frontend — Comprehensive Plan

This document is the authoritative plan for building the Migration Oracle user interface. Read it fully before writing frontend code. Where it conflicts with an assumption you would otherwise make, this document wins. Where it is silent, follow the conventions already established in Phases 1–10 and the existing debug console at `/ui`.

**Goal:** Build a production-quality frontend that makes the closed loop — **predict → approve → verify → grade → remember** — visible, understandable, and demo-ready. A developer or judge should be able to watch data flow in, see how the model predicts, follow shadow execution, compare prediction vs actual, and understand what the system learned — without reading backend code or raw JSON.

---

## 1. What this phase is, and why it matters

Phases 1–10 built a working backend: FastAPI control plane, CockroachDB state, AWS Step Functions execution, Bedrock prediction, hybrid vector memory, and deterministic grading. The backend is **API-complete** for a hackathon demo. What is missing is a UI that tells the story.

The current debug console (`frontend/index.html`, served at `http://127.0.0.1:8000/ui`) is a functional API exerciser. It can create runs, trigger predict/approve, and dump JSON into `<pre>` blocks. It is valuable for development but fails three user needs:

1. **Comprehension** — Raw JSON does not explain *why* the model predicted 42 seconds or *which* past migrations influenced that prediction.
2. **Live visibility** — No polling during `running`, no workflow stage timeline, no sense that shadow execution is happening.
3. **Learning narrative** — The accuracy curve, memory retrieval attribution, and confidence calibration are the hackathon differentiators but have no visual home.

Phase 11 is not “add some buttons.” It is the **observability and storytelling layer** for an agentic system. The UI must answer:

| Question | Where the answer lives today | What the UI must show |
| --- | --- | --- |
| What did I submit? | `migration_runs.migration_sql`, `schema_snapshot` | SQL editor + schema summary cards |
| Is it safe to proceed? | `policy_decision`, `risk_flags` | Policy panel with severity-coded findings |
| What will happen on shadow? | `predictions`, `explainability.prediction` | Metric cards + confidence breakdown |
| What did memory contribute? | `explainability.memory` | Retrieval panel with similarity scores |
| What should I do? | `recommendation` | Rollout steps, monitoring checklist, approve actions |
| Is it running? | `status`, `workflow_status`, `shadow_clusters` | Live pipeline tracker + stage timings |
| Was the prediction right? | `grades`, `execution_results` | Side-by-side predicted vs actual |
| Is the system getting smarter? | `GET /runs/metrics/accuracy` | Accuracy trend + calibration charts |

---

## 2. Research synthesis: what good UIs in this space look like

We reviewed related projects and 2025–2026 observability patterns. The frontend plan borrows structure from these, not their stacks wholesale.

### 2.1 LLM / agent observability (Langfuse, Arize Phoenix, Braintrust)

**Pattern:** Hierarchical trace timelines with nested spans — LLM call → tool use → retrieval → output validation.

**Applicable to Migration Oracle:**
- Treat each run as a **trace** with named spans: `policy_analyze` → `memory_retrieve` → `bedrock_predict` → `bedrock_recommend` → `human_approve` → `sfn_discover` → `sfn_provision` → … → `grade` → `remember`.
- **Aggregated vs expanded views** (Langfuse Agent Graphs): collapsed pipeline for overview; expanded step-by-step for debugging.
- **Semantic telemetry**, not just HTTP status: token usage, model ID, retrieval count, confidence adjustments, scalar accuracy score.

**References:**
- [Langfuse Agent Graphs](https://langfuse.com/docs/observability/features/agent-graphs) — aggregated/expanded workflow visualization
- [Arize Phoenix Tracing](https://arize.com/docs/phoenix/tracing/llm-traces) — span timelines, session grouping, annotations
- [AI Agent Telemetry Dashboards (Zylos Research, 2026)](https://zylos.ai/research/2026-05-10-ai-agent-telemetry-dashboards/) — structural vs semantic metrics hierarchy

### 2.2 Migration risk / safety tools (SafeMigrate, pg-dash, Migratrix, MCP Migration Advisor)

**Pattern:** Input SQL → deterministic scan → optional shadow simulation → risk score → actionable recommendations.

**Applicable to Migration Oracle:**
- **Risk scorecard** with color-coded severity (SafeMigrate, pg-dash `check-migration`)
- **Schema browser** with table/row-count/size summary (pg-dash schema tracking)
- **Side-by-side environment diff** mindset for predicted vs actual (Migratrix schema compare)
- **CI-friendly annotations** — our console panel is the dev-time equivalent of pg-dash `--ci` output

**References:**
- [SafeMigrate](https://github.com/SarveshTikekar/SafeMigrate) — shadow simulation + LLM risk narrative + visual report
- [pg-dash](https://github.com/indiekitai/pg-dash) — migration safety checks, schema timeline, multi-env diff
- [Migratrix](https://migratrix.com/) — governed workflow: explore → plan → approve → execute → compare
- [mcp-migration-advisor](https://github.com/Dmitriusan/mcp-migration-advisor) — lock risk, data loss detection, 0–100 risk scoring

### 2.3 ML explainability dashboards (ExplainerDashboard, Evidently, Fiddler)

**Pattern:** Prediction detail view with feature contributions, calibration plots, and accuracy-over-time.

**Applicable to Migration Oracle:**
- **Local explanation:** why this duration/storage estimate (assumptions, uncertainty notes, policy flags)
- **Global learning:** accuracy trend, confidence calibration buckets, precision/recall on high-risk flags
- **What-if is out of scope** for MVP — we show real graded runs, not counterfactual sliders

**References:**
- [ExplainerDashboard](https://github.com/oegedijk/explainerdashboard) — modular tabs: performance, importances, individual predictions
- [Evidently AI](https://www.evidentlyai.com/) — drift/quality dashboards from notebook or service

### 2.4 Design principles distilled

1. **Pipeline-first layout** — The closed loop is the hero; every page reinforces where you are in predict → approve → verify → grade → remember.
2. **Inputs left, outputs right** — Data going in (SQL, schema, connection) on the left; model outputs and grades on the right; processing in the center or bottom console.
3. **Progressive disclosure** — Summary cards first; expand to full JSON / raw prompts for power users.
4. **Never fake state** — UI reads only from API responses. No invented progress bars.
5. **Console is always available** — A persistent event log (evolve the existing debug log) shows every API call with timing, status, and expandable request/response bodies.
6. **Demo moments are first-class** — Memory retrieval panel and accuracy curve are not “nice to have”; they are judging criteria.

---

## 3. What exists today (inventory)

### 3.1 Backend API (ready to consume)

| Capability | Endpoint(s) | UI status |
| --- | --- | --- |
| Health | `GET /health` | Debug console ✓ |
| Create run | `POST /runs` | Debug console ✓ |
| List runs | `GET /runs` | Debug console ✓ |
| Run detail | `GET /runs/{id}` | Debug console ✓ (JSON) |
| Schema discover | `POST /runs/{id}/discover` | **Missing** |
| Predict | `POST /runs/{id}/predict` | Debug console ✓ |
| Approve | `POST /runs/{id}/approve` | Debug console ✓ |
| Closed loop shortcut | `POST /runs/{id}/closed-loop` | **Missing** |
| Start/sync workflow | `POST /runs/{id}/start-workflow`, `sync-workflow` | **Missing** |
| Grade | `GET /runs/{id}/grade` | Debug console ✓ (JSON) |
| Memory | `GET /runs/{id}/memory` | Debug console ✓ (JSON) |
| Accuracy metrics | `GET /runs/metrics/accuracy` | **Missing** |
| Approval audit | `GET /runs/{id}/approval` | **Missing** |

Full reference: `docs/API.md`.

### 3.2 Explainability payload (no extra API needed)

After `POST /predict`, `run.explainability` contains everything needed to render the prediction story without another model call (`ExplainabilityBundle` in `backend/app/prediction/models.py`):

```json
{
  "policy": { "policy_decision", "driving_findings", ... },
  "prediction": { "estimated_duration_seconds", "rollback_risk", "prediction_target": "shadow_run_only", ... },
  "recommendation": { ... } | null,
  "memory": { "retrieved_count", "memories", "weak_retrieval", "attribution", ... },
  "confidence": { "raw_confidence_score", "adjusted_confidence", "adjustments": [...] },
  "framing_note": "Blast radius means backfill duration, storage growth, ..."
}
```

### 3.3 Accuracy metrics payload (chart source)

`GET /runs/metrics/accuracy` returns (`backend/app/memory/metrics.py`):

- `scalar_accuracy_trend` — time series for accuracy curve
- `confidence_calibration` — bucketed mean error vs confidence
- `recommendation_rates` — acceptance and linked success rates
- `learning_by_scale_tier` — accuracy segmented by shadow tier
- `memory_corpus` — corpus size, pending embeddings
- `high_risk_flag_precision_recall` — policy flag quality
- `retrieval_usefulness_vs_accuracy` — correlation of retrieval to accuracy

### 3.4 Debug console gaps (baseline to exceed)

| Gap | Impact |
| --- | --- |
| No schema discover form | Cannot demo full connect → predict flow |
| No polling while `running` | Shadow execution feels like a black box |
| No workflow sync button | Stuck on stale `workflow_status` |
| No accuracy charts | Cannot show “getting smarter” narrative |
| JSON-only inspector | Judges cannot parse prediction vs grade quickly |
| No request/response body in log | Hard to debug what went in/out of API |
| No pipeline graph | Cannot see Bedrock call #1 vs #2 vs SFN steps |

---

## 4. Recommended tech stack

Aligned with `docs/DEVELOPMENT_ROADMAP.md` and `docs/PROJECT.md`:

| Layer | Choice | Rationale |
| --- | --- | --- |
| Framework | **Next.js 15** (App Router) | Planned in roadmap; SSR optional; easy Vercel deploy |
| Language | **TypeScript** | Type-safe API client matching backend schemas |
| Styling | **Tailwind CSS** | Fast iteration, consistent spacing |
| Components | **shadcn/ui** | Accessible primitives: tabs, cards, dialogs, badges |
| Charts | **Recharts** or **Tremor** | Accuracy trend, calibration, tier breakdown |
| Data fetching | **TanStack Query** | Polling, cache, mutation status for run detail |
| API client | Generated or hand-written types from `MigrationRunResponse`, `GradeResponse`, etc. |
| Auth (later) | **Clerk** | Planned; MVP can use `owner_identity` string + `DEMO_API_KEY` |
| Deploy | **Vercel** (UI) + existing Railway (API) | Matches system design doc |

**Alternative for fastest path:** Evolve the vanilla `/ui` debug console into a richer single-page app first (Phase 11a), then migrate to Next.js (Phase 11b). This plan assumes **Next.js as the target** but recommends porting proven patterns from `/ui` (event log, loop banner, stage strip).

---

## 5. Information architecture

### 5.1 Primary navigation

```
┌─────────────────────────────────────────────────────────────────┐
│  Migration Oracle    [Dashboard] [New Migration] [History] [⚙]  │
└─────────────────────────────────────────────────────────────────┘
```

| Route | Purpose |
| --- | --- |
| `/` or `/dashboard` | Accuracy metrics, recent runs, system health |
| `/migrate` | Submit SQL + connect DB + start closed loop |
| `/runs` | Filterable run history |
| `/runs/[id]` | **Main observability surface** — full run detail |
| `/settings` | API base URL, demo API key, owner identity |

### 5.2 Run detail page layout (most important screen)

Three-column mental model on desktop; stacked on mobile:

```
┌──────────────────┬──────────────────────────────┬──────────────────┐
│  INPUTS          │  PIPELINE (closed loop)      │  OUTPUTS         │
│                  │                              │                  │
│  Migration SQL   │  [Predict][Approve][Verify]  │  Prediction      │
│  Schema snapshot │       [Grade][Remember]       │  Recommendation  │
│  Connection meta │  ● active stage highlighted   │  Grade vs actual │
│                  │  stage timing chips           │  Memory stored   │
├──────────────────┴──────────────────────────────┴──────────────────┤
│  TABS: Policy | Prediction | Memory | Verify | Grade | Raw JSON     │
├──────────────────────────────────────────────────────────────────────┤
│  LIVE CONSOLE (collapsible, pinned bottom)                           │
│  [timestamp] POST /predict 200 4.2s  ▶ expand request/response     │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 6. Page and component specifications

### 6.1 Dashboard (`/dashboard`)

**Purpose:** Answer “is the system healthy and learning?”

**Components:**

1. **Health strip** — `GET /health`: DB, AWS, CockroachDB version badges (reuse debug console pattern).
2. **Accuracy over time** — Line chart from `scalar_accuracy_trend[].scalar_accuracy_score` vs `created_at`.
3. **Confidence calibration** — Bar chart: `confidence_calibration[]` buckets vs `mean_scalar`.
4. **Memory corpus stats** — `memory_corpus.memories_ready`, `pending` embeddings.
5. **Retrieval usefulness** — Single stat card: `corr_retrieval_count_vs_accuracy` + `fraction_with_retrieval`.
6. **High-risk flag quality** — Mini confusion matrix: TP/FP/FN/TN from `high_risk_flag_precision_recall`.
7. **Recent runs table** — Last 10 from `GET /runs?limit=10`, link to detail.

**Empty state:** “No graded runs yet. Submit a migration to start the loop.”

### 6.2 New migration (`/migrate`)

**Purpose:** Full input flow — the demo starts here.

**Step wizard (can be one page with sections):**

| Step | User action | API | UI feedback |
| --- | --- | --- | --- |
| 1. SQL | Paste migration SQL | `POST /runs` | Run ID created, status `pending` |
| 2. Connect | Paste read-only connection string OR secret ARN | `POST /runs/{id}/discover` | Schema snapshot summary; read-only badge |
| 3. Analyze | Click “Analyze” | `POST /runs/{id}/predict` | Redirect to `/runs/[id]` with prediction visible |
| 4. (Optional) One-shot | “Run full closed loop” | `POST /runs/{id}/closed-loop` | Skips manual approve for corpus batch runs |

**Schema snapshot panel** (from `run.schema_snapshot` after discover):
- Table count, total rows, total size
- Expandable table list: name, columns (types), row count, size
- Badge: `schema_discovery_status` (succeeded / failed)
- Prominent note: “Read-only connection verified” when discover succeeds

**SQL editor:**
- Syntax-highlighted textarea (Monaco or CodeMirror lite)
- Example migrations dropdown (index create, add column, type change)
- Character count + parsed statement types preview (after predict)

### 6.3 Run detail (`/runs/[id]`) — core observability

#### A. Closed-loop pipeline header

Visual stepper (evolve `#loopSteps` from debug console):

| Stage | Active when | Done when |
| --- | --- | --- |
| Predict | `pending`, `predicting` | `explainability` present |
| Approve | `awaiting_approval` | approval recorded or status advanced |
| Verify | `running` | `completed` or `failed` |
| Grade | `completed` + no grade yet | `GET /grade` returns 200 |
| Remember | grade exists, no memory | `GET /memory` returns 200 |

Include **stage strip chips** (already in `app.js` `renderStageStrip`) as compact booleans below the stepper.

#### B. Policy panel (deterministic — authoritative)

**Data:** `run.policy_decision`, `run.risk_flags`, `run.explainability.policy`

**UI elements:**
- Decision badge: `allow` / `warn` / `block` with color
- `compatibility_risk`, `requires_manual_review`, `requires_expand_contract` flags
- **Findings table:** rule_id, severity, objects, explanation (from `driving_findings`)
- Parsed statement types as tags

**Copy rule (from Phase 9):** Never frame as “lock duration.” Use backfill duration, storage growth, resource saturation, rollback safety.

#### C. Prediction panel (Bedrock call #1)

**Data:** `run.explainability.prediction`, `run.explainability.confidence`, `predictions` table via run children if exposed

**UI elements:**
- **Metric cards:**
  - Duration: `estimated_duration_seconds` (format as `42s` or `2m 10s`)
  - Storage: `estimated_storage_mb` MB
  - Rollback risk: `low` / `medium` / `high` with color
  - Confidence: gauge showing `adjusted_confidence` (0–100%)
- **Confidence breakdown:** list `confidence.adjustments[]` with reason + amount (why confidence was reduced)
- **Narrative:** `risk_explanation`, bullet lists for `key_assumptions`, `uncertainty_notes`
- **Metadata footer:** `model_version`, `prompt_template_version`, `shadow_scale_tier`, `prediction_target: shadow_run_only`
- **Repair indicator:** if `repair_retried`, show “JSON repaired on retry” badge

#### D. Memory retrieval panel (hackathon centerpiece)

**Data:** `run.explainability.memory`

**UI elements:**
- Header: `retrieved_count` memories, `weak_retrieval` warning if true
- **Memory cards** (one per `memories[]`):
  - `similarity_score` as progress bar (0–1)
  - `migration_summary` (truncated, expand)
  - Predicted vs actual duration/storage from past run
  - `surprise_notes` if present
  - Link to source run `migration_run_id` if available
- **Attribution expander:** `attribution` object — vector candidates, re-rank factors (tier proximity, flag overlap)
- **Demo callout:** highlight pairs where SQL wording differs but mechanism matches

**Empty state:** “No similar past migrations in corpus yet. Accuracy improves as graded runs accumulate.”

#### E. Recommendation panel (Bedrock call #2)

**Data:** `run.recommendation`

**UI elements:**
- Strategy headline: `recommended_strategy`
- Numbered `rollout_steps`
- `suggested_deployment_window`, `rollback_guidance`
- Checklist: `monitoring_checklist`
- Collapsible: `safer_alternative_plan`, `rationale`
- **Approve actions** (when `awaiting_approval`):
  - Proceed → `POST /approve` `{ decision: "proceed", start_workflow: true }`
  - Accept recommended → `{ decision: "accept_recommended" }`
  - Cancel → `{ decision: "cancel" }`
  - Override rationale field (required when `policy_decision === "block"`)

#### F. Verify / shadow execution panel

**Data:** `run.status`, `run.workflow_status`, `run.sfn_execution_arn`, shadow cluster fields on run response

**UI elements:**
- **SFN step timeline** (static mapping from `infra/stepfunctions/migration_workflow.asl.json`):
  ```
  DiscoverSchema → ProvisionShadow → LoadSchema → ExecuteMigration
  → CollectMetrics → PersistResults → Cleanup
  ```
  Highlight current step from `workflow_status` / sync response.
- **Sync control:** `POST /runs/{id}/sync-workflow` button + auto-poll every 2s while `status === "running"`
- **Shadow cluster card:** provision/seed/migrate/teardown timings when available
- **Job watch** (if artifact URL exposed later): live progress; MVP shows last known job state from execution result
- **Timeout badge** if execution exceeded limit

#### G. Grade panel — prediction vs actual

**Data:** `GET /runs/{id}/grade`, execution results on run

**UI elements — comparison table:**

| Dimension | Predicted | Actual | Within band? | Score |
| --- | --- | --- | --- | --- |
| Duration (sec) | from prediction | `duration_abs_error_seconds` context | `duration_within_band` | from `dimension_details` |
| Storage (MB) | from prediction | actual storage | `storage_within_band` | |
| Rollback risk | `rollback_predicted` | `rollback_actual_class` | `rollback_consistent` | |

- **Scalar accuracy:** large `scalar_accuracy_score` (0–1) with color threshold
- **Outcome class:** success / failure / partial / timeout
- **Surprise & lessons:** `surprise_notes`, `lessons_learned` (Bedrock prose, optional)
- **Timed out** banner when `timed_out === true` (still graded — intentional)

#### H. Memory stored panel

**Data:** `GET /runs/{id}/memory`

**UI elements:**
- `migration_summary`, `lessons_learned`, `schema_summary`
- `embedding_status`: ready / pending / failed
- `embed_text` preview (collapsible — what Titan embedded)
- `scalar_accuracy_score` from grade linkage
- Note: “This memory will influence future predictions via vector search.”

#### I. Raw JSON tab

Full `GET /runs/{id}`, grade, memory, approval responses — for developers. Pretty-printed, copy button.

### 6.4 History (`/runs`)

- Filter by status (`pending`, `awaiting_approval`, `running`, `completed`, `failed`)
- Sort by `updated_at` desc
- Columns: status, SQL snippet, policy, scalar accuracy (if graded), updated
- Pagination: `limit` / `offset`

### 6.5 Settings (`/settings`)

- API base URL (default: env `NEXT_PUBLIC_API_URL`)
- `X-API-Key` for demo mode
- `owner_identity` default for new runs
- Link to `/docs` and `/ui` debug console

---

## 7. Live console — data in, out, and processing

The user explicitly wants to **see everything going on** in a console. This is the most important UX addition beyond pretty panels.

### 7.1 Console behavior (evolve debug console `app.js`)

**Location:** Persistent drawer at bottom of every page (default collapsed on mobile, open on `/runs/[id]`).

**Each log entry captures:**

| Field | Source |
| --- | --- |
| Timestamp | Client |
| HTTP method + path | Request |
| Status code | Response |
| Duration (ms) | Client `performance.now()` |
| Outcome | pass / fail / info |
| Request body | JSON.stringify (redact connection strings) |
| Response body | JSON.stringify (truncate > 50KB with “expand”) |
| Correlation | `run_id` when path contains UUID |

**Event types beyond HTTP:**

| Event | When |
| --- | --- |
| `poll` | `GET /runs/{id}` during running (every 2s) |
| `stage_change` | Run status or workflow_status changed |
| `prediction_ready` | `explainability` appeared |
| `grade_ready` | Grade endpoint first returns 200 |

### 7.2 Pipeline trace view (synthetic spans)

Backend does not yet emit OpenTelemetry spans. The UI can **reconstruct a trace** from API responses and timestamps:

```
Run created ─────────────────────────────────────────────►
  ├─ discover_schema (POST /discover)          1.2s ✓
  ├─ policy_analyze (inside /predict)          (inferred)
  ├─ memory_retrieve (inside /predict)         3 candidates
  ├─ bedrock_predict (inside /predict)         2.8s ✓
  ├─ bedrock_recommend (inside /predict)       1.9s ✓
  ├─ awaiting_approval                         (human gate)
  ├─ start_workflow (POST /approve)            ✓
  ├─ sfn: ProvisionShadow                      45s ✓
  ├─ sfn: ExecuteMigration                     120s ✓
  ├─ grade (auto)                              ✓
  └─ remember (embedding)                      pending
```

**Implementation:** Store stage timestamps on the client from poll diffs; optionally add `explainability.pipeline_timings` in a small backend follow-up (see §9).

### 7.3 Console filters

- All / API only / Errors only
- Filter by run ID
- Export session log as JSON (for demo debugging)

### 7.4 Security in console

- **Redact** `database_url`, passwords, full connection strings in log display
- Never log `X-API-Key` value
- Show `connection_secret_arn` as masked `arn:.../secret:****`

---

## 8. API client and polling strategy

### 8.1 TanStack Query keys

```text
['health']
['runs', { status, limit, offset }]
['runs', runId]
['runs', runId, 'grade']
['runs', runId, 'memory']
['runs', runId, 'approval']
['metrics', 'accuracy']
```

### 8.2 Polling rules

| Condition | Interval | Endpoint |
| --- | --- | --- |
| `status === 'running'` | 2s | `GET /runs/{id}` + `POST /sync-workflow` |
| `status === 'predicting'` | 1s | `GET /runs/{id}` |
| `embedding_status === 'pending'` on memory | 5s | `GET /runs/{id}/memory` |
| Dashboard metrics | 30s | `GET /runs/metrics/accuracy` |
| Otherwise | No poll | Manual refresh button |

### 8.3 Mutation flow example (predict)

```text
User clicks "Analyze"
  → console: info "predict started"
  → POST /runs/{id}/predict
  → console: pass/fail with full bodies
  → invalidate ['runs', runId]
  → UI switches to Prediction + Memory tabs
  → pipeline header: Predict → done, Approve → active
```

---

## 9. Optional backend enhancements (small, high leverage)

The frontend can ship against existing APIs. These backend additions would make the console and pipeline view materially better:

| Enhancement | Effort | Benefit |
| --- | --- | --- |
| `GET /runs/{id}/events` — append-only stage log | Medium | Real pipeline trace without client inference |
| Include `shadow_cluster` + `execution_result` in `MigrationRunResponse` | Low | Verify panel without extra calls |
| `explainability.pipeline_timings` on predict response | Low | Show Bedrock latency split |
| SSE or WebSocket for run status | Medium | Replace polling; nicer live demo |
| `GET /runs/{id}/artifacts` — S3 job-watch presigned URL | Medium | Live migration progress |
| OpenTelemetry spans on predict/grade paths | Medium | Future Langfuse/Phoenix export |

**Recommendation:** Ship MVP without these; add `shadow_cluster` + `execution_result` to run detail response first if verify panel feels empty.

---

## 10. Visual design system

### 10.1 Aesthetic direction

Extend the debug console palette (`frontend/styles.css`):

- **Primary:** `#0c5c42` (Cockroach-adjacent green) — actions, success
- **Danger:** `#9b1c1c` — block policy, failed runs
- **Info:** `#1f4e79` — running, informational
- **Warn:** `#8a5a00` — warn policy, weak retrieval
- **Console:** `#0f1411` background, monospace — distinct from main UI
- **Fonts:** IBM Plex Sans + Plex Mono (already in debug CSS)

### 10.2 Status semantics

| Status | Color | Icon |
| --- | --- | --- |
| `pending` | gray | circle |
| `predicting` | blue pulse | spinner |
| `awaiting_approval` | amber | hand |
| `running` | blue pulse | play |
| `completed` | green | check |
| `failed` | red | x |

### 10.3 Risk / policy semantics

| `policy_decision` | Badge |
| --- | --- |
| `allow` | green outline |
| `warn` | amber fill |
| `block` | red fill + “override requires rationale” |

---

## 11. Implementation phases

### Phase 11a — Enhanced debug console (1–2 days)

**Goal:** Immediate visibility without Next.js scaffold.

- Add discover form, closed-loop button, sync-workflow, metrics fetch to `/ui`
- Add polling while `running`
- Replace raw `<pre>` with structured cards for prediction, memory, grade
- Expand event log with request/response bodies
- Add simple accuracy line chart (Chart.js CDN)

**Checkpoint:** Full demo possible from `/ui` alone.

### Phase 11b — Next.js scaffold (1 day)

- `npx create-next-app` in `frontend/` or `web/` with TypeScript, Tailwind, shadcn
- API client module, env config, layout with nav
- Port health + run list from debug console

### Phase 11c — Run detail observability (2–3 days)

- Pipeline header + tabs (Policy, Prediction, Memory, Verify, Grade)
- Live console drawer
- Approve flow with validation
- Polling + sync-workflow

### Phase 11d — Dashboard + migrate wizard (1–2 days)

- `/dashboard` charts from metrics endpoint
- `/migrate` wizard with schema snapshot
- `/runs` history with filters

### Phase 11e — Polish + demo hardening (1–2 days)

- Empty states, loading skeletons, error toasts
- Mobile responsive layout
- Seed demo data script alignment
- Fresh-browser demo verification (Phase 12 precursor)

**Total estimate:** 6–10 days for one developer; 11a alone unblocks understanding in 1–2 days.

---

## 12. Demo-critical flows (must work for judges)

### Flow A — “See the prediction before verify” (30 seconds)

1. Paste `CREATE INDEX idx_users_email ON users(email);`
2. Discover schema (or use pre-seeded run)
3. Predict → show duration, storage, confidence, memory retrieval
4. **Stop here** — prediction visible while verify has not started

### Flow B — “Memory found a similar migration” (45 seconds)

1. Open run where `explainability.memory.retrieved_count > 0`
2. Memory panel shows similarity scores + past outcome
3. Narrate: “Different wording, same mechanism”

### Flow C — “Full closed loop” (2–3 minutes)

1. Predict → Approve proceed → watch verify stages poll
2. Grade appears → side-by-side predicted vs actual
3. Memory stored → dashboard accuracy tick moves

### Flow D — “Console proves what happened” (any time)

1. Open live console
2. Expand `POST /predict` response
3. Show `explainability.memory` and `confidence.adjustments` in response body

---

## 13. Testing checklist

| Test | Pass criteria |
| --- | --- |
| Health probe | Badges match `/health` |
| Create + discover + predict | Schema summary renders; prediction cards populated |
| Approve proceed | Status → `running`; workflow starts when configured |
| Polling | UI updates without manual refresh during `running` |
| Grade display | Comparison table matches `GradeResponse` |
| Memory panel | Similarity bars match `explainability.memory.memories` |
| Metrics charts | Trend line has ≥1 point after corpus runs |
| Console | Every user action produces log entry with timing |
| API key | 401 handled with clear message when key wrong |
| Empty corpus | Memory panel shows empty state, not error |
| Block policy | Override rationale required before proceed |

---

## 14. Out of scope for Phase 11 (explicit)

- Clerk auth (use `owner_identity` + API key for demo)
- Billing UI
- Multi-tenant admin
- Editing migration SQL after create
- Running arbitrary SQL against customer DB from UI
- Embedding vector visualization (UMAP of memories) — future nice-to-have
- Full OpenTelemetry / Langfuse integration — future Phase 12+

---

## 15. File structure (proposed)

```text
web/                          # Next.js app (or evolve frontend/)
├── app/
│   ├── layout.tsx            # Nav + console provider
│   ├── page.tsx              # Dashboard
│   ├── migrate/page.tsx
│   ├── runs/page.tsx
│   ├── runs/[id]/page.tsx    # Main observability
│   └── settings/page.tsx
├── components/
│   ├── pipeline/
│   │   ├── ClosedLoopStepper.tsx
│   │   └── StageStrip.tsx
│   ├── panels/
│   │   ├── PolicyPanel.tsx
│   │   ├── PredictionPanel.tsx
│   │   ├── MemoryRetrievalPanel.tsx
│   │   ├── RecommendationPanel.tsx
│   │   ├── VerifyPanel.tsx
│   │   └── GradeComparisonPanel.tsx
│   ├── charts/
│   │   ├── AccuracyTrendChart.tsx
│   │   └── ConfidenceCalibrationChart.tsx
│   └── console/
│       ├── LiveConsole.tsx
│       └── ConsoleProvider.tsx
├── lib/
│   ├── api.ts                # fetch wrapper + types
│   ├── polling.ts
│   └── redact.ts             # console secret redaction
└── types/
    └── api.ts                # Mirror backend schemas

frontend/                     # Keep debug console until web/ parity
├── index.html
├── app.js
└── styles.css
```

---

## 16. Key references

### Project docs
- `docs/PROJECT.md` — product thesis, demo script
- `docs/API.md` — HTTP contract
- `docs/DEVELOPMENT_ROADMAP.md` — Phase 11 checklist
- `docs/phase9.md` — prediction + explainability shape
- `docs/phase10.md` — grading + memory retrieval shape

### Backend source (UI data contracts)
- `backend/app/prediction/models.py` — `ExplainabilityBundle`, prediction schemas
- `backend/app/memory/metrics.py` — accuracy metrics SQL
- `backend/app/schemas/grade.py` — `GradeResponse`, `MemoryResponse`
- `backend/app/schemas/migration_run.py` — run list/detail shapes
- `frontend/app.js` — existing console patterns to port

### External inspiration
- [Langfuse Agent Graphs](https://langfuse.com/docs/observability/features/agent-graphs)
- [Arize Phoenix Tracing](https://arize.com/docs/phoenix/tracing/llm-traces)
- [SafeMigrate](https://github.com/SarveshTikekar/SafeMigrate)
- [pg-dash](https://github.com/indiekitai/pg-dash)
- [ExplainerDashboard](https://github.com/oegedijk/explainerdashboard)
- [Migratrix](https://migratrix.com/)
- [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)

---

## 17. Success criteria

Phase 11 is complete when:

1. A new user can submit a migration, see schema + policy + prediction + memory retrieval **without reading JSON**.
2. During shadow execution, the UI visibly progresses through verify stages (polling or sync).
3. After completion, predicted vs actual is shown in a comparison table with scalar accuracy.
4. The dashboard shows a real accuracy trend from `GET /runs/metrics/accuracy`.
5. The live console logs every API interaction with expandable request/response bodies.
6. The three-minute demo script in `docs/PROJECT.md` can be executed entirely from the new UI.

---

## 18. Immediate next step

**Start with Phase 11a** — enhance `/ui` before scaffolding Next.js. The highest-impact additions in order:

1. Polling + `sync-workflow` while `running`
2. Structured prediction / memory / grade cards (stop raw JSON as default)
3. Schema discover form on create flow
4. Accuracy chart on a new “Metrics” section
5. Request/response bodies in event log

This delivers visibility in hours, validates the component design, and de-risks the Next.js build.

---

## 18b. Implementation status (2026-07-21)

Landed in-repo (operator console path; no Next.js):

| Item | Status |
| --- | --- |
| Seed script → `CORPUS_OWNER_IDENTITY` | Done (`scripts/seed_demo_memories.py`) |
| `GET /memories`, `/memories/health`, `/memories/corpus-identity` | Done |
| `scripts/corpus_health.py` | Done |
| `GET /runs/{id}/shadow-cluster`, `execution-result`, `model-traces` | Done |
| `retrieval_attempted` / `retrieval_mode` / `empty_vs_never_attempted` | Done |
| Durable Bedrock traces in `explainability.bedrock_traces` | Done |
| `/ui` operate + corpus + metrics tabs, discover, polling, panels, vector callout, side-by-side DDL | Done |
| `CORS_ORIGINS` default + `.env.example` docs | Done |
| AWS SAM deploy / Bedrock access / real graded corpus | **Still blocked on operator AWS setup** |

---

## 19. Open questions — answered (2026-07-21)

Confirmed by operator. Earlier assumptions that conflict with these answers are obsolete.

### Deployment and environment

| # | Question | Answer |
| --- | --- | --- |
| 1 | Where does the backend run? | **AWS for demo and submission.** Local is development only. Railway is out. A localhost-only demo fails the hackathon requirement for a functional demo URL. |
| 2 | Has `sam deploy` been run? | **No.** SAM stack is defined but undeployed. `MIGRATION_WORKFLOW_ARN` is empty. Verify → grade → remember cannot complete until deploy lands. |
| 3 | Bedrock model access? | **Not granted yet.** Assume it lands shortly. UI and APIs must degrade visibly when Bedrock is unavailable (clear error, not blank panels). |

### Data and demo readiness

| # | Question | Answer |
| --- | --- | --- |
| 4 | Seed corpus state? | **Unverified and likely broken:** (a) seed script uses `owner_identity = "demo-corpus"` instead of reserved `CORPUS_OWNER_IDENTITY = "__migration_oracle_corpus__"`; (b) embeddings likely never generated (`pending`). Hybrid retrieval will not see those rows as corpus. |
| 5 | Graded runs? | **Zero.** Nothing has completed the full loop end to end. Empty states must be honest and loud. |
| 6 | Deadline? | **August 18, 2026 @ 5:00pm EDT** (~four weeks). Confirmed on Devpost. |

### Scope and priorities

| # | Question | Answer |
| --- | --- | --- |
| 7 | Auth / Clerk? | **No.** Soft `owner_identity` string only, same pattern as `approver_identity`. Do not add Clerk or real auth. |
| 8 | Deployed demo URL? | **Required.** Demo and submitted URL hit deployed AWS infrastructure. Same-origin `/ui` served by the control plane is the preferred path; separate frontend origin needs explicit CORS. |
| 9 | Shadow / execution on API? | **Not exposed.** Repositories exist (`ShadowClusterRepository`, `ExecutionResultRepository`) but **no read routes**. Must add read-only endpoints. Do not guess shapes — mirror DB models. |

### Technical details

| # | Question | Answer |
| --- | --- | --- |
| 10 | `MigrationRunResponse` contents? | Schema in `backend/app/schemas/migration_run.py` **does** include Phase 9/10 fields (`explainability`, `recommendation`, `risk_flags`, etc.). `docs/API.md` examples are stale/incomplete — fix the docs to match OpenAPI, then generate client types from OpenAPI. |
| 11 | CORS? | Already env-driven via `CORS_ORIGINS` (`backend/app/config.py`), default `http://localhost:3000` only. Keep localhost for dev; make multi-origin list configurable; document adding the deployed frontend origin; **no wildcards**. |
| 12 | Discover input? | Support **both** `connection_secret_arn` (preferred for demo) and `database_url` (stores secret, returns ARN). UI must distinguish bad ARN, permissions failure, and unreachable DB in error states. |
| 13 | Sync-workflow polling? | Poll 2–3s initially, back off after ~1 minute, stop on terminal statuses, hard ceiling past longest timeout, cancel on unmount. Prefer `GET /runs/{id}` for UI refresh; call `sync-workflow` on a slower cadence or when workflow fields look stale — do not hammer SFN Describe every tick forever. |

### Demo narrative

| # | Question | Answer |
| --- | --- | --- |
| 14 | Name CockroachDB vector indexing in UI? | **Yes, in plain visible text.** Memory / retrieval panel must state that retrieval is served by a CockroachDB vector index using **Distributed Vector Indexing**. Judges must learn this from the UI. |
| 15 | Same-mechanism / different-vocabulary pair? | **Target pair:** defaulted `NOT NULL` column addition vs secondary index creation — near-zero lexical overlap, both trigger full-row backfill. UI must render current DDL and retrieved memory **side by side**. Embedding composition already prefers risk narrative + lessons over raw DDL (`compose_embed_text`); verify that remains true. |

---

## 20. Expanded observability requirements (additive)

This section expands Phase 11 beyond the original dashboard plan. Through-line: **see everything the system is doing without ad hoc SQL.** Operator console first; demo surface second. Not a product.

### 20.1 Corpus and memory visibility

**API + UI** to inspect the memory store:

- Every memory row: `owner_identity`, `scale_tier`, `migration_type`, embedding status, `created_at`, source `migration_run_id`.
- Full `embed_text` **verbatim** (already stored; do not truncate into uselessness).
- Health summary at top: total memories; counts per owner; count missing embeddings; count missing `scale_tier` or `migration_type`. Nonzero health problems must look **loud**, not like a clean empty state.
- Filter by `owner_identity`, including `__migration_oracle_corpus__`.

**Also:** diagnostic endpoint and/or CLI maintenance command that prints corpus health as structured JSON for terminal use.

**Earlier-phase fix required:** `backend/scripts/seed_demo_memories.py` uses `OWNER = "demo-corpus"`. Must use `CORPUS_OWNER_IDENTITY` from `app.memory.constants`. Flag as Phase 10 fix.

### 20.2 Retrieval transparency

For every prediction, surface existing retrieval attribution (do not rebuild):

- Ranked memories, similarity scores, hybrid re-rank factors (tier match, migration type match, schema shape, flag overlap).
- Strong vs weak retrieval, and whether weak retrieval triggered Phase 9 confidence reduction.
- Distinguish **retrieval returned nothing** vs **retrieval never attempted** (today both can look like empty `retrieved_count: 0`). Add an explicit field such as `retrieval_attempted: true|false` and `retrieval_mode: hybrid|stub|skipped` into explainability when needed.

### 20.3 Model input and output visibility

For every Bedrock call (prediction and recommendation):

- Exact prompt sent (including assembled retrieval context)
- Raw response before parsing
- Parsed structured result
- Model id + prompt template version
- Latency and token counts when available
- Both attempts if schema validation failed and repair retry fired

**Persist durably** (not only logs). If full prompts are heavy: keep most recent **N** runs, N configurable (e.g. `BEDROCK_TRACE_RETENTION_RUNS`). This is an earlier-phase change (prediction/recommendation engines + schema).

### 20.4 Run lifecycle visibility (success and failure)

- Runs list: every run regardless of outcome — status, owner, created, duration, terminal result. Failed/cancelled as visible as completed.
- Run detail timeline: created → predicted → approved → provisioned → seeded → executed → verified → torn down → graded → remembered. Per stage: timestamp, duration, outcome; real error text on failure.
- Include shadow cluster + execution actuals beside predicted values with per-dimension error.

**Backend gap confirmed:** add `GET /runs/{id}/shadow-cluster` and `GET /runs/{id}/execution-result` (or embed in run detail). Repositories already exist.

### 20.5 Drive the loop from the UI

Discover (ARN or URL) → create run → predict → approve / accept / cancel → live progress → grade + new memory. Loading and distinct error states for discover failures.

### 20.6 Polling safety

2–3s start → back off after ~60s → stop on terminal → hard ceiling past longest configured timeout → cancel on unmount. Background tabs must not hammer forever.

### 20.7 Types and contracts

Generate frontend types from **live OpenAPI**. If a response shape mismatches the schema, fix the schema (and `docs/API.md`), do not invent client types.

### 20.8 CORS and deployment

`CORS_ORIGINS` comma-list; keep localhost for local Next/dev hosts; document adding deployed frontend origin; no `*`. Prefer same-origin deploy of `/ui` with the API so the demo URL needs no CORS for the primary surface.

### 20.9 Demo narrative (mandatory UI copy)

- Visible text: retrieval uses CockroachDB **Distributed Vector Indexing**.
- Side-by-side DDL vs retrieved memory for the backfill-mechanism pair.
- Verify `compose_embed_text` composition (summary → risk → lessons → surprise → capped DDL excerpt).

### 20.10 Constraints (reaffirmed)

- No fabricated memories, synthetic similarity scores, or fake history. Empty = genuinely empty and labeled as such.
- Correct with zero memories and zero grades; degrade visibly.
- Match existing conventions.
- Flag every earlier-phase code change with reason.
- Operator console + demo surface only: no new component library, no auth, no theming project.

---

## 21. Build plan (ordered by what unblocks the most)

Deadline: **2026-08-18**. Single developer. AWS deploy is on the critical path for the full loop; observability must work even before the loop completes.

### Tier 0 — Unblock seeing the truth (days 1–2)

Without these, you still cannot tell if the corpus or runs are healthy.

| Order | Work | Why first |
| --- | --- | --- |
| 0.1 | Fix seed script `owner_identity` → `CORPUS_OWNER_IDENTITY`; add `scripts/corpus_health.py` + `GET /memories` list/health endpoints | Corpus is currently invisible / wrongly scoped |
| 0.2 | `GET /runs/{id}/shadow-cluster`, `GET /runs/{id}/execution-result` (+ OpenAPI schemas) | Failed provision runs become diagnosable |
| 0.3 | Enrich `explainability.memory` with `retrieval_attempted` / mode; surface attribution already stored | Empty vs never-attempted stop looking identical |
| 0.4 | Expand `/ui`: Corpus browser + Runs list showing failed runs + loud health summary | Operator can stop writing SQL |

### Tier 1 — Drive and watch the loop (days 2–5)

| Order | Work | Why |
| --- | --- | --- |
| 1.1 | Discover + create + predict + approve flows in `/ui` with real error taxonomy | Can exercise API without curl |
| 1.2 | Safe polling (2–3s → backoff → terminal stop → ceiling → unmount cancel) | Minutes-long runs without hammering |
| 1.3 | Structured prediction / retrieval / grade panels + vector-index callout + side-by-side DDL | Demo narrative without JSON |
| 1.4 | Sync `docs/API.md` to OpenAPI; generate client types if/when TS lands | Contract correctness |

### Tier 2 — Model I/O durability (days 4–7, parallelizable)

| Order | Work | Why |
| --- | --- | --- |
| 2.1 | Persist Bedrock traces (prompt, raw, parsed, model, template, latency, tokens, repair attempts) for last N runs | Review after the fact without log grep |
| 2.2 | `GET /runs/{id}/model-traces` + UI inspector | Judges/operators see what the model saw |

### Tier 3 — Deploy and close the loop (must finish before demo week)

| Order | Work | Why |
| --- | --- | --- |
| 3.1 | Grant Bedrock access; `sam deploy`; wire `MIGRATION_WORKFLOW_ARN` + bucket into env | Verify path becomes real |
| 3.2 | Deploy control plane + `/ui` on AWS; set `CORS_ORIGINS` if UI is separate | Demo URL requirement |
| 3.3 | Run real graded corpus (NOT NULL add-column + CREATE INDEX pair) through full loop; repair embeddings | Accuracy curve + retrieval beat become real |
| 3.4 | Accuracy metrics panel from `GET /runs/metrics/accuracy` | Learning narrative |

### Explicitly deferred / optional

- Next.js + shadcn rewrite (roadmap listed it; **not required** if `/ui` is the deployed operator/demo console). Prefer evolve `/ui` under deadline pressure.
- Clerk / billing / theming / new component libraries.
- OpenTelemetry → Langfuse export (nice later; durable Bedrock traces cover the demo need).

---

## 22. Ambiguities found in the repo (with proposed defaults)

| Ambiguity | Evidence | Proposed default |
| --- | --- | --- |
| Seed script vs “never fabricate” | `seed_demo_memories.py` creates synthetic completed runs/grades/memories without shadow execution; Phase 10/operator rules forbid fabricated history | **Fix identity + embedding repair for any existing rows; stop relying on synthetic seed for the demo.** Prefer a small set of **real** closed-loop graded runs. Keep script only as a last-resort offline tool, clearly labeled non-demo, or rewrite it to only insert after real grade+memory write paths. |
| “Retrieval never attempted” | Live DI uses `HybridMemoryRetrieval`; stub is tests/offline. Empty corpus still yields `retrieved_count: 0` with no explicit `retrieval_attempted` | Always set `retrieval_attempted: true` and `retrieval_mode: "hybrid"` on the live predict path; `false` / `"stub"` / `"skipped"` only when applicable. Persist on `explainability.memory`. |
| Model traces storage | Bedrock client returns text only; no durable prompt/raw/token store | New JSONB (or table) `model_invocations` keyed by `migration_run_id` + `kind` (`prediction`/`recommendation`/`grade_prose`), retention = last N runs configurable, default **N=50**. |
| Same-origin `/ui` vs separate frontend | `/ui` is mounted by FastAPI; CORS defaults to `:3000` | **Ship demo as same-origin `/ui` on the AWS control plane.** Keep CORS configurable for optional separate host. |
| Polling + sync-workflow cost | Sync likely calls SFN Describe | Poll `GET /runs/{id}` every 2–3s; call `sync-workflow` every **10–15s** or when `workflow_status` unchanged for > interval while still `running`. |
| OpenAPI type generation without Next.js | Operator said generate types; `/ui` is vanilla JS | Generate OpenAPI JSON in CI / `scripts/export_openapi.py`; if staying on vanilla `/ui`, treat schema as contract tests. If a TS client appears later, consume the same schema. Do not hand-write duplicate types. |
| Discover prefers ARN vs URL | Both supported by API | UI: primary field = secret ARN; advanced toggle = database URL. Document both. |
| Token counts from Converse API | May or may not be returned depending on response | Store when present; show `n/a` when absent — never invent. |

---

## 23. What in the expanded ask is wrong or unnecessary (given the repo)

| Claim / ask | Verdict |
| --- | --- |
| “CORS is currently localhost:3000 only” and must be made configurable | **Partially outdated.** It is **already** configurable via `CORS_ORIGINS`. Work left: document multi-origin deploy usage; ensure no wildcard; include `http://127.0.0.1:3000` if needed. |
| “The retrieval log already exists from Phase 9. Surface it, do not rebuild it.” | **Correct.** Attribution lives in `explainability.memory` (+ hybrid `attribution`). Surface it. Only add fields that are missing (`retrieval_attempted`). |
| Full Next.js + Tailwind + shadcn from roadmap §Phase 11 | **Unnecessary under constraints** (“no new component library”, single dev, four weeks, AWS demo URL). Evolving `/ui` same-origin is lower risk. Next.js remains optional if time remains after Tier 0–3. |
| Clerk auth | **Unnecessary / rejected.** |
| Seeded synthetic corpus for the accuracy curve | **Conflicts with “do not fabricate.”** Demo accuracy points must come from real graded runs. |
| Rebuilding hybrid retrieval UI logic client-side | **Unnecessary.** Rank/scores/factors are already in attribution JSON. |
| Wild speculation that `MigrationRunResponse` lacks explainability | **Wrong.** Schema already has it; update stale `API.md` examples. |
| Embedding text composition rewrite | **Mostly unnecessary** if `compose_embed_text` still matches Phase 10 order. **Verify**, only change if DDL still dominates or mechanism pair fails to retrieve. |

---

## 24. Implementation prompt (for the coding agent)

Use this block as the standing prompt when implementing Phase 11 / observability work. It incorporates Phase 10 rules, this document, and operator confirmations.

```text
You are implementing Migration Oracle observability + operator UI in this repo.

CONTEXT
- Product: predict → approve → verify → grade → remember migration advisor.
- Deadline: 2026-08-18. Demo URL must hit AWS (not localhost-only).
- SAM not deployed yet; Bedrock access pending; zero graded runs; corpus seed
  likely broken (wrong owner_identity, missing embeddings).
- No Clerk/auth. owner_identity is a soft string.
- No fabricated memories or synthetic similarity scores.
- Operator console + demo surface only: no new component library, no theming,
  no product chrome.

READ FIRST
- docs/phase11basic.md (this file), docs/phase10.md, docs/PHASE_10_GRADING_AND_MEMORY.md,
  docs/API.md, docs/HACKATHON_TOOLS.md, frontend/*, backend/app/api/routes/runs.py,
  backend/app/memory/*, backend/app/schemas/migration_run.py

MUST BUILD (in priority order)
1. Corpus health API + CLI + /ui browser (full embed_text, loud health counts,
   filter by owner including __migration_oracle_corpus__).
2. Fix seed script to CORPUS_OWNER_IDENTITY; do not demo with fabricated history.
3. Read-only shadow-cluster and execution-result endpoints; show failed runs.
4. Surface explainability.memory attribution; distinguish empty vs never attempted.
5. /ui flows: discover, create, predict, approve/accept/cancel, live poll, grade,
   memory appear; CockroachDB Distributed Vector Indexing callout; side-by-side
   DDL vs retrieved memory.
6. Durable Bedrock traces (prompt, raw, parsed, model, template, latency, tokens,
   repair attempts) retained for last N runs; UI to inspect.
7. CORS_ORIGINS documented; no wildcards; prefer same-origin /ui on AWS.
8. OpenAPI is source of truth; fix schema/docs rather than inventing client types.
9. Safe polling: 2–3s, backoff after 1m, stop on terminal, hard ceiling, cancel
   on unmount.

CONSTRAINTS
- Match existing code conventions.
- Flag every earlier-phase change with reason.
- Empty states must look empty and honest.
- Never invent token counts, similarity scores, or memories.
```

---

## 25. Earlier-phase changes expected (flag when implementing)

| Change | Phase origin | Reason |
| --- | --- | --- |
| `seed_demo_memories.py` owner → `CORPUS_OWNER_IDENTITY` | Phase 10 | Corpus rows invisible to hybrid retrieval scopes |
| Optional: purge or re-key existing `demo-corpus` rows | Phase 10 | Orphaned under wrong identity |
| `explainability.memory.retrieval_attempted` (+ mode) | Phase 9/10 | Empty vs never-attempted ambiguity |
| `model_invocations` persistence + retention | Phase 9 | Durable Bedrock I/O visibility |
| `GET .../shadow-cluster`, `GET .../execution-result` | Phase 7/8 | Data exists in DB, not on HTTP |
| `docs/API.md` examples updated to match schemas | Docs | Stale contract |
| `CORS_ORIGINS` docs + multi-origin deploy note | Phase 1/config | Demo URL + optional separate frontend |
