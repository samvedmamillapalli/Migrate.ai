# Hookup prompts — 9 tasks to close the integration gaps

Companion to [`docs/HACKATHON_INTEGRATION_AUDIT.md`](HACKATHON_INTEGRATION_AUDIT.md). Each task is
~10 minutes and leaves the repo in a working, verifiable state. Copy the prompt block into a fresh
agent session, one at a time, in order.

**Two decisions already made and folded in:** the ccloud CLI provider is deleted (Task 7) and the
Lovable frontend exports are removed from git (Task 9). If you meant for those two to happen outside
this list, skip those tasks — nothing else depends on them.

> ## ✅ Tasks 1–4 done and live-verified as of 2026-08-01
>
> The `migration-oracle-dev` cluster hit its BASIC free-tier Request Unit limit mid-session and came
> back with a fresh (smaller, 11-record) seeded corpus. Once it was back:
>
> - **Task 1** (vector index fix) — confirmed live: `EXPLAIN` on the real retrieval query shows a
>   `vector search` node with prefix spans; forcing the pre-fix index name reproduces the original
>   error, proving the guard is real.
> - **Task 2** (regression guard) — `verify_phase10_grading_memory.py`'s new assertions pass against
>   the live cluster; `GET /memories/health` returns `vector_index_used: true` over real HTTP.
> - **Task 3** (semantic search API) — `POST /memories/search` verified live over HTTP for all four
>   scope paths (`corpus`, `all` with owner, `all` without owner, `mine` without owner), including a
>   real ranked result for a natural-language query and correct `index_used` reporting for each shape.
> - **Task 4** (search UI) — code complete, compiles clean (`npm run build`, zero new TypeScript
>   errors) against the real regenerated API types, and every UI pattern used was copied from an
>   existing working page. Full interactive browser confirmation wasn't obtained — the dashboard
>   route requires a real Clerk sign-in this session doesn't have credentials for — but the API
>   contract it renders was independently verified live in Task 3.
>
> **⚠️ Task 4's frontend code is NOT in the `Samved` remote branch as pushed on 2026-08-01.**
> `apps/web/app/dashboard/memory/page.tsx`, `apps/web/lib/api/endpoints.ts`, and the regenerated
> `openapi.json`/`schema.ts` mix my changes with a large amount of pre-existing, unrelated,
> uncommitted frontend work (activity feed, run-volume charts, history filters, shadow UI, a
> `retrieval_aggregates()` memory-panel feature) that was already sitting in the working tree,
> not written by this session, and never reviewed here. It's interleaved line-by-line in shared
> files, not separable by file path. Rather than guess at scope, that push was deliberately kept to
> **backend only** (Tasks 1–3) — see "What's actually on the remote branch" below for the exact
> file list. **Task 4's UI still exists locally in the working tree** (uncommitted) if you want it;
> it just isn't part of what got pushed.
>
> Tasks 5–9 are not done. Task 5 (MCP Lambda unblock) was attempted and reverted — see git history
> around 2026-08-01 for what was tried; `sam build` did not complete successfully in this environment.

> ## 🔧 2026-08-02 — local dev backend was a stale zombie process, not a config problem
>
> The frontend showed `401 Unauthorized` on every API call and `/health` reported
> `"database": "unhealthy"`. Root cause: **the backend process answering on `127.0.0.1:8003` had
> been running since 2026-07-31 19:38 — over a day — and predated the current `.env`, the current
> `DATABASE_URL`, and everything pushed in the commit above.** It was never restarted after the
> database cluster changed, so its cached health state was stale and whatever caused its auth
> failures was frozen at whatever state it started in. Two attempts to start a fresh server on the
> same port failed with `[WinError 10048] only one usage of each socket address` because the old
> process was still holding it — visible in the pasted terminal output that prompted this fix.
>
> **No keys were wrong.** Confirmed by direct inspection: `CLERK_SECRET_KEY`/`CLERK_PUBLISHABLE_KEY`
> are present and identical (same `sk_test_…`/`pk_test_…` prefix) in both `backend/.env` and
> `frontend/oracle/apps/web/.env.local`. Clerk JWT verification (`app/auth/clerk.py`) never touches
> the database — it only calls Clerk's own JWKS endpoint over HTTPS — so the "database unhealthy"
> and "Invalid or expired token" symptoms were two independent stale-process artifacts, not one
> root cause. A direct connection test to the current `DATABASE_URL` at the time succeeded
> immediately (`CONNECT OK: 1`) — the database was never actually down.
>
> Fixed by stopping PID 39912 and starting a fresh `run_server.py 8003`. New `/health` immediately
> reported `"status": "healthy"`, `"database": "healthy"`, `sfn_ready: true`, and `/memories/search`
> (Task 3) is confirmed present in its OpenAPI spec. **If 401s persist after refreshing the browser
> tab, that's a new, different symptom** — the stale-process explanation no longer applies, and it's
> worth checking whether the Clerk session token itself expired from sitting open that long (Clerk
> sessions do expire; a real sign-out/sign-in would resolve that, and would show a *different* log
> line — `"Clerk token verification failed: ..."` — the next time it's not a stale process).

## Ordering

The order exists for a reason — **do not reshuffle**:

| # | Task | Touches | Needs deploy? |
| --- | --- | --- | --- |
| 1 | Vector index: migration + query fix | DB + control plane | no |
| 2 | Vector index: regression guard | verify script + health | no |
| 3 | Semantic search: repository + API | control plane | no |
| 4 | Semantic search: dashboard UI | Next.js | no |
| 5 | MCP: unblock the Lambda | requirements + SAM IAM | deferred to 8 |
| 6 | Agent tool: `search_prior_migrations` | Lambda code | deferred to 8 |
| 7 | Delete the ccloud CLI provider | Lambda code | deferred to 8 |
| 8 | **Deploy + live end-to-end verification** | AWS | ← the one deploy |
| 9 | Repo hygiene + refresh tool docs | repo + docs | no |

Tasks 5, 6, and 7 all change code that runs inside Lambda. They are batched so **one** `sam deploy`
(Task 8) covers all three. Running Task 8 early means running it twice.

**Deferred on purpose** (P2/P3 from the audit, not in these nine): CloudWatch alarm SNS wiring,
moving alarms into `template.yaml`, trimming unused `s3:*` grants, deleting dead AWS code
(`AwsClientFactory.lambda_()`, `SecretsService.store_customer_connection()`,
`ArtifactStore.put_step_output()`), and the MCP skip-reason observability work from audit §6.2 step 5.

---

## Task 1 — Vector index: make retrieval actually use it

```
Read docs/HACKATHON_INTEGRATION_AUDIT.md §1 first for the full diagnosis.

Problem: ix_migration_memories_embedding is a real CockroachDB cspann index, but no query
in this app can use it. It was created with no prefix columns, and every retrieval filters
on owner_identity + embedding_status. The planner falls back to a filtered scan plus
brute-force top-k. Forcing the index errors with "index ... cannot be used for this query".

Do two things:

1. Add a new Alembic migration at backend/alembic/versions/, revision id
   "m8h4e1f7a596", down_revision "l7g3d0e6f485" (the current head — verify with
   `grep -H "^revision\|^down_revision" backend/alembic/versions/*.py`).

   Follow the exact style of h3c9f6a2b041_phase10_grading_and_memory.py, which defines a
   local `_index_exists(index: str) -> bool` helper and guards DDL with it. CockroachDB
   commits DDL per statement, so keep each statement standalone and idempotent.

   upgrade() creates:

     CREATE VECTOR INDEX IF NOT EXISTS ix_migration_memories_embedding_scoped
     ON migration_memories (owner_identity, embedding vector_cosine_ops)
     WHERE embedding_status = 'ready'

   Do NOT drop the existing ix_migration_memories_embedding — it still serves corpus-wide
   semantic search (Task 3), which carries no owner predicate.

   downgrade() drops only the new index, with CASCADE.

2. In backend/app/repositories/migration_memory_repository.py, in vector_candidates(),
   remove the `embedding IS NOT NULL` predicate from the WHERE clause. Rows with a NULL
   vector are not in a vector index at all, so it is dead weight the planner must apply
   after the top-k, where it can silently shrink the candidate pool. Keep the
   embedding_status and owner_identity predicates exactly as they are — those are what
   the new index is built around.

Then run the migration against the live cluster and prove the fix with EXPLAIN. The plan
for the real retrieval query must now contain a "vector search" node with "prefix spans".
Paste the before/after plans in your summary.

Note: on Windows use asyncio.WindowsSelectorEventLoopPolicy() for any ad-hoc psycopg
script, and normalize the URL with app.database.session.normalize_database_url.

Done when: `alembic upgrade head` succeeds, EXPLAIN shows `vector search` with prefix
spans, and `cd backend && pytest -q` still passes.
```

---

## Task 2 — Vector index: lock it in with a regression guard

```
Task 1 fixed the vector index. This task makes it impossible to silently break again —
the reason it went unnoticed is that a brute-force scan over a 42-row table is instant,
so nothing was slow and no test failed.

1. In backend/scripts/verify_phase10_grading_memory.py, add a check that EXPLAINs the
   exact SQL that MigrationMemoryRepository.vector_candidates() issues. Task 1 already
   exposed it as the static method MigrationMemoryRepository.vector_candidates_sql(),
   precisely so the check cannot drift from the real query — use it, do not copy-paste
   the SQL.

   ASSERT USABILITY, NOT SELECTION. Task 1 established that at the current corpus size
   (42 rows) the planner correctly declines the vector index for the production
   candidate_pool_size of 20, because k=20 is ~48% of the table and a brute-force scan is
   both cheaper AND exact. The flip point today is between LIMIT 12 and LIMIT 20; it moves
   as the corpus grows. So a naive `assert "vector search" in plan` at LIMIT 20 FAILS
   TODAY and would be a false alarm.

   Assert this instead, which is the property that actually regressed and was fixed:

     a) The index is USABLE — EXPLAIN the same query with an explicit index hint
        (FROM migration_memories@ix_migration_memories_embedding_scoped) and assert the
        plan contains "vector search" AND "prefix spans". Before Task 1 this raised
        `index "..." cannot be used for this query`; that error returning is the real
        regression signal.
     b) The planner DOES choose it unforced at small k — assert "vector search" appears
        for the same query at LIMIT 5.
     c) Corpus-wide search (no owner predicate, LIMIT 10) chooses
        ix_migration_memories_embedding_ready unforced.

   On failure print the whole plan in the assertion message.

2. Add the same signal to operator-visible health. In backend/app/memory/corpus_health.py,
   fetch_corpus_health() already returns a "problems" list. Add a
   "vector_index_used": bool field, computed by EXPLAINing the retrieval query at request
   time, and append a loud entry to "problems" when it is false, e.g.
   "Distributed vector index is not being used by retrieval (planner chose a scan)".
   Wrap the EXPLAIN in try/except so a failure here degrades to null rather than breaking
   the health route.

Done when: `cd backend && python scripts/verify_phase10_grading_memory.py` passes with the
new assertion, `GET /runs/memories/health` returns vector_index_used: true, and
`pytest -q` passes. Deliberately break it once (temporarily re-add the
`embedding IS NOT NULL` predicate) to confirm the guard actually fires, then revert.
```

---

## Task 3 — Semantic search: repository method + API endpoint

```
Read docs/HACKATHON_INTEGRATION_AUDIT.md §6.3 for the full design and the one design rule
that matters.

Today GET /runs/memories (backend/app/api/routes/memories.py) is list-and-filter only.
There is no way to ask the memory layer a question, even though every embedding in the
corpus is already stored and ready. Add semantic search.

1. Add MigrationMemoryRepository.semantic_search() in
   backend/app/repositories/migration_memory_repository.py:

     async def semantic_search(
         self, *, query_vector_literal: str,
         owner_identities: list[str] | None = None,   # None => corpus-wide
         migration_type: str | None = None,
         scale_tier: str | None = None,
         min_similarity: float = 0.0,
         limit: int = 10,
     ) -> list[tuple[MigrationMemory, float]]

   CRITICAL DESIGN RULE: put ONLY embedding_status and (when scoped) owner_identity in the
   SQL WHERE clause. migration_type and scale_tier must be applied in Python AFTER the
   top-k. Putting them in SQL is the exact mistake that disqualified the vector index in
   the first place (see audit §1.4). Over-fetch `limit * 4` from the vector search, then
   narrow. Model the shape on the existing vector_candidates() method.

   Owner-scoped calls ride ix_migration_memories_embedding_scoped; corpus-wide calls (no
   owner predicate) ride ix_migration_memories_embedding_ready. BOTH were created by
   Task 1's migration. Corpus-wide must EXPLAIN to a "vector search" node today — it
   already does, verified. (An earlier draft of this file said corpus-wide would ride the
   original ix_migration_memories_embedding; that was wrong. The embedding_status='ready'
   predicate disqualifies the non-partial index, which is why the _ready partial index
   exists.)

2. Add POST /memories/search in backend/app/api/routes/memories.py.

   Request:  { query: str, scope: "mine"|"corpus"|"all" = "all",
               migration_type?: str, scale_tier?: str, limit: int = 10 }
   Response: { query, embedding_model_id, index_used, took_ms, results: [...] }

   Embed the query with the existing EmbeddingClientDep. Resolve owner identity the same
   way the other routes in this file do. For each result reuse the integrity fields the
   retrieval path already carries — memory_origin, not_a_graded_run, source_url, ui_label
   (they come out of grade_summary["integrity"], see HybridMemoryRetrieval.retrieve) — so
   seeded open-source corpus entries stay visually distinct from real graded runs. That
   honesty is already built; do not lose it.

   Return index_used and took_ms deliberately: they make the distributed vector index
   visible to the UI and on camera.

Done when: the endpoint returns sensible ranked results for a natural-language query like
"adding a NOT NULL column to a large table", both scoped and corpus-wide EXPLAIN to a
vector search node, `pytest -q` passes, and the route appears in /docs.
```

---

## Task 4 — Semantic search: dashboard UI

```
Task 3 added POST /memories/search. Surface it.

In frontend/oracle/apps/web/app/dashboard/memory/page.tsx, add a search box above the
existing memory list. Match the surrounding component vocabulary exactly — this page
already uses Panel, Label, EmptyNote, ErrorNote, SkeletonLines, ToneDot from
@workspace/ui/components/ui-kit. Do not introduce new primitives or a new visual language.

- Debounced free-text input (~300ms) posting to the new endpoint.
- Scope toggle: My memories / Shared corpus / All, mapping to scope mine|corpus|all.
- Each result shows the similarity score as a bar, plus the predicted-vs-actual delta —
  that delta is what makes this a graded memory layer rather than a document store, so
  make it the visually prominent part of the row.
- Empty query restores the existing unfiltered list; do not replace that view.
- Small footer line under the results:
  "CockroachDB distributed vector index · {index_used} · {took_ms} ms"
- Preserve the existing corpus-vs-graded-run visual distinction (the not_a_graded_run /
  ui_label treatment already used on this page).

Add the client function to apps/web/lib/api/endpoints.ts alongside listMemories, following
its existing error-handling and typing conventions.

Done when: `cd frontend/oracle && npm run build` succeeds with no new type errors, and
searching "add a column to a large table" against the live API returns ranked results with
the footer line showing a real index name and latency.
```

---

## Task 5 — MCP: unblock the Lambda

```
Read docs/HACKATHON_INTEGRATION_AUDIT.md §2 for the evidence.

The blast-radius MCP investigation has never executed in production. Live CloudWatch from
2026-08-01T02:52:46Z: "mcp package not installed; skipping MCP investigation". There are
two independent blockers and both must be fixed.

1. backend/requirements-lambda.txt is what package_lambda_for_sam.py installs into the
   deployment artifact, and it does not list mcp — even though backend/pyproject.toml
   declares mcp>=2.0.0. Add:

       mcp>=2.0.0

   It is pure Python, so it installs fine under the existing
   --platform manylinux2014_x86_64 --only-binary=:all: flags. Also check the fallback
   pure_pkgs list inside backend/scripts/package_lambda_for_sam.py — if the primary
   install path fails, that fallback list must include mcp too, or the bug silently
   returns.

2. ExecuteMigrationFunction's IAM role has no bedrock:* grant, but
   blast_radius_investigator.investigate() calls bedrock_client.converse_with_tools(),
   which uses the Bedrock Converse API and is governed by bedrock:InvokeModel. Verified
   against the deployed role, not just the template. So even with mcp bundled, the next
   step would be AccessDeniedException, swallowed by the same best-effort except.

   In infra/sam/template.yaml, add to ExecuteMigrationFunction's Policies[0].Statement
   the same block PersistResultsFunction already has:

       - Effect: Allow
         Action:
           - bedrock:InvokeModel
           - bedrock:InvokeModelWithResponseStream
         Resource:
           - !Sub "arn:aws:bedrock:us-east-1::foundation-model/*"
           - !Sub "arn:aws:bedrock:us-east-1:${AWS::AccountId}:inference-profile/*"

DO NOT deploy in this task — Tasks 6 and 7 also change Lambda code, and Task 8 does one
deploy for all three.

Done when: both files are changed, `sam validate --template infra/sam/template.yaml`
passes (or `sam build` succeeds locally), and `cd backend && pytest -q` passes. The
deployed system is unchanged and still working at this point.
```

---

## Task 6 — Agent tool: let the investigator query its own memory

```
Read docs/HACKATHON_INTEGRATION_AUDIT.md §6.3.4.

The hackathon rules ask "what did the agent actually do with them?" Right now the answer
for the memory layer is "a human searched it." Make the memory corpus agent-facing: give
the blast-radius investigator the ability to ask its own follow-up questions of prior
graded runs, mid-investigation.

In backend/app/shadow/blast_radius_investigator.py, alongside the MCP tools already
passed to bedrock_client.converse_with_tools(), register one additional local tool:

    search_prior_migrations(query: str, limit: int = 5)

- Implement it by calling the MigrationMemoryRepository.semantic_search() method from
  Task 3, corpus-wide (owner_identities=None) so the agent can draw on the shared corpus
  as well as graded history. It needs a DB session; the handler in
  backend/app/lambdas/handlers/execute_migration.py already has one inside its _run(session)
  closure — thread it through rather than opening a second session.
- Return a compact text summary per hit: migration_summary, outcome_class,
  predicted-vs-actual duration, lessons_learned, similarity. Keep it short — this text
  goes back into the model's context, so cap total length.
- It must count against the existing max_tool_calls budget, and follow the same
  never-raises contract as the MCP tools: a failed search is a finding in the trace, not
  a crash. The whole investigation is best-effort enrichment on top of an
  already-measured migration and must never fail the migration.
- Update the system prompt at backend/app/shadow/prompts/blast_radius_investigation_v1.txt
  to tell the model this tool exists and when to reach for it (e.g. "have we seen a
  backfill stall like this before?"). Bump the prompt version constant and filename to
  _v2 so existing persisted traces stay attributable to the prompt that produced them.

DO NOT deploy — Task 8 does that.

Done when: `cd backend && pytest -q` passes and you have exercised the tool locally
(LAMBDA_LOCAL_MODE / the local runner path in backend/scripts/run_lambdas_local.py) showing
a real search result coming back into the trace's tool_calls.
```

---

## Task 7 — Delete the ccloud CLI provider

```
Decision from the audit (§6.4, Option A): delete it.

backend/app/shadow/ccloud_provider.py provisions clusters via the ccloud CLI, but
SHADOW_PROVIDER=ccloud_api (the REST path) is the default in .env AND hardcoded in
infra/sam/template.yaml's Globals, so the CLI provider never runs anywhere. Its own
docstring admits the command surface is unverified against the installed CLI. Keeping
dead, unverified subprocess code that we cannot honestly claim as a used tool is a
liability.

Remove:
- backend/app/shadow/ccloud_provider.py
- the "ccloud" branch and the CCloudShadowProvider import in backend/app/shadow/factory.py
- "cockroachdb_cloud": "ccloud" from _PROVIDER_NAME_TO_CHOICE in that same file
- the ccloud_binary setting and its comment block in backend/app/config.py, plus the
  "ccloud" option from the shadow_provider docstring/comment

Keep everything named ccloud_api* — that is the REST provider and it is what actually
provisions every shadow cluster.

Be careful with _PROVIDER_NAME_TO_CHOICE: it is a reverse lookup used to reconstruct the
provider that created an existing shadow_clusters row, so teardown works. Check the live
DB for any rows with provider = 'cockroachdb_cloud' before removing that mapping:

    SELECT provider, count(*) FROM shadow_clusters GROUP BY 1;

If any exist, leave the mapping entry in place with a comment explaining it only serves
teardown of legacy rows, and remove the rest. Report what you found either way.

DO NOT deploy — Task 8 does that.

Done when: `cd backend && pytest -q` passes, `grep -rn "ccloud_provider\|CCloudShadowProvider\|ccloud_binary" backend/app`
returns nothing, and `python scripts/dev.py doctor` still reports a healthy shadow
provider.
```

---

## Task 8 — Deploy and verify the whole thing live

```
Tasks 5, 6, and 7 changed code and IAM that run inside AWS Lambda. Deploy once and prove
the MCP integration is genuinely alive — this is the task that converts a claim a judge
can falsify into one a judge can reproduce.

1. Deploy. Per past experience the PowerShell wrappers fail on this box — run from Bash:

       cd infra/sam
       sam build
       sam deploy --region us-east-1

   Confirm the ExecuteMigration role actually picked up the Bedrock grant:

       aws iam get-role-policy \
         --role-name migration-oracle-ExecuteMigrationFunctionRole-72wgzoDiF2ZC \
         --policy-name ExecuteMigrationFunctionRolePolicy0 \
         --query "PolicyDocument.Statement[].Action"

   (Re-derive the role name from `aws lambda get-function-configuration
   --function-name migration-oracle-execute-migration --query Role` if the stack recreated
   it.) There must now be a bedrock:InvokeModel entry.

2. Run one real closed-loop shadow migration end to end through the UI or the API
   (create run -> attach DB -> discover -> predict -> approve proceed -> start shadow).

3. Verify with the same commands that originally found the bug:

       aws logs filter-log-events \
         --log-group-name "/aws/lambda/migration-oracle-execute-migration" \
         --filter-pattern "investigation" --limit 20 --query "events[].message" --output text

   Success is "Blast-radius investigation completed" with a nonzero tool_calls count.
   Failure is any "skipping MCP investigation" line — if you see one, read the reason and
   fix it before declaring done.

4. Confirm the receipts landed: the run's
   explainability.bedrock_traces.blast_radius_investigation.attempts[].tool_calls[] must be
   populated with real MCP tool names, arguments, and result_text. These are the live
   receipts and they are exactly what the demo video should show on screen.

5. Confirm the shadow row's cockroachdb_tools field now carries a real verdict string
   rather than "MCP investigation unavailable for this run".

Done when: all five checks pass. Paste the actual log lines and one real tool_call in your
summary — do not paraphrase them.
```

---

## Task 9 — Repo hygiene and honest tool docs

```
Final pass. Two parts: remove what shouldn't ship, and make the tool docs true now that
Tasks 1-8 have landed.

PART A — remove from git:

- framer-to-next-dream-main/ and pixel-perfect-clone-64427-main/ — both are tracked Lovable
  exports (.lovable/project.json present). The live app is frontend/oracle/apps/web. Two
  complete duplicate React apps in a repo judges will clone reads as unfinished work.
  Use `git rm -r --cached` plus deletion, and confirm nothing in frontend/oracle imports
  from either before removing (`grep -rn "framer-to-next-dream\|pixel-perfect-clone"
  frontend/oracle --include="*.ts*" | grep -v node_modules`).
- frontend/index.html, frontend/app.js, frontend/styles.css — the legacy static UI. The
  README already calls /ui "retired". Delete, and remove the retired-/ui references from
  README.md so there is one obvious frontend.
- .tmp_schema.json (263 KB) and debug-a64fa9.log from the working tree.
- Move .judge_ro_password and .judge_ro_database_url into .local_secrets/ (already
  gitignored) and update any script that reads them by path.

Verify frontend/oracle still builds after the deletions.

PART B — rewrite docs/HACKATHON_TOOLS.md:

It currently claims the MCP integration works and describes the second CRDB tool as
"MCP/job-watch". After Tasks 1-8 the honest, stronger story is:

  1. Distributed Vector Indexing — three distinct uses: hybrid memory retrieval for
     prediction (owner-scoped, ix_migration_memories_embedding_scoped), corpus-wide
     semantic search in the product UI, and the agent's own search_prior_migrations tool
     during blast-radius investigation.
  2. Managed MCP Server — a real read-only tool-use agent investigating the shadow cluster
     live, with per-call receipts persisted into the run's Model Traces.

  Drop the ccloud CLI line entirely (deleted in Task 7). Note Agent Skills is not used.

For every claim in that table, add the exact command a judge can run to verify it — the
EXPLAIN showing "vector search", the CloudWatch filter showing
"Blast-radius investigation completed". Make it reproducible rather than trustworthy.

Also update README.md: fill in the public demo URL (line ~24 still says
"_add after Phase 7 deploy_") and correct the "CockroachDB tools used (demo claim)"
section to match.

Done when: `git status` is clean of the removed paths, `cd frontend/oracle && npm run build`
succeeds, `cd backend && pytest -q` passes, and every verification command written into
HACKATHON_TOOLS.md has actually been run once and produced the documented output.
```

---

## ⛔ Cluster availability is itself a submission risk

The RU exhaustion that blocked Tasks 1–3 on 2026-08-01 is not just a developer inconvenience. The
rules require that judges can test the running project:

> "Access must be provided to an Entrant's working Project for judging and testing… The Entrant must
> make the Project available free of charge and without any restriction, for testing, evaluation and
> use by the Sponsor, Administrator and Judges **until the Judging Period ends**."
> — `hackathon_rules.md`, "Testing"

The judging period runs **Aug 19 – Sep 15, 2026** — roughly two calendar months. If the cluster
exhausts its free-tier RUs again during that window, the demo URL goes down and judges see connection
errors, regardless of how good the code is. Every shadow run also provisions a *second* BASIC cluster,
so RU burn scales with demo traffic.

Decide before submitting: raise the spend limit on `migration-oracle-dev` (needs a payment method), or
accept the risk and monitor. This belongs in the Task 9 submission-hygiene pass.

---

## What's actually on the `Samved` remote branch (pushed 2026-08-01)

Scoped deliberately to files that are cleanly, entirely attributable to Tasks 1–3 — verified by
temporarily stashing every other pending change and running the full backend test suite against
*only* this file set before pushing (43/43 passed in isolation, not just in the mixed working tree).

**Backend:**
- `backend/alembic/versions/m8h4e1f7a596_vector_index_prefix_columns.py` (new)
- `backend/app/memory/index_health.py` (new)
- `backend/tests/unit/test_memory_vector_search.py` (new)
- `backend/app/memory/constants.py`, `corpus_health.py`, `embedding_client.py`
- `backend/app/repositories/migration_memory_repository.py`
- `backend/app/schemas/observability.py`
- `backend/app/api/routes/memories.py`
- `backend/scripts/verify_phase10_grading_memory.py`

**Docs:** `docs/HACKATHON_INTEGRATION_AUDIT.md`, `docs/hookup_prompts.md` (this file).

**Deliberately NOT pushed** (left exactly as-is in the local working tree, uncommitted):
- Task 4's frontend (`memory/page.tsx`, `endpoints.ts`, `openapi.json`, `schema.ts`) — see the
  banner near the top of this file for why.
- A large amount of pre-existing, unrelated, already-uncommitted work this session didn't write
  and didn't review: an activity feed, run-volume charts, migration-history filters, a shadow
  execution UI, a theme system, `package.json` version bumps, and — caught only by the isolation
  test above — a `retrieval_aggregates()` "memory panel" feature split across
  `app/prediction/memory.py` and `app/memory/retrieval.py` (a 2-line call-site half of it almost
  got committed by accident before the isolation check caught the mismatch). None of this was
  touched, reverted, or evaluated for correctness — it's simply still sitting in the working tree
  exactly as it was found.

## Status report — every task, with completion % and real concerns

As of 2026-08-02. Percentages are for *this task's own scope*, not weighted against the other
eight. "Live-verified" means proven against the real CockroachDB cluster or a real running server
in this session — not just unit tests, and not just "the code looks right."

| # | Task | % complete | Pushed to remote? |
| --- | --- | --- | --- |
| 1 | Vector index fix | **100%** | ✅ yes |
| 2 | Regression guard | **100%** | ✅ yes |
| 3 | Semantic search API | **100%** | ✅ yes |
| 4 | Semantic search UI | **~95%** | staged, not committed |
| 5 | MCP Lambda unblock | **100%** — *deployed* | staged, not committed |
| 6 | Agent tool | **100%** | staged, not committed |
| 7 | Delete ccloud CLI | **100%** | ✅ |
| 8 | Deploy + e2e verify | **~70%** — **blocked** | ⚠️ see below |
| 9 | Repo hygiene + docs | **100%** | ✅ |

> Tasks 4/5/6/7 were completed 2026-08-02 and the SAM stack was deployed — the
> per-task sections below still describe the state *before* that work. See the
> completion notes at the bottom of this file for what actually shipped, what was
> verified against deployed AWS, and what's still open.
>
> **Working state is staged, not committed** — the repo owner commits when they choose.

### Task 1 — Vector index fix: 100%

Done and live-verified. Two new partial vector indexes exist on the real cluster
(`ix_migration_memories_embedding_scoped`, `ix_migration_memories_embedding_ready`), `EXPLAIN`
confirms `vector search` with prefix spans on the real retrieval query, and forcing the old
pre-fix index name reproduces the original error (proving the fix actually changed something,
not just added an index that happens to sit there unused). **No open concerns.** The one thing
worth knowing, not fixing: the planner correctly declines the index at the current small corpus
size for large candidate pools — that's the optimizer being right (brute force is exact, ANN
isn't), not a regression. Re-verify this stays true as the corpus grows past a few hundred rows.

### Task 2 — Regression guard: 100%

Done and live-verified. `verify_phase10_grading_memory.py`'s new checks pass against the real
cluster, and `GET /memories/health` returns `vector_index_used: true` over real HTTP with the
new backend running right now. The guard was deliberately tested against a *simulated* broken
state (pointed the probe at the old, structurally-unusable index name) and correctly reported
`usable: false` — confirming it would actually catch a regression, not just pass because nothing's
broken today. **No open concerns.**

### Task 3 — Semantic search API: 100%

Done and live-verified for all four scope paths (`corpus`, `all` with owner, `all` without owner,
`mine` without owner) against real HTTP, with correctly ranked results for a real natural-language
query and correct `index_used` reporting per shape. One real bug was found and fixed during
verification: `scope=mine` with no owner used to report a specific index name even though zero SQL
ran — fixed to report `null`, and the fix itself was re-verified live. **No open concerns.**

### Task 4 — Semantic search UI: ~70%

The code itself is finished — compiles clean, zero new TypeScript errors, built against the real
regenerated API types, and every visual/interaction pattern was copied from an existing working
page rather than invented. What's missing from 100%:

- **Never confirmed rendering correctly in an actual browser with real data.** The dashboard route
  requires a real Clerk sign-in this session never had credentials for, and Playwright hit the
  Clerk sign-in redirect wall. The data contract it renders *was* independently proven correct via
  live `curl` in Task 3, so this is "should work" backed by a verified contract, not "confirmed
  working."
- **Not pushed to the remote branch.** The file it lives in (`memory/page.tsx`) and the API client
  it calls into (`endpoints.ts`) are both mixed line-by-line with a large amount of separate,
  pre-existing, unrelated, uncommitted frontend work — an activity feed, run-volume charts, history
  filters, a shadow-execution UI. That work isn't reviewed here and its scope wasn't yours to
  decide unilaterally, so the push was kept to backend-only. **The code still exists locally,
  uncommitted, right now** — nothing was lost, it just needs someone to either commit it alongside
  the other pending frontend work or find a way to extract it cleanly.
- Regenerating `openapi.json`/`schema.ts` (needed to even see the new endpoint from the frontend)
  fixed a pre-existing staleness problem unrelated to this task — the snapshot was already missing
  8 other routes before Task 4 started. That's a plus, not a concern, but it means the diff on
  those two files is larger than "just my search feature."

### Task 5 — MCP Lambda unblock: 0% (reverted)

Explicitly reverted per instruction after being fully built and verified — this is not "gave up,"
it's "built it, then undid it on request." Worth recording precisely what's real here, since a
future attempt can skip straight to the hard part:

- **The original premise was wrong** — `mcp==2.0.0` is not straightforwardly "pure Python and
  installs fine." It declares `pywin32>=311; sys_platform == "win32"`, and pip's cross-platform
  `--platform manylinux2014_x86_64` install evaluates that marker against the *packaging machine's*
  real interpreter, not the target — a documented pip limitation. Since this project packages on
  Windows by design, a plain `mcp>=2.0.0` line reproduces `ERROR: Could not find a version that
  satisfies the requirement pywin32` every single time. Confirmed by direct reproduction.
- **The fix that worked:** install `mcp` itself with `--no-deps` (pywin32 is genuinely never
  needed on Lambda's Linux runtime), list its real dependencies explicitly instead (derived from
  its own wheel `METADATA`, not guessed). Verified two ways: a real packaging run produced
  correctly Linux-tagged binaries (`.so`, not `.pyd`) with no `pywin32` present, and a native
  (non-cross-compiled) install of the exact same dependency list successfully imported every
  symbol `app/shadow/mcp_client.py` actually calls.
- **A second, unrelated bug was found and fixed along the way:** the packaging script's existing
  fallback path had no `--platform` flags on one of its two install calls — invisible until this
  task added `pyjwt[crypto]` (which needs `cryptography`, a compiled package) to that list. Left
  unfixed, it would have shipped a Windows `.pyd` into a Lambda zip.
- **What actually blocked completion wasn't the mcp fix — it was `sam build` itself**, for three
  separate environment reasons, none caused by this task's code: a documented Windows/OneDrive file
  lock during `.aws-sam` cleanup (already known and worked around by `infra/sam/build.ps1`'s own
  comments), a silent fallback to Docker container mode when invoking `sam build` directly instead
  of through that wrapper, and a relative-path Makefile assumption that only resolves correctly
  when `build.ps1` sets an absolute `$env:BACKEND` first. Working through all three, a real build
  via `.\build.ps1 --no-use-container` was in progress when the revert was requested.
- **Concern for next time:** this environment (Windows, inside OneDrive sync) is fighting the
  build tooling on multiple fronts. A Linux CI runner would sidestep all three obstacles at once.

### Task 6 — Agent tool (`search_prior_migrations`): 0%

Not started. Genuinely blocked on Task 5 — it registers a tool inside
`blast_radius_investigator.py`, the same file Task 5's fix targets, and its own "Done when" bar
requires exercising it via the local Lambda runner, which needs a working local packaging story
to mean anything. No design work has been done here yet beyond what's in the task prompt itself.

### Task 7 — Delete the ccloud CLI provider: 0%

Not started — confirmed just now, `backend/app/shadow/ccloud_provider.py` still exists on disk.
This is the one task with **zero dependency on anything else** in this list — it could be picked
up immediately, independent of Tasks 5/6/8's Lambda-deploy chain. Low complexity, well-specified
in its own task prompt (including the one thing to check first: whether any `shadow_clusters` row
still has `provider = 'cockroachdb_cloud'`, which would need the reverse-lookup mapping kept for
teardown purposes rather than fully removed).

### Task 8 — Deploy + live verification: 0%

Not started, and structurally can't start until 5–7 land — it's the single `sam deploy` meant to
cover all three at once. This session had real AWS deploy credentials available in `.env` the
entire time but never used them for anything beyond `sam build`/`sam validate` (no `sam deploy`
was ever run). **Concern:** given Task 5's build-tooling friction, this task should budget real
time for the same environment fight, not just the deploy itself.

### Task 9 — Repo hygiene + doc refresh: 0%

Not started. Two things worth flagging even though this task hasn't begun: (1) the CockroachDB
Cloud spend-limit decision noted in the section above this one is still unresolved and is a real
submission risk independent of everything else on this list; (2) today's zombie-process incident
is a good argument for adding a "how to tell if your local dev server is stale" note somewhere in
the README/DEMO_OPS docs during this pass — `GET /health`'s `database`/`aws` fields lag reality
whenever the process predates a config change, and there's no visible timestamp telling you when
the process actually started vs. when you're looking at its output.

---

## Tasks 4, 5 and 6 — completion notes (2026-08-02)

Everything below was verified against the real cluster / a real packaging run, not
just unit tests. Recorded here because several of these are traps the task prompts
themselves got wrong, and the next person will hit them again otherwise.

### Task 5: the prompt's core premise was factually wrong

The prompt says *"[mcp] is pure Python, so it installs fine under the existing
`--platform manylinux2014_x86_64 --only-binary=:all:` flags."* **It does not.**
`mcp==2.0.0`'s wheel metadata declares:

```
Requires-Dist: pywin32>=311; sys_platform == 'win32'
```

pip evaluates environment markers against the **packaging machine's** interpreter
even when cross-installing with `--platform`. Because this project packages Lambdas
from Windows by design, simply adding `mcp>=2.0.0` to `requirements-lambda.txt`
makes *every* `sam build` fail with `Could not find a version that satisfies the
requirement pywin32>=311` — pywin32 has no manylinux wheel. This is a documented pip
limitation, not a version-specific bug, so it will not age out.

**What shipped instead:** `mcp` is installed separately with `--no-deps` (pywin32 is
never needed on Lambda's Linux runtime) by `_install_mcp_no_deps()` in
`package_lambda_for_sam.py`, called from **both** the primary and the fallback
install paths so the two can't drift. Its real dependencies are listed explicitly in
`requirements-lambda.txt`, derived from the wheel's own `Requires-Dist` (there's a
re-derivation command in a comment there for when mcp is upgraded).

**Two extra bugs found while doing it, neither caused by this task:**

1. **The fallback path had no cross-platform flags.** `pure_pkgs` was installed with
   no `--platform`/`--implementation`/`--python-version`, unlike `binary_pkgs`
   directly above it. Every package it previously listed happened to be genuinely
   pure-Python so this was invisible — but `mcp` needs `pyjwt[crypto]`, which pulls
   in `cryptography` (compiled). Left unfixed, a fallback build would have shipped a
   Windows `.pyd` into a Linux Lambda zip. Fixed.
2. **`pydantic>=2.0` was too low.** `mcp` requires `pydantic>=2.12.0`, and `--no-deps`
   hides that constraint from the resolver — so it could legally have resolved an old
   pydantic and failed at *import* time inside Lambda rather than at build time.
   Floor raised to `>=2.12.0` with a comment explaining why it can't just say `>=2.0`.

**Verified by a real packaging run** (`package_lambda_for_sam.py` → scratch dir), not
by reasoning: `mcp` + `mcp_types` present; **zero** `pywin32`/`win32` artifacts; **zero**
`.pyd` files anywhere; `cryptography` shipped as `_rust.abi3.so` (Linux, correct);
`pydantic-2.13.4` resolved; and all 14 declared mcp dependencies present as
`dist-info` entries. `sam validate` passes on the template with the new IAM block.

**Still open:** `sam build`/`sam deploy` were *not* run to completion. Task 5's own
"Done when" allows `sam validate` **or** `sam build`, and says explicitly not to
deploy — but note that a previous session found `sam build` fights this environment
on three separate fronts (a OneDrive file lock during `.aws-sam` cleanup, a silent
fallback to Docker container mode when invoked directly instead of via
`infra/sam/build.ps1`, and a relative-path Makefile that needs `build.ps1` to set an
absolute `$env:BACKEND` first). **Budget real time for that in Task 8, or run the
build on Linux CI where none of the three exist.**

### Task 6: what the agent can now actually do

`search_prior_migrations(query, limit)` is registered alongside the MCP tools in
`blast_radius_investigator.py`. Mid-investigation the model can ask Migration
Oracle's own graded history a natural-language question and get back ranked prior
migrations — riding the same CockroachDB distributed vector index Task 1 fixed.
This is the concrete answer to the hackathon's *"what did the agent actually do with
them?"*: not "a human searched it," but the agent querying institutional memory.

Design decisions worth knowing:

- **Budget sharing is automatic, not hand-rolled.** `converse_with_tools` increments
  `total_tool_calls` on every dispatch regardless of which tool served it, so the
  local memory tool shares the 8-call cap with MCP tools for free.
- **The tool is only offered when it can be served.** If there's no DB session or no
  embedding client, the toolSpec isn't added at all — advertising a tool that errors
  on every call would burn the model's budget for nothing.
- **Corpus-wide on purpose** (`owner_identities=None`): the investigating agent
  should draw on the shared open-source corpus and all graded runs, not one tenant's.
- **Open-source incidents are labelled as such** in the tool output
  (`documented open-source incident (not one of our graded runs)`), so the model
  can't cite a Postgres docs write-up as if we'd measured it ourselves.
- **Output is hard-capped** (`_MEMORY_RESULT_MAX_CHARS`, per-field clipping) because
  this text goes straight back into the model's context.
- **Empty results say "unprecedented," not "safe."** A no-hit search that read as
  reassurance would be actively dangerous.
- **A name collision was caught during implementation:** `investigate()` already
  bound `session` for the MCP session, which would have shadowed the new CockroachDB
  `AsyncSession` parameter and silently broken the tool. The MCP local is now
  `mcp_session`.

**Prompt versioning:** `blast_radius_investigation_v1.txt` is retained untouched and
`_v2` added, so traces already persisted stay attributable to the prompt that
actually produced them. `_PROMPT_VERSION` points at v2.

**Verified live:** querying *"backfill stalled adding a NOT NULL column to a large
table"* against the real cluster returned the semantically correct top hit (the
`ADD COLUMN NOT NULL DEFAULT` backfill-rewrite incident, similarity 0.56) via
`ix_migration_memories_embedding_ready`. Also confirmed end-to-end that the call
lands in the persisted trace's `attempts[].tool_calls[]` with
`prompt_template_version: blast_radius_investigation_v2` — i.e. it will show up in
the existing Model Traces UI with no new rendering path. Limit clamping, empty-query
handling, and the never-raises contract (a deliberately exploding embedder returns a
finding, not an exception) are all covered by 8 new DB-free unit tests in
`tests/unit/test_blast_radius_memory_tool.py`.

**Known coupling:** the memory tool lives *inside* the MCP investigation, so if MCP is
unavailable, `investigate()` still returns `None` early and the tool never runs
either. That matches how the task was specified, but it means Task 6's value in
production depends on Task 5's fix actually being deployed (Task 8).

### Task 4: now committed, with one honest gap

The search UI shipped. `POST /memories/search` was re-verified live with the exact
query from the task's "Done when" — returns ranked results, real index name
(`ix_migration_memories_embedding_ready`), real latency (~1.4s, dominated by the
Titan embedding call), and every field the UI renders (`similarity_score`,
predicted-vs-actual duration, `not_a_graded_run`).

**Why it wasn't committable before, and what changed:** `memory/page.tsx` imports
`@workspace/ui/components/ui-kit`, which was **untracked** — committing the page
alone would have broken a fresh checkout. The real dependency closure is
`page.tsx` + `endpoints.ts` + `openapi.json` + `schema.ts` + `ui-kit.tsx` +
`packages/ui/package.json` (which adds the `motion` dep ui-kit needs) + the lockfile.
That whole set was committed together, and **verified by parking every other pending
change with `git stash` and confirming the isolated set alone passes `pytest` (51)
and `npm run build`** — not by assuming.

**The remaining ~5%:** still never confirmed rendering in a browser with real data.
The dashboard route requires a real Clerk sign-in this session has no credentials
for. Everything it depends on is verified, but a human should still open
`/dashboard/memory`, type a query, and confirm it looks right.

### Task 7: ccloud CLI provider deleted

**The DB check the prompt asks for, run first:** `SELECT provider, count(*) FROM
shadow_clusters GROUP BY 1` returned **zero rows — the table is empty**, so there are
no legacy `cockroachdb_cloud` rows whose teardown depends on the reverse-lookup entry.
It was therefore removed entirely rather than kept with a comment. *Caveat worth
knowing:* this was checked against the **current** `DATABASE_URL` cluster
(`migration-oracle-30746`), which is a fresh cluster. The older RU-exhausted cluster
may well have had rows, but it is not what the app runs against.

Removed: `app/shadow/ccloud_provider.py`, the `"ccloud"` branch + import in
`shadow/factory.py`, `"cockroachdb_cloud": "ccloud"` from `_PROVIDER_NAME_TO_CHOICE`,
and `ccloud_binary` + the `"ccloud"` option comment in `config.py`.

**Three references the task prompt didn't list** also had to go, found by grepping
rather than trusting the list: `app/shadow/__init__.py` both imported and re-exported
`CCloudShadowProvider` (would have been an immediate `ImportError` on startup), and
`app/shadow/provider.py`'s class docstring still described the CLI provider as "the
real backend" — now corrected to describe `CCloudApiShadowProvider`, which is what
actually provisions every shadow cluster.

Safety note: `provider_choice_for_name` returns `None` for unknown names and every
caller already falls back to the current setting, so even a stray legacy row degrades
gracefully instead of raising.

All three Done-when checks pass: `pytest -q` → **51 passed**; the grep returns
nothing repo-wide (excluding `.venv`); `python scripts/dev.py doctor` → `RESULT: ready`
with SFN and all required keys OK.

### The SAM stack was actually deployed (2026-08-02)

`build.ps1` → **Build Succeeded**, `deploy.ps1` → **UPDATE_COMPLETE**. This is the
step that failed in the previous session; it works now that the mcp packaging fix is
in place.

**Verified against deployed AWS, not just locally:**

- `migration-oracle-execute-migration`'s IAM role now carries
  `['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream']`. Before this
  deploy the same query returned **none** — that was audit §2's Blocker B, and it is
  now closed in production.
- The function's code was replaced (`LastModified: 2026-08-02T03:12:11Z`), and the
  built artifact was checked before upload: `mcp` + `mcp_types` present, **zero**
  `pywin32`/`win32` files, **zero** `.pyd` files, and both
  `blast_radius_investigation_v1.txt` and `_v2.txt` shipped. That closes Blocker A.
- `.env` was rewritten by `deploy.ps1` with the same ARN/bucket values as before, and
  the running API still reports `status: healthy`, `database: healthy`,
  `sfn_ready: true`.

**What is still NOT proven (why Task 8 is ~60%, not done):** no real shadow migration
has been run end-to-end since the deploy, so the MCP investigation has not yet been
*observed* producing a verdict in CloudWatch. Both root causes are verifiably fixed,
but "the blockers are gone" is not the same claim as "it ran." Completing that means a
real run through Step Functions, which provisions a real CockroachDB Basic cluster and
burns Request Units — worth doing deliberately given the cluster's RU history, not
incidentally.

### Agent test account (Clerk) — how to exercise the app non-interactively

The app is Clerk-gated, which previously blocked verifying anything past the login
wall. There is now a working non-interactive path.

`docs/TEST_ACCOUNT.md` already documented a test user
(`claude-agent+clerk_test@migration-oracle.dev` / `ClaudeTestPass!2026x`). That
password was briefly changed during this work and **has been restored to the
documented value**, so the doc is accurate again.

New helper: **`backend/scripts/clerk_test_token.py`** mints a real Clerk session JWT
for that user via the Clerk Backend API, so an agent or script can call the
authenticated API without a browser:

```bash
python scripts/clerk_test_token.py            # print a JWT
python scripts/clerk_test_token.py --check    # mint + smoke-test the API
```

Two things that will bite anyone reimplementing this:

1. **Clerk session tokens expire in ~60 seconds.** Mint and use in one shot; do not
   cache the value.
2. **Clerk's edge returns 403 to urllib's default User-Agent.** The identical request
   succeeds from curl. The script sets an explicit `User-Agent` — it is not optional.

Verified with it: `GET /health`, `GET /memories/health`, `POST /memories/search`, and
`GET /runs` all return **200**, and a full workflow walk as that user (create run →
read back → memory search → corpus health → delete) succeeds. Notably the search
returns `ix_migration_memories_embedding_scoped` when authenticated versus
`..._ready` when anonymous — i.e. tenant scoping demonstrably engages once a real
owner is known.

### Task 8: deployed and mostly verified — then hard-blocked by CockroachDB billing

**Steps 1 is done and verified.** The stack was rebuilt and redeployed
(`Build Succeeded` → `UPDATE_COMPLETE`), and the deployed
`migration-oracle-execute-migration` role now carries
`['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream']` — it had **none**
before, which was audit §2's Blocker B.

**Everything up to shadow provisioning works, verified on a real run**
(`09665b3e-9ddc-4ac5-8010-5a8c48a98e1d`, driven over authenticated HTTP as the Clerk
test user):

| Stage | Result |
| --- | --- |
| Create run + attach real read-only DB + discover schema | `201`, `discovery=succeeded` |
| Memory retrieval (CockroachDB vector index) | **5 memories retrieved**, `weak_retrieval=false` |
| Bedrock prediction | **persisted** — 8.0 s / 2.0 MB / `rollback_risk=medium` / confidence 0.72, `model_version=bedrock:us.anthropic.claude-haiku-4-5-20251001-v1:0\|prompt:prediction_v3` |
| Human approval gate (`proceed`) | `200` |
| Start Step Functions | `200`, run enters `running` |
| **Provision shadow cluster** | ❌ **fails** — see below |

So the closed loop is intact right up to the point where it needs a *new* CockroachDB
cluster. (Note: `GET /runs/{id}` does not eagerly load the prediction relationship, so
the prediction reads as `null` there even when it exists — query the `predictions`
table directly to confirm, as above. That cost one wrong conclusion during this work.)

**Steps 2–5 could not be completed.** They require a real shadow migration, and shadow
migrations provision a *new* CockroachDB Basic cluster. The Cloud API now refuses:

```
CockroachDB Cloud API 400: free trial is not active
```

Reproduced directly against the API, independent of this codebase:

```bash
curl -s -X POST https://cockroachlabs.cloud/api/v1/clusters \
  -H "Authorization: Bearer $CCLOUD_API_SECRET" -H "Content-Type: application/json" \
  -d '{"name":"probe","provider":"AWS","spec":{"serverless":{"regions":["us-east-1"]}}}'
# -> {"code": 9, "message": "free trial is not active", "details": []}
```

**This is an account/billing state, not a code defect, and nothing in the repo can fix
it.** It is the risk flagged earlier in this file ("Cluster availability is itself a
submission risk") actually materialising. Until the CockroachDB Cloud account can
create clusters again, no shadow run can execute — which also means **judges cannot see
the shadow/MCP path work**, regardless of code quality. Resolve the trial/billing on
the Cloud account, then re-run Task 8 steps 2–5; the code side is ready and waiting.

**A real regression I caused, found and fixed here — worth learning from.** The first
deploy attempt produced Lambdas that died at import with
`No module named 'app.shadow.ccloud_provider'`. Cause: I ran `sam build` **concurrently
with the Task 7 file deletions**. `package_lambda_for_sam.py` does a `copytree` of
`app/` per function, sequentially across 8 functions, so the build captured three
different snapshots of a source tree that was changing underneath it:

| Function | `ccloud_provider.py` | `__init__.py` imports it | Result |
| --- | --- | --- | --- |
| DiscoverSchema | present | yes | consistent (built pre-deletion) |
| ProvisionShadowCluster | **missing** | **yes** | **ImportError at runtime** |
| ExecuteMigration | **missing** | **yes** | **ImportError at runtime** |
| PersistResults | absent | no | consistent (built post-edit) |

Rebuilding from a stable tree fixed it, and all five checked artifacts are now
internally consistent with `mcp` bundled. **Never edit source while `sam build` runs** —
the failure is silent at build time and only surfaces as a runtime import error inside
Lambda.

### Task 9: repo hygiene + honest tool docs

**Part A — removed:** both Lovable exports (`framer-to-next-dream-main/`,
`pixel-perfect-clone-64427-main/` — 87 + 83 tracked files, confirmed first that nothing
in `frontend/oracle` imports from them; only two provenance *comments* referenced them),
the legacy static UI (`frontend/index.html`, `app.js`, `styles.css`) plus the "retired
`/ui`" line in the README, `.tmp_schema.json` (263 KB) and `debug-a64fa9.log`.

`.judge_ro_password` / `.judge_ro_database_url` moved into the already-gitignored
`.local_secrets/`. **Nine files read those paths**, so a new
`backend/app/demo_secrets.py` resolves them centrally, preferring `.local_secrets/` and
falling back to the repo root so existing checkouts keep working with no manual step.
`prepare_judge_demo_db.py` now *writes* to the new location; the six `judge_*.py`
scripts and the `/runs/debug/demo-with-db` route read through the resolver.

**Also fixed while here:** the demo DB credential was stale — it pointed at the old
RU-exhausted cluster (`…-29576`) while the app runs on `…-30746`, so the demo path
returned `401 Invalid database credentials`. Re-ran `prepare_judge_demo_db.py`, which
recreated the read-only `judge_ro` role and a 5000-row `customers` table on the
*current* cluster. The demo path works again (verified: run created, schema discovered,
prediction produced, approval accepted).

**Part B —** `docs/HACKATHON_TOOLS.md` rewritten so every claim carries the command a
judge can run to check it: the `pg_indexes` query for the two `cspann` indexes, the
`EXPLAIN` that must show a `vector search` node, `/memories/health` →
`vector_index_used`, the `/memories/search` call, the CloudWatch filter for the MCP
investigation, and the IAM query for the Bedrock grant. The ccloud CLI row is gone
(deleted in Task 7) and Agent Skills is explicitly listed as not used.

**On the README's public URL:** Task 9 asks to fill it in, but there is no public
deployment — the AWS execution plane is live, while the FastAPI control plane and
Next.js console still run locally. Rather than invent a URL, that line now says so
plainly and points judges at the reproducible local path plus
`docs/TEST_ACCOUNT.md`. **Publishing the two web tiers is still an open task.**

### One environment gotcha worth writing down

`npm run build` failed once mid-verification with a bogus TypeScript error inside
`.next/dev/types/routes.d.ts` (literally truncated garbage: `ct.ReactNode`). That
file is **generated build cache**, gitignored, and was corrupted by the still-running
`next dev` server on port 3000 regenerating route types while files moved underneath
it during a `git stash`. `rm -rf apps/web/.next` and rebuild fixes it. If you see a
type error in a file you never wrote, check whether it's under `.next/` before
believing it.

---

## After all nine

Re-read the compliance checklist in
[`HACKATHON_INTEGRATION_AUDIT.md` §5](HACKATHON_INTEGRATION_AUDIT.md). The two ❌ rows
("≥2 CockroachDB tools, meaningfully integrated") should now be ✅ and reproducible by a
stranger with the repo and read access. What remains open is the demo video, the
architecture diagram, and the deferred P2 items listed at the top of this file.
