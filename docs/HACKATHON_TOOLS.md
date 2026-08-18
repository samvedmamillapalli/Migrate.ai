# Hackathon tools narrative

Judging expects **≥2 CockroachDB tools** and **≥1 AWS service**, *meaningfully
integrated — not just initialized*.

Every claim below has a command next to it. Run the command; don't take the claim on
trust. That's deliberate: an earlier version of this file claimed an integration that
had, in fact, never once executed in production (see
[`HACKATHON_INTEGRATION_AUDIT.md`](HACKATHON_INTEGRATION_AUDIT.md) §2).

---

## CockroachDB tools used

### 1. Distributed Vector Indexing — three distinct uses

Not one embedding lookup wearing three hats. Three different query shapes, two
different indexes, serving three different consumers.

| # | Use | Index | Consumer |
| --- | --- | --- | --- |
| 1a | Hybrid memory retrieval that grounds each prediction | `ix_migration_memories_embedding_scoped` (owner-scoped, partial) | the prediction pipeline |
| 1b | Corpus-wide semantic search in the product UI | `ix_migration_memories_embedding_ready` (no owner predicate, partial) | a human, on `/dashboard/memory` |
| 1c | `search_prior_migrations` — the agent querying its own graded history mid-investigation | `ix_migration_memories_embedding_ready` | the blast-radius agent |

Both indexes are **partial** (`WHERE embedding_status = 'ready'`) and the scoped one
carries `owner_identity` as a **prefix column**. That is not decoration: without it,
every tenant-scoped retrieval is structurally ineligible for the index and silently
degrades to a full scan plus a brute-force sort. Alembic revision `m8h4e1f7a596`.

**Verify the index exists and is a real vector index:**

```sql
SELECT indexname, indexdef FROM pg_indexes
WHERE tablename = 'migration_memories' AND indexdef LIKE '%cspann%';
```

Expect two `USING cspann (... vector_cosine_ops)` rows.

**Verify a query actually rides it** (this is the check that matters — an index that
exists but is never used is the failure mode this project already had once):

```sql
EXPLAIN SELECT id FROM migration_memories
WHERE embedding_status = 'ready'
ORDER BY embedding <=> (SELECT embedding FROM migration_memories
                        WHERE embedding_status='ready' LIMIT 1)
LIMIT 10;
```

Expect a `• vector search` node naming
`migration_memories@ix_migration_memories_embedding_ready (partial index)`.

**Verify via the running API** (no SQL client needed):

```bash
curl -s localhost:8003/memories/health | python -m json.tool
```

Expect `"vector_index_used": true` and a `vector_index` block reporting `usable`,
`selected_at_pool_size`, and `corpus_wide_selected`.

**Verify the product feature end to end** (needs a Clerk token, see below):

```bash
curl -s -X POST localhost:8003/memories/search \
  -H "Authorization: Bearer $(python backend/scripts/clerk_test_token.py)" \
  -H "Content-Type: application/json" \
  -d '{"query":"add a column to a large table","scope":"all","limit":3}'
```

Expect ranked results plus `index_used` and `took_ms` — the response deliberately
names the index so the UI can show *which* CockroachDB index served the search.

**Automated regression guard:** `backend/scripts/verify_phase10_grading_memory.py`
asserts the index is *usable* (forces it and requires a `vector search` + `prefix
spans` plan) and that the planner *chooses* it unforced at small k. It deliberately
does **not** assert selection at large k — on a small corpus the optimizer correctly
prefers an exact brute-force scan, and asserting otherwise would be a false alarm.

### 2. CockroachDB Cloud Managed MCP Server

A genuine Bedrock tool-use agent with live, **read-only** MCP access to the shadow
cluster it is investigating, run once per migration immediately after execution.

- Read-only *by construction*, not convention: `ShadowMcpSession.tool_defs()` filters
  the server's write tools (`create_database`, `create_table`, `insert_rows`) out of
  the tool list before the model ever sees them, and `call_tool` refuses them even if
  asked (`backend/app/shadow/mcp_client.py`).
- Bounded: 8 tool calls per investigation, shared across MCP tools *and* the
  agent's own `search_prior_migrations` memory tool.
- Every call's real arguments and real result text are persisted into the run's
  `explainability.bedrock_traces.blast_radius_investigation` — receipts, so a claim in
  the verdict can be checked against what the tool actually returned.
- Best-effort by design: it is enrichment on top of an already-measured migration and
  can never fail the migration.

**Verify it actually ran** (this is the exact command that originally proved it
*wasn't* running):

```bash
aws logs filter-log-events \
  --log-group-name "/aws/lambda/migration-oracle-execute-migration" \
  --filter-pattern "investigation" --limit 20 \
  --query "events[].message" --output text
```

Success looks like `Blast-radius investigation completed` with a nonzero
`tool_calls`. Any `skipping MCP investigation` line means it did **not** run — read
the reason rather than assuming.

**Verify the receipts persisted:**

```bash
curl -s localhost:8003/runs/<run_id>/model-traces \
  -H "Authorization: Bearer $(python backend/scripts/clerk_test_token.py)"
```

Expect `blast_radius_investigation.attempts[].tool_calls[]` with real tool names,
arguments, and `result_text`.

### Tools deliberately NOT claimed

- **ccloud CLI** — *not used.* A CLI-based shadow provider existed but never ran
  (`SHADOW_PROVIDER=ccloud_api` is the default in `.env` and hardcoded in the SAM
  template), and its command surface was never verified against a real CLI. It was
  **deleted** rather than left in as something that could be mistaken for a used tool.
  Shadow clusters are provisioned through the CockroachDB Cloud **REST API**
  (`app/shadow/ccloud_api_provider.py`), which works headlessly where the CLI does not.
- **Agent Skills repo** — not used.

---

## AWS services used

| Service | Role | Verify |
| --- | --- | --- |
| **Amazon Bedrock** | Claude for prediction/recommendation/grading prose and the blast-radius agent; Titan v2 for every embedding | `curl -s localhost:8003/health` → `bedrock_configured: true` |
| **AWS Lambda** | 8 functions under `backend/app/lambdas/handlers/` | `aws lambda list-functions --query "Functions[?starts_with(FunctionName,'migration-oracle')].FunctionName"` |
| **AWS Step Functions** | `infra/stepfunctions/migration_workflow.asl.json` — 7 states with guaranteed-cleanup fan-in | `curl -s localhost:8003/health` → `sfn_ready: true` |
| **Amazon S3** | Run artifacts (schema snapshots, execution reports), SSE-AES256, all public access blocked | `aws s3 ls s3://migration-oracle-artifacts-<account>/runs/` |
| **AWS Secrets Manager** | Customer connection URLs + per-run shadow credentials; the credential value never travels through Step Functions state, only its ARN | `aws secretsmanager list-secrets --query "SecretList[?starts_with(Name,'migration-oracle/')].Name"` |
| **Amazon CloudWatch** | Accuracy/ops metrics in namespace `MigrationOracle`; structured JSON logs | `aws cloudwatch list-metrics --namespace MigrationOracle` |
| **Amazon EventBridge** | `rate(15 minutes)` orphan-cluster sweeper | `aws lambda get-function --function-name migration-oracle-shadow-sweeper` |

**Bedrock IAM note worth checking**, because it was wrong until 2026-08-02:
`ExecuteMigrationFunction` needs `bedrock:InvokeModel` for the MCP investigation's
Converse call. Without it the investigation fails with `AccessDeniedException` that
the best-effort handler swallows into a generic "unavailable" message.

```bash
ROLE=$(aws lambda get-function-configuration \
  --function-name migration-oracle-execute-migration --query Role --output text | sed 's|.*/||')
aws iam get-role-policy --role-name "$ROLE" \
  --policy-name "$(aws iam list-role-policies --role-name "$ROLE" --query 'PolicyNames[0]' --output text)" \
  --query "PolicyDocument.Statement[].Action"
```

Expect `bedrock:InvokeModel` in the output.

---

## Getting a token for the authenticated checks

The API is Clerk-gated. `backend/scripts/clerk_test_token.py` mints a real session JWT
for the documented test account (`docs/TEST_ACCOUNT.md`) so these commands work
without a browser:

```bash
cd backend
python scripts/clerk_test_token.py            # print a JWT
python scripts/clerk_test_token.py --check    # mint + smoke-test the API
```

Two gotchas: Clerk session tokens expire in **~60 seconds** (mint and use in one
shot, never cache), and Clerk's edge returns **403 to urllib's default User-Agent**
— the script sets an explicit one.

---

## Closed-loop gate

Step Functions is only started after a Phase 9 prediction **and** a human `proceed`
approval — `WorkflowOrchestrationService.start_for_run(..., require_prediction_and_approval=True)`
refuses otherwise. The agent does not get to run a migration against a shadow cluster
just because it wants to.
