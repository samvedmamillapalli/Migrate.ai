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

## What's needed next, task by task

- **Task 4 (frontend UI):** the code exists locally, compiles clean, and is ready — it just needs
  someone who can review/commit the *other* pending frontend work first (or accept committing it
  alongside), since `page.tsx`/`endpoints.ts` can't be split from that work by file path. Once
  that's committed, re-run `npm run gen:api` if any backend route changed since the local
  `openapi.json` was regenerated (2026-08-01), then push.
- **Task 5 (MCP Lambda unblock):** diagnosis is solid and reusable, but the fix itself was
  reverted per instruction — see git history around 2026-08-01 for the exact `--no-deps` /
  explicit-dependency-list approach that was verified to work. What's still needed: either get
  `sam build` working in this environment (the blocker was Windows/OneDrive-specific — file
  locks during `.aws-sam` cleanup and a relative-path Makefile issue, both walkable via
  `infra/sam/build.ps1`, which was mid-run when stopped) or move the build to a Linux CI runner
  where none of those three obstacles exist.
- **Task 6 (agent tool `search_prior_migrations`):** blocked on Task 5 landing first — it wires
  into the same `blast_radius_investigator.py` that Task 5's MCP fix targets, and the prompt calls
  for exercising it via the local Lambda runner, which needs a working local packaging story to
  matter.
- **Task 7 (delete ccloud CLI provider):** independent of everything else — can be done any time,
  including before Task 5/6. Not started.
- **Task 8 (deploy + live verification):** needs Tasks 5–7 done first (it's the one deploy that
  covers all three), plus a real `sam deploy` with AWS credentials, which this session had access
  to but never used for anything beyond `sam build`/`sam validate`.
- **Task 9 (repo hygiene + doc refresh):** not started. Also carries the cluster-spend-limit
  decision noted above — worth doing regardless of where 5–8 land, since it's independent cleanup.

---

## After all nine

Re-read the compliance checklist in
[`HACKATHON_INTEGRATION_AUDIT.md` §5](HACKATHON_INTEGRATION_AUDIT.md). The two ❌ rows
("≥2 CockroachDB tools, meaningfully integrated") should now be ✅ and reproducible by a
stranger with the repo and read access. What remains open is the demo video, the
architecture diagram, and the deferred P2 items listed at the top of this file.
