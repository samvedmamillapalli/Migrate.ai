# CockroachDB Managed MCP — Real Integration Plan

Status: **plan, not yet implemented.** The prompt (§6 / `backend/app/shadow/prompts/blast_radius_investigation_v1.txt`)
is written and ready to use once the code in §5 exists to load it — the text
file itself is inert until then.

Scope: make the CockroachDB Managed MCP Server an actually-functional, core
part of the app, replacing the current cosmetic placeholder. Every claim below
is anchored to a file path and line number, or to an external source with a
link. Anything about the real MCP server's behavior that I could not verify
from official documentation is flagged as **unverified — spike first**, not
asserted as fact.

---

## 0. Current state: confirmed cosmetic, not a guess

This needed no inference — the codebase says so about itself.

`backend/app/shadow/job_watch.py:1-6`, the module docstring, verbatim:

> "Shadow job watch — **MCP-compatible blast-radius theater**. The
> CockroachDB Managed MCP Server exposes cluster/job introspection to IDE
> agents (`.cursor/mcp.json`). During ExecuteMigration we poll the same job
> surface via SQL (`SHOW JOBS` / `crdb_internal`) so the demo can show live
> backfill duration and schema-change job state **without** [connecting to
> MCP]."

And `docs/HACKATHON_TOOLS.md:10`, the internal judging cheat-sheet, states
the second CockroachDB tool claimed for judging is "**Managed MCP / job
watch**" — evidenced by "IDE: `.cursor/mcp.json`. Runtime:
`backend/app/shadow/job_watch.py`" — i.e., the credit is claimed from a
developer-tooling config file (`.cursor/mcp.json`, used only when *you*, the
human, edit code in Cursor) plus a function that never calls MCP at all.

The mechanics, precisely:

| Piece | File:line | What it actually does |
|---|---|---|
| `snapshot_schema_jobs()` | `job_watch.py:21-54` | **Real.** Plain SQL: `SELECT job_id, job_type, status, description, created FROM [SHOW JOBS] WHERE job_type IN (...) ORDER BY created DESC LIMIT 10`, run on the shadow cluster. This part genuinely works and is genuinely useful — it's just not MCP. |
| `mcp_tool_attribution()` | `job_watch.py:57-65` | **Fake.** Returns a hardcoded Python dict — `{"cockroachdb_tools": "Distributed Vector Indexing (memory retrieval) + Managed MCP Server / SQL job watch (shadow blast-radius)", "mcp_endpoint": "https://cockroachlabs.cloud/mcp", "runtime_watch": "SHOW JOBS on shadow cluster during ExecuteMigration"}`. No network call, no MCP client, nothing. |
| Callers | `migration_runner.py:144,189` | Spread this fake dict into `stage_timings` on both the success and failure path of every shadow migration. |
| Duplicated | `lambdas/handlers/execute_migration.py:79-81,106` | The **same literal string** is hardcoded a second time, independently, in the Lambda handler's return payload — two copies of one lie. |
| Rendered to the user | `frontend/.../migrations/[id]/page.tsx:594-607` | The "Jobs observed" section on the run detail page prints this string verbatim: *"Live SHOW JOBS on the shadow cluster during ExecuteMigration — same job surface Managed MCP uses for blast-radius watch."* — I saw this rendered live in a screenshot earlier this session (2026-07-30). |
| Also in marketing copy | `frontend/.../components/landing/HowItWorks.tsx:36` | The public-facing "How It Works" landing section repeats the same unverified claim: "Managed MCP / SHOW JOBS watch during shadow ExecuteMigration." |
| Dev-tool config | `.cursor/mcp.json` | Real, but scoped to *your* Cursor IDE session, not the running application. Points at `https://cockroachlabs.cloud/mcp` with header `mcp-cluster-id: d44d1dfa-cdb2-4d37-95fa-b36e5654647f` — useful evidence of the real endpoint/header shape (§1), but the running FastAPI app never reads this file. |
| Config field | `backend/app/config.py:124-130` | `cockroach_mcp_url` (default `https://cockroachlabs.cloud/mcp`) exists as a `Settings` field but nothing in the codebase reads `settings.cockroach_mcp_url` anywhere except this one definition — confirmed by a repo-wide grep for `cockroach_mcp_url` returning only this line. |

**Conclusion:** there is a real, working, useful job-introspection feature
here (`snapshot_schema_jobs`) sitting right next to a completely inert
config field and a hardcoded attribution string dressed up to look like the
real feature calls MCP. Fixing this means two things: (1) make the
attribution honest by actually calling MCP, and (2) — per your ask — make
MCP do something *only it* can do, not just re-narrate what the SQL path
already provides, so it's a real capability, not a relabeled one.

---

## 1. What the real CockroachDB Managed MCP Server actually offers

Researched from Cockroach Labs' own sources — not inferred, not guessed:

- **Endpoint:** `https://cockroachlabs.cloud/mcp` (confirmed twice: the blog
  post below, and the repo's own `.cursor/mcp.json`).
- **Tools exposed** ([Cockroach Labs blog, "Managed MCP Server for AI Agents"](https://www.cockroachlabs.com/blog/cockroachdb-ai-agents-managed-mcp-server/)):
  - Read-only (enabled by default): `list_databases`, `select_query`,
    `get_table_schema`.
  - Write (opt-in, requires explicit consent): `create_database`,
    `create_table`, `insert_rows`.
  - Explicitly **never** available, by design: `DROP`, `TRUNCATE`, or any
    other destructive statement.
- **Authentication** ([same source](https://www.cockroachlabs.com/blog/cockroachdb-ai-agents-managed-mcp-server/); [CockroachDB Cloud API auth docs](https://www.cockroachlabs.com/docs/cockroachcloud/cloud-api)):
  two mechanisms — OAuth 2.1 (Authorization Code + PKCE) for interactive
  human use, and **service-account API keys** for autonomous/headless use
  ("intended for fully autonomous environments" — i.e., exactly this app's
  situation). The sibling REST Cloud API uses `Authorization: Bearer
  {API_KEY}` with a service-account secret; this app already has a working
  one (`CCLOUD_API_SECRET`, used successfully by
  `app/shadow/ccloud_api_provider.py` for real cluster provisioning,
  verified multiple times this session against real infrastructure). Cockroach
  Labs states the MCP server "integrates natively with existing Cloud
  authentication, RBAC" — strongly suggesting the same service-account key
  authenticates to MCP too, but **this is unverified — spike first** (§4,
  Phase 0). The `.cursor/mcp.json` header `mcp-cluster-id` additionally scopes
  a session to one cluster.
- **Authorization model:** cluster-scoped, RBAC-checked per tool call; system
  tables are deny-listed even in read mode.
- **What none of the sources describe:** a Python/server-side SDK example
  (only IDE config snippets, e.g. Cursor/Claude Desktop). This app will be
  one of the first non-IDE, purely programmatic MCP clients for this server
  — flagged explicitly as new ground, not a well-trodden path.

Sources:
- [Managed MCP Server for AI Agents | CockroachDB Cloud (blog)](https://www.cockroachlabs.com/blog/cockroachdb-ai-agents-managed-mcp-server/)
- [CockroachDB and AI (docs)](https://www.cockroachlabs.com/docs/stable/cockroachdb-and-ai)
- [Authentication on CockroachDB Cloud](https://www.cockroachlabs.com/docs/cockroachcloud/authentication)
- [Use the CockroachDB Cloud API](https://www.cockroachlabs.com/docs/cockroachcloud/cloud-api)

---

## 2. Existing infrastructure this plan builds on (not from scratch)

- **Bedrock Converse API is already in use**, `backend/app/prediction/bedrock_client.py:178`
  (`self._client.converse(...)`) — but **no `toolConfig`/tool-use anywhere in
  the codebase** (confirmed: a repo-wide grep for `toolConfig`/`tool_use`
  returns nothing). Converse natively supports tool use for Claude models on
  Bedrock; this is additive, not a new calling convention.
- **A durable model-trace pattern already exists and is already rendered**:
  `ModelTrace`/`ModelTraceAttempt` (`backend/app/schemas/observability.py:151-170`),
  persisted to `migration_runs.explainability["bedrock_traces"]`
  (`backend/app/api/routes/runs.py:634-651`, `GET /runs/{id}/model-traces`),
  and displayed in the "Model Traces" section of the run detail page — I saw
  this rendered live this session (system prompt, user prompt, latency,
  token counts, per-attempt raw/parsed response, all expandable). A new MCP
  agent trace reuses this exact surface — same persistence field, same UI
  component, one new `kind` value.
- **Shadow clusters already legitimately have write access** —
  `app/shadow/schema_snapshot.py:111-114`'s own docstring: "Unlike
  customer-database discovery, the shadow connection legitimately has write
  access — it has to, to seed and migrate." This makes the shadow cluster
  the correct, safe, already-accepted place to point an MCP agent — it's
  disposable infrastructure by design, never the customer's database.
- **A working service-account credential already exists and is proven**:
  `CCLOUD_API_SECRET`, used successfully by the real (not mocked)
  `ccloud_api_provider.py` throughout this session's verification work.
- **House prompt style is established and consistent** across
  `app/prediction/prompts/prediction_v3.txt` and
  `app/grading/prompts/surprise_lessons_v1.txt`: strict role framing, a
  mandatory "blast radius = duration/storage/saturation/rollback, never lock
  duration" vocabulary constraint repeated verbatim in every prompt, a
  strict JSON-only output contract, explicit "you do not decide X, it's
  already final" deference to deterministic code, and UI-rendering-aware
  formatting rules embedded directly in the prompt. §6's new prompt matches
  this voice deliberately, not coincidentally.

---

## 3. Where MCP becomes real *and* a core part of the app

The wrong version of this plan makes MCP produce the exact same narrative
`snapshot_schema_jobs()` already produces, just slower and over a network
call — cosmetic-but-real is still not "core." The right version has MCP do
something the deterministic SQL path structurally cannot: **decide what to
look at**, not just report what a fixed query already fetched.

### Phase A — Foundational spike (no LLM yet, no UI change)

Build `backend/app/shadow/mcp_client.py`: a thin async wrapper around the
official `mcp` Python SDK (`pip install mcp` — not currently a dependency;
confirmed via `grep -i mcp pyproject.toml` returning nothing and `import mcp`
failing in the venv) that connects to `https://cockroachlabs.cloud/mcp` with
the service-account bearer token + `mcp-cluster-id` header scoped to a real
shadow cluster's ID, calls `list_tools()`, and calls `select_query` once for
something trivial (`SELECT 1`, or a real row count). This is a pure
connectivity spike: confirms auth actually works server-side (§1's flagged
unverified assumption), confirms the tool names/shapes match what the blog
post describes, and produces zero user-facing change. **Do this before
anything else — it's the one assumption the rest of the plan depends on.**

### Phase B — Core feature: agentic blast-radius investigation

This is the part that makes MCP genuinely load-bearing, not decorative.
Immediately after a migration executes on the shadow cluster (the existing
"measure" stage — see `docs/ai_audit.md` §C3's band layout, already the
named stage for this in the UI rail), run a bounded Claude tool-use loop
(Bedrock Converse + `toolConfig`) where the model has the MCP **read-only**
tools (`list_databases`, `get_table_schema`, `select_query`) live against the
just-migrated shadow cluster, and is asked to independently investigate
whether the migration actually did what it was supposed to — not re-run the
fixed `SHOW JOBS` query, but decide for itself what's worth checking (did
the column really get added with the right type/default? do a few sampled
rows actually reflect it? does an index that was supposed to be created
exist and look correct in `get_table_schema`? is there anything about the
resulting shape that looks off given the migration SQL?).

This is a genuine capability gap the deterministic path has: the SQL queries
in `migration_runner.py`/`schema_snapshot.py` were all decided in advance by
a human writing code once — they can never notice something unexpected that
nobody thought to query for ahead of time. An agent with live, general-purpose
query access can. That's the actual case for why this should be an LLM
loop and not just "call MCP instead of SQL to do the same fixed check" —
otherwise MCP is a slower detour to the same answer.

Output: a new `ModelTrace` with `kind: "blast_radius_investigation"`
(extending the existing `prediction | recommendation | grade_prose` set at
`observability.py:161`), persisted the same way predictions already are,
shown in the same "Model Traces" UI section — plus a short summary surfaced
in the shadow execution box (the "Jobs observed" section that currently
prints the fake attribution string gets the real finding instead). The
`ModelTraceAttempt` shape should be extended with a `tool_calls: list[{tool,
args, result_summary}]` field so the trace shows its receipts — which MCP
calls were actually made, not just the model's prose conclusion — matching
this product's whole "never fabricate, always show the measured truth" ethos
(the same standard already applied to `job_progress.py`'s "never fabricates
a progress value" rule and the storage-unverifiable-floor discussion in
`docs/ai_audit.md`).

### Phase C — Stretch: recommendation-time MCP access

Give the Phase 9 recommendation model (`app/prediction/prompts/recommendation_v3.txt`)
live read-only MCP access to the shadow cluster's schema once it's
provisioned, instead of only a static discovered-schema JSON blob, so it can
interactively drill into a specific table or index it's uncertain about
rather than reasoning from a frozen snapshot. This is a bigger structural
change — it requires the shadow cluster to exist *before* recommendation
runs, which is a pipeline-ordering change (today: predict → approve → shadow;
this would need something closer to predict → provision-shadow → recommend →
approve → migrate), a real re-sequencing, not just an added step. Flagged as
future work, intentionally not scoped further here — Phase B alone
satisfies "real and core" without touching pipeline ordering.

---

## 4. Technical implementation plan (Phase A + B)

**New dependency:** `mcp` (official Python MCP SDK) added to
`backend/pyproject.toml`'s `dependencies` list, alongside the existing
`boto3`/`httpx`/etc.

**New module — `backend/app/shadow/mcp_client.py`:**
- `ShadowMcpSession` — async context manager wrapping the SDK's streamable-HTTP
  client, constructed with `(cluster_id: str, api_secret: str, base_url: str
  = settings.cockroach_mcp_url)` — finally giving that config field a real
  reader.
- `list_tools()` → the MCP tool definitions, translated into Bedrock Converse
  `toolConfig` shape (name, description, input schema — MCP tool schemas are
  already JSON Schema, the same shape Converse expects, so this translation
  is closer to a pass-through than a real conversion).
- `call_tool(name, arguments)` → dict result, with a hard per-session cap on
  total calls (e.g. 8) so a confused model can't loop indefinitely against a
  live cluster — mirrors the existing bounded-retry discipline already used
  elsewhere in this codebase (`ccloud_api_provider.py`'s `max_retries`,
  `job_progress.py`'s `_MAX_POLLS`).

**Extend `BedrockClient`** (`app/prediction/bedrock_client.py`) with a
tool-use-capable method — e.g. `converse_with_tools(*, system_prompt,
user_prompt, tools, tool_executor, max_tool_calls=8) -> ModelTrace` — that
runs the standard Converse tool-use loop (model responds with a
`toolUse` content block → call `tool_executor` → feed a `toolResult` message
back → repeat until the model responds with plain text or the call cap is
hit) and returns everything as a populated `ModelTrace`/`ModelTraceAttempt`,
matching the existing trace shape so no new persistence path is needed.

**New service — `BlastRadiusInvestigationService`:**
Orchestrates: open a `ShadowMcpSession` for the shadow cluster that just
finished migrating → build tool config from `list_tools()` → call
`converse_with_tools()` with the §6 prompt and a user turn containing the
migration SQL + the deterministic `schema_diff`/`row_sample_after` already
captured (so the model isn't rediscovering things the app already knows
for free — it should spend its tool budget on verification, not on
re-deriving the table list) → persist the resulting trace to
`migration_run.explainability["bedrock_traces"]` → return a short summary
string for the shadow box.

**Wire-in point:** called from the same place `snapshot_schema_jobs()` is
called today — `migration_runner.py:128,170` (both the failure and success
path, right after the migration statement resolves and before teardown/hold)
— as an **additive** call alongside the existing SQL job-watch, not a
replacement. `snapshot_schema_jobs()` stays exactly as-is (it's real, it's
cheap, it's fast); the MCP investigation is a slower, deeper, complementary
check, not a rip-and-replace.

**Cost/latency guardrail:** cap at 8 tool calls and a fixed max-tokens
budget, same discipline as everything else in this app that touches a live
resource. This runs once per shadow migration (not per poll, not per UI
render) — same cost shape as the existing prediction/recommendation calls,
which the app already budgets for per run.

**Frontend:** extend the "Jobs observed" section
(`app/dashboard/migrations/[id]/page.tsx:594-607`) to render the real
investigation summary instead of the hardcoded string, and add the new
trace `kind` to the existing "Model Traces" panel (already generic over
`kind` — `ModelTrace.kind: str`, no frontend enum to extend). Also correct
`components/landing/HowItWorks.tsx:36`'s marketing copy once this is real,
not before.

---

## 5. What this plan deliberately does not do

- **Does not touch the deployed Lambda/Step Functions path without a
  separate deploy decision.** Same rule as the shadow-hold feature built
  earlier this session: this is real, correct code, ready to run locally via
  `verify-local`, but the real AWS Lambda handlers only pick it up once
  someone runs `sam build && sam deploy` — not attempted here without an
  explicit go-ahead, for the same "real deployment to live infrastructure"
  reason as before.
- **Does not give the agent write tools** (`create_database`, `create_table`,
  `insert_rows`) in Phase B. Read-only is sufficient for "investigate what
  happened" and matches the product's "never touch anything except the
  disposable shadow cluster, and even there stay conservative" posture.
  Revisit only if a concrete Phase C use needs it.
- **Does not replace `snapshot_schema_jobs()`.** It's real, correct, cheap,
  and already working — Phase B adds to it, it doesn't touch it.
- **Does not promise the auth mechanism works as described** until Phase A's
  spike confirms it against a real cluster — flagged, not assumed.

---

## 6. The prompt

Written to the same house standard as `prediction_v3.txt` and
`surprise_lessons_v1.txt` — same blast-radius vocabulary constraint, same
JSON-only contract, same explicit deference to deterministic data, same
UI-rendering awareness. Saved as
`backend/app/shadow/prompts/blast_radius_investigation_v1.txt` (new
directory, following the existing `app/prediction/prompts/` /
`app/grading/prompts/` convention — one prompts folder per subsystem that
owns a Bedrock call).

See that file for the full text. Summary of what it instructs the model to
do: given the migration SQL, the deterministic schema-diff/row-sample data
already captured, and live read-only MCP tools against the shadow cluster,
spend a bounded number of tool calls verifying specific, concrete claims
about what the migration actually did — not re-describing what the
deterministic diff already says — and return a short, tool-grounded verdict
plus the specific tool calls that back it up, in the same terse, honest,
UI-aware voice as every other model output in this product.
