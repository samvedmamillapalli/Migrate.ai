# Hackathon Integration Audit — CockroachDB tools, AWS services, redundancy, and the plan to close the gaps

**Date:** 2026-07-31
**Scope:** every CockroachDB feature and every AWS service this project claims to use, verified against
the **live** CockroachDB Cloud cluster, the **live** deployed AWS stack (`630434208625`, `us-east-1`),
and the source tree — not against the docs.
**Reference:** [`docs/hackathon_rules.md`](hackathon_rules.md)

---

## 0. Executive summary — read this first

| Claim in `README.md` / `docs/HACKATHON_TOOLS.md` | Reality | Verdict |
| --- | --- | --- |
| CockroachDB Distributed Vector Indexing is used for memory retrieval | The `cspann` vector index **exists** and is correct, but **no query in the app can use it**. Every retrieval is a filtered full scan + brute-force top-k. Forcing the index errors out. | ⚠️ **Partially integrated** |
| CockroachDB Managed MCP Server drives a blast-radius investigation | The client code is real and good, but it has **never once executed in production**. Live CloudWatch log, 2026-08-01T02:52:46Z: `"mcp package not installed; skipping MCP investigation"`. Two independent blockers. | ❌ **Not integrated** |
| ccloud CLI | `CCloudShadowProvider` exists but `SHADOW_PROVIDER=ccloud_api` (REST) is the default in `.env` *and* baked into the Lambda `Globals`. The CLI never runs. | ❌ **Not used** |
| CockroachDB Agent Skills | Referenced only inside quoted hackathon rules text. No skill files, no invocation. | ❌ **Not used** |
| AWS: Bedrock, Lambda, Step Functions, S3, Secrets Manager, CloudWatch, EventBridge | All seven genuinely deployed and load-bearing. | ✅ **Integrated** (with gaps, §3) |

### The compliance problem, stated plainly

The rules require **at least 2 CockroachDB tools, meaningfully integrated — "not just initialized
within the Project"** (`hackathon_rules.md` line 86). Today:

- **Tool 1 (Vector Indexing)** is *initialized but not exercised*. The embeddings are real, the storage
  is real, the retrieval is real — but the **distributed index itself** is decorative. A judge who runs
  `EXPLAIN` sees a full scan. That is exactly the "just initialized" failure the rules call out.
- **Tool 2 (MCP)** is *code that has never run*. A judge who greps CloudWatch finds the skip warning.

**This is a Stage One pass/fail risk.** Stage One asks whether the Project "reasonably applies the
required APIs/SDKs." Both fixes are small and are fully specified in §6 — the hard engineering is
already done; what's missing is one Alembic migration, one line in a requirements file, and one IAM
statement.

---

## 1. CockroachDB Distributed Vector Indexing — deep dive

### 1.1 What is actually built

| Layer | File | Status |
| --- | --- | --- |
| Column type | [`backend/app/database/types.py`](../backend/app/database/types.py) — `Vector(UserDefinedType)` emitting `VECTOR(n)` | ✅ correct |
| Model | [`backend/app/database/models/migration_memory.py:65`](../backend/app/database/models/migration_memory.py#L65) — `embedding: Vector(1024)`, plus `embedding_status`, `embedding_error`, `embedding_model_id` | ✅ correct |
| Index DDL | [`backend/alembic/versions/h3c9f6a2b041_phase10_grading_and_memory.py:329-336`](../backend/alembic/versions/h3c9f6a2b041_phase10_grading_and_memory.py#L329-L336) | ✅ created |
| Embeddings | [`backend/app/memory/embedding_client.py`](../backend/app/memory/embedding_client.py) — Bedrock Titan `amazon.titan-embed-text-v2:0`, `dimensions: 1024`, `normalize: true` | ✅ real |
| Write path | [`backend/app/memory/writer.py`](../backend/app/memory/writer.py) — embeds on grade, marks `pending` on failure, repairable | ✅ real |
| Read path | [`backend/app/repositories/migration_memory_repository.py:33-89`](../backend/app/repositories/migration_memory_repository.py#L33-L89) — `<=>` cosine, `similarity = 1 - distance` | ✅ correct SQL |
| Re-rank | [`backend/app/memory/retrieval.py`](../backend/app/memory/retrieval.py) — 5-factor weighted re-rank over the vector candidate pool | ✅ genuinely good |

### 1.2 Verified live cluster state

CockroachDB **CCL v26.2.1**, database `migration_oracle`.

```
ix_migration_memories_embedding
  ON migration_oracle.public.migration_memories
  USING cspann (embedding vector_cosine_ops)
```

`cspann` is CockroachDB's real distributed vector index (SPANN). The DDL is right.

Corpus state:

| Metric | Value |
| --- | --- |
| `migration_memories` rows | 42 |
| `embedding_status = 'ready'` | 42 (100% — zero pending, zero failed) |
| `__migration_oracle_corpus__` (shared corpus) | 16 |
| Real user identities (`user_3H7…`, `user_3HI…`) | 10 |
| `migration_runs` | 163 |
| `vector_search_beam_size` | 32 (default) |

The memory layer is genuinely populated with real graded runs. **This part is strong** and directly
serves the "Agentic Memory Design" judging criterion.

### 1.3 The defect: the index is never used

The query the app actually runs (`MigrationMemoryRepository.vector_candidates`) is:

```sql
SELECT id, (embedding <=> CAST(:qv AS VECTOR(1024))) AS distance
FROM migration_memories
WHERE embedding IS NOT NULL
  AND embedding_status = 'ready'
  AND owner_identity IN (:o0, :o1)
ORDER BY embedding <=> CAST(:qv AS VECTOR(1024))
LIMIT 20                              -- retrieval.candidate_pool_size
```

`EXPLAIN` against the live cluster, with real values:

```
• top-k
│ k: 40
└── • render
    └── • filter
        │ filter: (embedding IS NOT NULL) AND (embedding_status = 'ready')
        └── • index join
            │ table: migration_memories@pk_migration_memories
            └── • scan
                  table: migration_memories@ix_migration_memories_owner_identity
                  spans: [/'__migration_oracle_corpus__' …] [/'judge-demo' …]
```

**No `vector search` node.** It scans the owner b-tree, index-joins to the PK, filters, then sorts
every surviving row by distance in memory. The `cspann` index contributes nothing.

Forcing the index proves it is not merely a cost decision:

```
EXPLAIN SELECT id FROM migration_memories@ix_migration_memories_embedding
WHERE embedding_status='ready' AND owner_identity IN (…)
ORDER BY embedding <=> … LIMIT 40;

ERROR: index "ix_migration_memories_embedding" cannot be used for this query
```

For contrast, the *same table*, *same operator*, with the filters removed **does** use it:

```
└── • lookup join
    └── • vector search
          table: migration_memories@ix_migration_memories_embedding
          target count: 5
```

### 1.4 Root cause

A CockroachDB vector index is `(prefix_columns…, vector_column ops)`. Equality predicates are only
pushed into the vector search when the predicate columns are **prefix columns of that index**.
`ix_migration_memories_embedding` was created with **no prefix columns**, so any query carrying a
`WHERE` clause — and the app's tenancy scoping means *every* query carries one — is structurally
ineligible.

Today's 42-row corpus hides this: a brute-force scan over 42 rows is instant. At 10k+ memories the
retrieval latency grows linearly and the "distributed indexing… stays fast as your data grows" claim
in the rules becomes false for this project.

### 1.5 The fix — verified working on the live cluster

Probed on a throwaway table (`_vecidx_probe`, created and dropped) against the same v26.2.1 cluster.
All three DDL forms are supported:

| DDL | Result |
| --- | --- |
| `CREATE VECTOR INDEX … (owner, emb vector_cosine_ops)` | ✅ accepted |
| `CREATE VECTOR INDEX … (owner, emb vector_cosine_ops) WHERE status='ready'` | ✅ accepted (partial) |
| `CREATE VECTOR INDEX … (status, owner, emb vector_cosine_ops)` | ✅ accepted (multi-prefix) |

And the plans, for the app's exact query shape:

```
-- WHERE owner IN ('a','b') AND status='ready' ORDER BY emb <=> … LIMIT 5
└── • vector search
      table: _vecidx_probe@probe_partial (partial index)
      target count: 5
      prefix spans: [/'a' - /'a'] [/'b' - /'b']
```

**`IN (…)` works** — it becomes two prefix spans, which is precisely the owner + shared-corpus
two-scope pattern `HybridMemoryRetrieval` uses. See §6.1 for the migration.

### 1.6 Outcome after the fix (applied 2026-07-31, revision `m8h4e1f7a596`)

Two partial indexes replace the single unusable one, one per query shape the app issues:

| Index | Definition | Serves |
| --- | --- | --- |
| `ix_migration_memories_embedding_scoped` | `(owner_identity, embedding vector_cosine_ops) WHERE embedding_status='ready'` | owner-scoped hybrid retrieval |
| `ix_migration_memories_embedding_ready` | `(embedding vector_cosine_ops) WHERE embedding_status='ready'` | corpus-wide semantic search (§6.3) |

**The structural defect is fixed.** The forced plan now succeeds where it previously errored:

```
FROM migration_memories@ix_migration_memories_embedding_scoped
└── • vector search
      table: migration_memories@ix_migration_memories_embedding_scoped (partial index)
      target count: 20
      prefix spans: [/'__migration_oracle_corpus__' …] [/'judge-demo' …]
```

**Whether the planner *chooses* it is now a cost decision, and depends on k/N.** Measured on the live
42-row corpus, owner-scoped:

| `LIMIT` | Plan chosen |
| --- | --- |
| 1, 3, 5, 8, 12 | ✅ vector search |
| 20 (production `candidate_pool_size`) | scan + brute-force top-k |

At k=20 the query asks for ~48% of the table, and a brute-force scan is both cheaper **and exact**
(brute force is not approximate; ANN is). The optimizer is right, and forcing an index hint here would
make results *worse* at small scale for a cosmetic plan shape — so no hint was added. As the corpus
grows, k=20 becomes a small fraction of N and the index wins unforced. Corpus-wide search already
chooses `…_ready` unforced today.

The honest one-line claim is therefore: *retrieval runs on CockroachDB's distributed vector index, and
the planner picks it whenever the candidate pool is small relative to the corpus.* That is verifiable
and does not overstate.

The original `ix_migration_memories_embedding` was deliberately left in place by the migration — it is
now redundant (every app query filters `embedding_status`) but dropping a vector index is a heavier
call than adding two. Drop it once corpus-wide search is confirmed on `…_ready`; three `cspann`
indexes on one table is real write amplification for a table written on every graded run.

---

## 2. CockroachDB Managed MCP Server — deep dive

### 2.1 What is built (and it is good)

[`backend/app/shadow/mcp_client.py`](../backend/app/shadow/mcp_client.py) and
[`backend/app/shadow/blast_radius_investigator.py`](../backend/app/shadow/blast_radius_investigator.py)
implement a genuine Claude tool-use agent with live read-only MCP access to the shadow cluster:

- Connects to `https://cockroachlabs.cloud/mcp` over streamable HTTP with
  `Authorization: Bearer <CCLOUD_API_SECRET>` + `mcp-cluster-id: <shadow cluster id>`.
- **Read-only by construction, not convention** — `_WRITE_TOOL_NAMES = {create_database, create_table,
  insert_rows}` are filtered out of `tool_defs()` *before* the tool list reaches the model, and
  `call_tool` refuses them even if asked. This is a genuinely good safety posture and directly
  addresses the "does the agent use the tools correctly and safely?" criterion.
- Tool-call budget (`max_calls=8`), per-call receipts (`McpToolCall` with `result_text`, `is_error`)
  persisted into `explainability.bedrock_traces.blast_radius_investigation` so a verdict can be checked
  against what the tool actually returned.
- Best-effort throughout: never blocks or fails the migration it is investigating.

Invoked from [`execute_migration.py:179`](../backend/app/lambdas/handlers/execute_migration.py#L179),
after the migration has already been measured.

### 2.2 The defect: it has never executed

Live CloudWatch, `/aws/lambda/migration-oracle-execute-migration`, run
`55ae9475-77e4-4b45-9a53-44d2348ba210`, **2026-08-01T02:52:46Z**:

```json
{"level": "WARNING", "logger": "app.shadow.mcp_client",
 "message": "mcp package not installed; skipping MCP investigation",
 "lambda_function_name": "execute-migration"}
```

Filtering the whole log group for `investigation` returns **zero events, ever**. The only historical
`MCP` hit is from 2026-07-25 and is the *old hardcoded attribution string* that
[`job_watch.py`](../backend/app/shadow/job_watch.py) itself documents as removed:

```json
"cockroachdb_tools": "Distributed Vector Indexing (memory retrieval) + Managed MCP Server / SQL job watch (shadow blast-radius)"
```

That string was attribution without a call. The real client replaced it — and the real client
short-circuits.

### 2.3 Two independent blockers

**Blocker A — `mcp` is not in the Lambda bundle.**

`mcp>=2.0.0` is declared in [`backend/pyproject.toml:19`](../backend/pyproject.toml#L19) but **not** in
[`backend/requirements-lambda.txt`](../backend/requirements-lambda.txt), which is what
`package_lambda_for_sam.py` installs into the deployment artifact. `open_shadow_mcp_session` hits
`ImportError`, logs the warning, yields `None`, and `investigate()` returns `None`.

**Blocker B — `ExecuteMigrationFunction` has no Bedrock permission.**

Verified against the **deployed** role, not just the template:

```
$ aws iam get-role-policy --role-name migration-oracle-ExecuteMigrationFunctionRole-72wgzoDiF2ZC \
    --policy-name ExecuteMigrationFunctionRolePolicy0 --query "PolicyDocument.Statement[].Action"

[["s3:PutObject","s3:GetObject","s3:ListBucket"],
 ["secretsmanager:GetSecretValue","secretsmanager:DescribeSecret"],
 ["cloudwatch:PutMetricData"],
 ["logs:CreateLogGroup","logs:CreateLogStream","logs:PutLogEvents"]]
```

No `bedrock:*`. `investigate()` calls `bedrock_client.converse_with_tools()`, which uses the Bedrock
**Converse** API — governed by `bedrock:InvokeModel`. So even with `mcp` bundled, the very next step
would be `AccessDeniedException`, swallowed by the same best-effort `except` and reported as
"MCP investigation unavailable for this run."

Why this happened is visible in git: `infra/sam/template.yaml` was last touched in `7a0b981`
(2026-07-25); `blast_radius_investigator.py` arrived in `903e681` (2026-07-30). The IAM grant was
never added alongside the new Bedrock call site.

### 2.4 Secondary issue — the IDE MCP config

[`.cursor/mcp.json`](../.cursor/mcp.json) carries only `mcp-cluster-id` and no credential:

```json
{"mcpServers": {"cockroachdb-cloud": {
  "url": "https://cockroachlabs.cloud/mcp",
  "headers": {"mcp-cluster-id": "d44d1dfa-cdb2-4d37-95fa-b36e5654647f"}}}}
```

A judge cloning the repo cannot connect with this. Also, `.mcp.json` (the Claude Code config) contains
only Playwright — the CockroachDB MCP server is not registered there at all. The cluster id is a
hardcoded personal cluster.

---

## 3. AWS services — deep dive

Requirement: **≥1 AWS service**. This project uses **seven**, all genuinely load-bearing. This is the
strongest part of the submission. A full line-level reference already exists in
[`docs/AWS_SERVICE_AUDIT.md`](AWS_SERVICE_AUDIT.md) (1310 lines, written against
`template.yaml` + the ASL + every `boto3` call site) — this section records what changed since it was
written and what it flagged that still stands.

| Service | Role | Live status |
| --- | --- | --- |
| **AWS Lambda** | 8 functions, `python3.12`, last deployed 2026-07-31T04:55Z | ✅ all 8 present |
| **AWS Step Functions** | `migration-oracle-migration-workflow`, STANDARD, 7 states + guaranteed-cleanup fan-in | ✅ |
| **Amazon Bedrock** | Claude Haiku 4.5 (`us.anthropic.claude-haiku-4-5-20251001-v1:0`) for predict/recommend/grade-prose; Titan v2 for embeddings | ✅ |
| **Amazon S3** | `migration-oracle-artifacts-630434208625`, SSE-AES256, all public access blocked | ✅ |
| **AWS Secrets Manager** | `migration-oracle/connections/{run_id}`, `migration-oracle/shadow/{run_id}` | ✅ |
| **Amazon CloudWatch** | 4 accuracy metrics + 2 ops metrics in namespace `MigrationOracle`; 2 alarms | ⚠️ see below |
| **Amazon EventBridge** | `rate(15 minutes)` orphan sweeper schedule | ✅ |

### 3.1 Gaps found

1. **`ExecuteMigrationFunction` missing `bedrock:InvokeModel`** — §2.3 Blocker B. **This is the one
   that breaks a claimed feature.**
2. **Both CloudWatch alarms are `ActionsEnabled: False`.** `migration-oracle-cleanup-failed` and
   `migration-oracle-orphaned-shadow-clusters` can enter ALARM but there is no SNS topic, email, or
   webhook anywhere. "We have alarms" overstates it — nothing notifies anyone.
3. **The alarms and custom log groups cannot be created by any deployed role.** No Lambda policy grants
   `cloudwatch:PutMetricAlarm` or `logs:PutRetentionPolicy`; `ensure_standard_alarms()` only runs from
   `verify_phase8_full.py` / `verify_phase8d_aws.py` with operator credentials. They are not
   self-provisioning infrastructure.
4. **5 of 7 Lambdas hold unused `s3:*` grants.** Only `discover-schema` and `persist-results` call
   `runtime.artifacts`. Over-broad relative to actual use.
5. **`CollectMetricsFunction` makes zero AWS SDK calls.** It holds S3 + Secrets Manager + CloudWatch
   grants and uses none — its whole body is a dict transform. It exists for pipeline shape.
6. **Nothing ever reads an S3 artifact back.** `ArtifactStore.get_bytes`/`get_json`/`put_step_output`
   have no call sites. S3 is a write-only audit trail here; the authoritative copy is CockroachDB.
7. **Dead AWS code:** `AwsClientFactory.lambda_()` (never called),
   `SecretsService.store_customer_connection()` (never called — the real path is
   `_store_connection_url` in `routes/runs.py`), `validate_workflow_definition()` (scripts only, never
   at deploy or startup).

---

## 4. Redundancy audit

### 4.1 Redundant — should be removed before submission

| Item | Evidence | Recommendation |
| --- | --- | --- |
| **`framer-to-next-dream-main/`** and **`pixel-perfect-clone-64427-main/`** | Both are **tracked in git** (`.lovable/project.json` present — Lovable exports). The live app is `frontend/oracle/apps/web`. | **Delete both.** Two full duplicate React apps in a repo judges will clone reads as unfinished. |
| **`frontend/index.html` + `app.js` + `styles.css`** | Legacy static UI; `README.md` explicitly calls `/ui` "retired". Still tracked. | Delete or move under `docs/archive/`. |
| **`.tmp_schema.json`** (263 KB), **`debug-a64fa9.log`**, **`.playwright-mcp/`** | Root-level scratch. `.gitignore` covers the latter two but `.tmp_schema.json` is matched by `.tmp_*.json` yet a 263 KB file is sitting there. | Remove from the working tree. |
| **`.judge_ro_password`, `.judge_ro_database_url`** | Gitignored, but credential-shaped files in the repo root. | Move under `.local_secrets/`. |

### 4.2 Redundant by design — keep, but label

| Item | Why it looks redundant | Verdict |
| --- | --- | --- |
| `ccloud_provider.py` (CLI) vs `ccloud_api_provider.py` (REST) | Two provisioning paths for the same thing. `SHADOW_PROVIDER=ccloud_api` is the default in `.env` **and** in the Lambda `Globals`, so the CLI provider never runs. Its own docstring warns the command surface is unverified. | **Genuinely dead.** Either wire it up as a real third tool (§6.4) or delete it. Do not claim "ccloud CLI" while it is unreachable. |
| `MockShadowProvider` + `LocalShadowVerifyService` + `POST /runs/{id}/verify-local` | A whole second lifecycle that bypasses Step Functions. | **Keep.** It is engineer-only, deliberately not in the product UI, and is the documented fallback when `sfn_ready` is false. Legitimate. |
| `job_watch.py` (`SHOW JOBS` over SQL) vs the MCP investigation | Both inspect the shadow cluster post-migration. | **Keep both — they are complementary.** Fixed SQL can only check what a human anticipated; the MCP agent decides what to verify. `job_watch.py`'s docstring already draws this line correctly. |
| `shadow_secret_name()` defined in both `app/aws/secrets_service.py:62` and `app/lambdas/helpers.py:112` | Two functions, identical output. | Minor. Collapse to one when convenient. |
| Three ways to resolve `shadow_secret_arn` in `load_schema`/`execute_migration` | event key → `provision_shadow_cluster` result → recompute locally. | **Keep.** Deliberate resilience; never passes the credential through ASL state. |

---

## 5. Hackathon rules compliance checklist

| Requirement (`hackathon_rules.md`) | Status | Note |
| --- | --- | --- |
| Agentic app using CockroachDB as persistent memory layer | ✅ | 42 graded memories, 163 runs, predict → verify → grade → remember is genuinely closed-loop |
| Deployed on AWS | ✅ | 8 Lambdas + SFN + S3 + Secrets + CloudWatch + EventBridge, live in `us-east-1` |
| **≥2 CockroachDB tools, meaningfully integrated** | ❌ **AT RISK** | Vector Indexing is initialized-not-exercised; MCP has never run. See §6.1–6.2. |
| ≥1 AWS service | ✅ | Seven |
| Public repo, open-source license visible | ✅ | MIT, `LICENSE` at root |
| README with setup + run instructions | ✅ | Thorough |
| **URL to functional demo app** | ⚠️ | `README.md` line 24 still says `_add after Phase 7 deploy_` — **must be filled in** |
| Demo video < 3 min showing the CockroachDB memory layer at work | ⏳ | Script exists (`demo/VIDEO_SCRIPT.md`); not yet recorded |
| Identify which CockroachDB tools and **what the agent actually did with them** | ⚠️ | `docs/HACKATHON_TOOLS.md` currently claims MCP works. Post-fix this becomes true; pre-fix it is inaccurate. |
| Identify which AWS services and how | ✅ | `docs/AWS_SERVICE_AUDIT.md` is exemplary |
| Architectural diagram (optional) | ➖ | Worth adding — cheap points |
| New project, built during submission period | ✅ | Git history June 30 – present |

### Against the five judging criteria

| Criterion | Current standing |
| --- | --- |
| **Agentic Memory Design** | Strong — real embeddings, real graded outcomes, hybrid retrieval, corpus + per-owner scoping. Weakened by the index not actually serving queries. |
| **Technological Implementation** | Strong engineering, **but** the two headline CockroachDB integrations don't execute. This is the criterion most exposed by §1–2. |
| **Real-World Impact** | Strong — "will this migration break prod, and how wrong were we last time" is a real, unsolved operator problem. |
| **Production Readiness** | Good: least-privilege IAM, guaranteed cleanup fan-in, orphan sweeper, txn retry, read-only MCP. Weakened by non-notifying alarms and the silent-degradation pattern (§7). |
| **Creativity & Originality** | Strong — self-grading closed loop is genuinely novel; most entries will be RAG chatbots. |

---

## 6. Remediation plan — what to do, in priority order

### 6.1 🔴 P0 — Make the vector index actually serve retrieval

**Effort:** ~1 hour. **Impact:** converts Tool 1 from "initialized" to "meaningfully integrated."

**Step 1 — new Alembic migration** (`m8h4e1f7a596_vector_index_prefix_columns.py`):

```python
def upgrade() -> None:
    # Prefix column + partial predicate so tenant-scoped retrieval can use the
    # distributed vector index. Verified against CockroachDB v26.2.1: this plan
    # produces `vector search … prefix spans: [/'a'-'a'] [/'b'-'b']` for the
    # owner IN (owner, corpus) query shape HybridMemoryRetrieval issues.
    op.execute("""
        CREATE VECTOR INDEX IF NOT EXISTS ix_migration_memories_embedding_scoped
        ON migration_memories (owner_identity, embedding vector_cosine_ops)
        WHERE embedding_status = 'ready'
    """)
    # Keep the unscoped index — it still serves corpus-wide semantic search (§6.3),
    # which carries no owner predicate.

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_migration_memories_embedding_scoped CASCADE")
```

**Step 2 — drop the residual predicate** in
[`migration_memory_repository.py:51-63`](../backend/app/repositories/migration_memory_repository.py#L51-L63).
Remove `embedding IS NOT NULL` — rows with a NULL vector are not in a vector index at all, so the
predicate is dead weight that the planner must apply *after* the top-k and which can silently shrink
the candidate pool:

```sql
SELECT id, (embedding <=> CAST(:qv AS VECTOR(1024))) AS distance
FROM migration_memories
WHERE embedding_status = :ready
  AND owner_identity IN (:o0, :o1)
ORDER BY embedding <=> CAST(:qv AS VECTOR(1024))
LIMIT :lim
```

**Step 3 — prove it, and keep proving it.** Add to `backend/scripts/verify_phase10_grading_memory.py`
an assertion that the plan for the real retrieval query contains `vector search`:

```python
plan = "\n".join(r[0] for r in (await conn.execute(text("EXPLAIN " + RETRIEVAL_SQL), params)).fetchall())
assert "vector search" in plan, f"Distributed vector index not used:\n{plan}"
```

This is the single highest-value thing in this document: it turns a claim a judge can falsify into a
claim a judge can verify, and it is the difference between "we created an index" and "our retrieval
runs on CockroachDB's distributed vector index."

**Step 4 — tune recall once it is on the index path.** `vector_search_beam_size` is at its default of
32. With `candidate_pool_size: 20` and a growing corpus, consider `SET vector_search_beam_size = 64`
on the retrieval session and measure recall against the current brute-force results (which are exact,
so today's output is a perfect ground-truth set to validate against — capture it *before* switching).

### 6.2 🔴 P0 — Make the MCP investigation actually run

**Effort:** ~30 minutes plus a redeploy. **Impact:** converts Tool 2 from dead code to a working tool.

**Step 1 — bundle the package.** Add to
[`backend/requirements-lambda.txt`](../backend/requirements-lambda.txt):

```
mcp>=2.0.0
```

`mcp` is pure-Python, so it installs cleanly under the existing
`--platform manylinux2014_x86_64 --only-binary=:all:` flags.

**Step 2 — grant Bedrock to ExecuteMigration.** In
[`infra/sam/template.yaml`](../infra/sam/template.yaml), inside
`ExecuteMigrationFunction.Properties.Policies[0].Statement`, add the same statement
`PersistResultsFunction` already has:

```yaml
            - Effect: Allow
              Action:
                - bedrock:InvokeModel
                - bedrock:InvokeModelWithResponseStream
              Resource:
                - !Sub "arn:aws:bedrock:us-east-1::foundation-model/*"
                - !Sub "arn:aws:bedrock:us-east-1:${AWS::AccountId}:inference-profile/*"
```

**Step 3 — redeploy.** Per `memory/shadow-lambda-deploy.md`, the PowerShell scripts fail on this box;
run from Bash:

```bash
cd infra/sam && bash -c './build.ps1' || sam build
sam deploy --region us-east-1
```

**Step 4 — verify with the same evidence used to find the bug.** Run one real shadow migration, then:

```bash
aws logs filter-log-events \
  --log-group-name "/aws/lambda/migration-oracle-execute-migration" \
  --filter-pattern "investigation" --limit 10
```

Success looks like `"Blast-radius investigation completed"` with a nonzero `tool_calls`. Then confirm
`explainability.bedrock_traces.blast_radius_investigation.attempts[].tool_calls[]` is populated on the
run — those are the live MCP receipts, and they are exactly what the video should show.

**Step 5 — stop failing silently.** The current design swallows every failure into
`"MCP investigation unavailable for this run"`, which is why this went unnoticed for a week. Keep the
best-effort behavior (it is correct — MCP must never fail a migration) but make the *reason*
observable: emit a CloudWatch metric `McpInvestigationSkipped` dimensioned by reason
(`import_error` / `auth` / `no_model` / `connect_failed`), and surface the reason string in the run's
`cockroachdb_tools` field rather than a generic sentence.

**Step 6 — fix the IDE config.** Add an `Authorization` header placeholder and document it:

```json
{"mcpServers": {"cockroachdb-cloud": {
  "url": "https://cockroachlabs.cloud/mcp",
  "headers": {
    "Authorization": "Bearer ${CCLOUD_API_SECRET}",
    "mcp-cluster-id": "${CCLOUD_CLUSTER_ID}"
  }}}}
```

Also register it in `.mcp.json` so Claude Code picks it up, and note in the README that judges must
supply their own cluster id.

### 6.3 🟠 P1 — Semantic search over agent memory (the third CockroachDB feature)

**Effort:** ~4 hours. **Impact:** a third, independently demonstrable use of Distributed Vector
Indexing, and the single most natural thing missing from the product.

Today [`GET /runs/memories`](../backend/app/api/routes/memories.py) is **list + filter only** —
`owner_identity`, `embedding_status`, `limit`, `offset`, ordered by `created_at DESC`. There is no way
to ask the memory layer a *question*. Every embedding in the corpus is already there and already
`ready`; the retrieval machinery already exists. This is wiring, not new capability.

Critically, this is the **one query shape with no owner predicate** — corpus-wide search — so it needs
no prefix column. It rides `ix_migration_memories_embedding_ready` (added by Task 1's migration) and
produces a clean `vector search` plan **that the planner chooses unforced today**, which the
owner-scoped path does not at the current 42-row corpus. It is therefore the most direct on-camera
demonstration of the distributed vector index available.

> **Corrected 2026-07-31 (Task 1).** This section originally claimed corpus-wide search would ride the
> *existing* unscoped `ix_migration_memories_embedding` with no migration required. That was wrong:
> the `embedding_status = 'ready'` predicate disqualifies the non-partial index exactly as the owner
> predicate does, and EXPLAIN showed a `FULL SCAN`. A second partial index without prefix columns —
> `(embedding vector_cosine_ops) WHERE embedding_status = 'ready'` — was added alongside the scoped
> one to serve this shape. See §1.6.

#### 6.3.1 Repository layer

Add to `MigrationMemoryRepository`:

```python
async def semantic_search(
    self,
    *,
    query_vector_literal: str,
    owner_identities: list[str] | None = None,   # None => corpus-wide
    migration_type: str | None = None,
    scale_tier: str | None = None,
    min_similarity: float = 0.0,
    limit: int = 10,
) -> list[tuple[MigrationMemory, float]]:
    """Free-text semantic search over graded memories.

    Owner-scoped calls ride ix_migration_memories_embedding_scoped (prefix
    spans); corpus-wide calls ride ix_migration_memories_embedding. Structural
    filters (migration_type, scale_tier) are applied AFTER the top-k so they
    never disqualify the vector index — over-fetch, then narrow.
    """
```

**Design rule that matters:** do **not** put `migration_type` / `scale_tier` into the SQL `WHERE`.
That is the exact mistake that killed the index in §1.4. Over-fetch `limit * 4` from the vector search
and filter in Python — the same over-fetch-then-re-rank shape `HybridMemoryRetrieval` already uses.

#### 6.3.2 API

```
POST /runs/memories/search
{
  "query": "adding a NOT NULL column to a large table without a default",
  "scope": "mine" | "corpus" | "all",     // default "all"
  "migration_type": "add_column",          // optional post-filter
  "scale_tier": "large",                   // optional post-filter
  "limit": 10
}
→ 200
{
  "query": "...",
  "embedding_model_id": "amazon.titan-embed-text-v2:0",
  "index_used": "ix_migration_memories_embedding",
  "took_ms": 41,
  "results": [{
    "memory_id": "...", "migration_run_id": "...",
    "similarity_score": 0.83,
    "migration_summary": "...", "lessons_learned": "...",
    "surprise_notes": "...", "outcome_class": "...",
    "scale_tier": "large", "migration_type": "add_column",
    "predicted_duration_seconds": 12.0, "actual_duration_seconds": 47.3,
    "memory_origin": "graded_run" | "open_source_corpus",
    "not_a_graded_run": false, "source_url": null
  }]
}
```

Reuse `EmbeddingClientDep` for the query embedding and the existing `RetrievedMemory` integrity fields
(`memory_origin`, `not_a_graded_run`, `source_url`, `ui_label`) so seeded open-source corpus entries
stay visually distinct from real graded runs — that honesty is already built and should not be lost.

Returning `index_used` and `took_ms` in the response is deliberate: it makes the vector index visible
in the UI, which is worth real points on camera.

#### 6.3.3 UI

On [`/dashboard/memory`](../frontend/oracle/apps/web/app/dashboard/memory/page.tsx), add a search box
above the existing list:

- Debounced free-text input → `POST /runs/memories/search`.
- Scope toggle: **My memories / Shared corpus / All**.
- Each result shows the similarity score as a bar plus the predicted-vs-actual delta — the thing that
  makes this memory layer different from a document store.
- A small footer line: `CockroachDB distributed vector index · ix_migration_memories_embedding · 41 ms`.

#### 6.3.4 Make it agent-facing, not just human-facing

The rules ask *"what did the agent actually do with them?"* — so the strongest version exposes this
search as a **tool the prediction agent can call**, not only a UI feature:

Add `search_prior_migrations(query: str, limit: int)` to the tool list in
`blast_radius_investigator.py`'s `converse_with_tools` call, alongside the MCP tools. The investigating
agent can then ask its own follow-up questions of the memory corpus — *"have we seen a backfill stall
like this before?"* — mid-investigation, and the answer arrives from a CockroachDB vector search over
its own graded history.

That is a defensible, specific, non-generic answer to the judging question, and it makes the memory
layer agentic rather than merely persistent.

### 6.4 🟡 P2 — Decide the ccloud CLI question

Two honest options; pick one and stop claiming both:

**Option A (recommended) — delete `ccloud_provider.py`.** With §6.1 + §6.3, the submission has
Vector Indexing (three distinct uses) + MCP = two tools, both genuinely working. The CLI adds nothing
and its unverified command surface is a liability. Remove the `"ccloud"` branch from
`shadow/factory.py`, the `ccloud_binary` setting, and the CLI mentions in `config.py`.

**Option B — make it real as a third tool.** Use `ccloud` for the operations the REST provider does
not cover and that genuinely benefit from the control plane: `ccloud cluster list -o json` in the
orphan sweeper as a cross-check against the REST listing, and `ccloud cluster sql --help`-style
introspection in `judge_chaos_checks.py`. Only do this if you will actually verify each command
against the installed CLI, as that file's own docstring insists.

Either way, update `docs/HACKATHON_TOOLS.md` — it currently says "The second CRDB tool for judging is
MCP/job-watch, not flipping the default to ccloud CLI," which was honest, but the MCP half is
currently untrue.

### 6.5 🟡 P2 — AWS hygiene

| Fix | Effort |
| --- | --- |
| Add an SNS topic + `AlarmActions` and flip `ActionsEnabled: True` on both alarms | 30 min |
| Move alarm/log-group provisioning into `template.yaml` as real `AWS::CloudWatch::Alarm` resources, so they exist after `sam deploy` instead of only after an operator script | 45 min |
| Drop unused `s3:*` from `provision-shadow-cluster`, `load-schema`, `execute-migration`, `collect-metrics`, `cleanup` | 15 min |
| Delete `AwsClientFactory.lambda_()`, `SecretsService.store_customer_connection()`, `ArtifactStore.put_step_output()`/`step_output_key()` | 20 min |
| Call `validate_workflow_definition()` at API startup so a malformed ASL fails fast | 20 min |

### 6.6 🟢 P3 — Submission hygiene

- [ ] Fill in the public demo URL in `README.md` (currently `_add after Phase 7 deploy_`)
- [ ] Delete `framer-to-next-dream-main/` and `pixel-perfect-clone-64427-main/` from git
- [ ] Delete legacy `frontend/index.html` / `app.js` / `styles.css`
- [ ] Remove `.tmp_schema.json` (263 KB) and `debug-a64fa9.log`
- [ ] Add the optional architecture diagram (CockroachDB ↔ AWS ↔ agent) — cheap, explicitly invited
- [ ] Rewrite `docs/HACKATHON_TOOLS.md` after §6.1/§6.2 land, with the *verification command* for each
      claim next to it, so a judge can reproduce rather than trust
- [ ] Record the video showing: (a) the `EXPLAIN` with `vector search`, (b) live MCP tool calls in the
      Model Traces panel, (c) semantic search returning a prior graded run

---

## 7. Cross-cutting observation: silent degradation

Three of the four defects in this document share one cause. The codebase uses a best-effort
`try/except → log warning → return None` pattern for everything that touches an external system:

- `open_shadow_mcp_session` on `ImportError` → yields `None`
- `_run_blast_radius_investigation` on any exception → returns `None`
- `publish_metrics_to_cloudwatch`, `record_cleanup_failed`, `snapshot_schema_jobs` → warn and continue

**The pattern is correct.** An MCP outage must never fail a migration that already succeeded. But
combined with (a) alarms that notify no one and (b) a generic user-facing message that does not name
the reason, it means a claimed feature can be 100% broken for a week with no signal anywhere except a
`WARNING` line in a log group nobody greps.

The fix is not to remove the pattern — it is to make degradation **loud in aggregate** while staying
**silent per request**:

1. Every best-effort skip emits a CloudWatch metric dimensioned by reason.
2. `/health` gains a `degraded_capabilities: []` array — MCP unavailable, embeddings pending, vector
   index not used — computed at request time.
3. The run's `cockroachdb_tools` string names the actual reason, not "unavailable for this run."

This is directly the "Production Readiness" criterion: *"Has the team thought about resilience,
observability, and what happens when things go wrong?"* The resilience is already there and is good.
The observability of the resilience is what is missing.

---

## Appendix A — Reproducing every finding in this document

```bash
# --- Vector index exists but is unused (§1.3) ---
# Any psql-compatible client against DATABASE_URL:
SELECT indexname, indexdef FROM pg_indexes WHERE tablename='migration_memories';
--   ix_migration_memories_embedding … USING cspann (embedding vector_cosine_ops)

EXPLAIN SELECT id FROM migration_memories
  WHERE embedding IS NOT NULL AND embedding_status='ready'
    AND owner_identity IN ('__migration_oracle_corpus__','judge-demo')
  ORDER BY embedding <=> (SELECT embedding FROM migration_memories WHERE embedding IS NOT NULL LIMIT 1)
  LIMIT 20;
--   → scan + top-k, NO "vector search" node

EXPLAIN SELECT id FROM migration_memories@ix_migration_memories_embedding
  WHERE embedding_status='ready' ORDER BY embedding <=> … LIMIT 20;
--   → ERROR: index "ix_migration_memories_embedding" cannot be used for this query

# --- MCP has never run (§2.2) ---
aws logs filter-log-events \
  --log-group-name "/aws/lambda/migration-oracle-execute-migration" \
  --filter-pattern "MCP" --limit 20 --query "events[].message" --output text
#   → "mcp package not installed; skipping MCP investigation"

aws logs filter-log-events \
  --log-group-name "/aws/lambda/migration-oracle-execute-migration" \
  --filter-pattern "investigation" --limit 20
#   → zero events

# --- ExecuteMigration lacks Bedrock (§2.3) ---
aws iam get-role-policy \
  --role-name migration-oracle-ExecuteMigrationFunctionRole-72wgzoDiF2ZC \
  --policy-name ExecuteMigrationFunctionRolePolicy0 \
  --query "PolicyDocument.Statement[].Action"
#   → no bedrock:* entry

# --- mcp missing from the Lambda bundle (§2.3) ---
grep -c mcp backend/requirements-lambda.txt   # → 0
grep -n mcp backend/pyproject.toml            # → 19:    "mcp>=2.0.0",
```

## Appendix B — The prefix-index fix, proven

Run on the live v26.2.1 cluster against a throwaway table (created and dropped):

```sql
CREATE TABLE _vecidx_probe (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner STRING NOT NULL, status STRING NOT NULL, emb VECTOR(1024));

CREATE VECTOR INDEX probe_partial ON _vecidx_probe (owner, emb vector_cosine_ops)
  WHERE status = 'ready';                                        -- ✅ accepted

EXPLAIN SELECT id FROM _vecidx_probe
  WHERE owner IN ('a','b') AND status='ready'
  ORDER BY emb <=> CAST('[…]' AS VECTOR(1024)) LIMIT 5;
```

```
└── • lookup join
    └── • vector search
          table: _vecidx_probe@probe_partial (partial index)
          target count: 5
          prefix spans: [/'a' - /'a'] [/'b' - /'b']
```

Multi-prefix `(status, owner, emb vector_cosine_ops)` and plain-prefix
`(owner, emb vector_cosine_ops)` were also accepted and also produced `vector search` plans.
`IN (…)` correctly expands into one prefix span per value — matching the
owner + shared-corpus scoping in `HybridMemoryRetrieval.retrieve()`.
