# Switching to a new CockroachDB Cloud account

Written 2026-08-02, after shadow provisioning started failing with
`CockroachDB Cloud API 400: free trial is not active`.

## What's actually wrong

Your `DATABASE_URL` already points at the **new** account's cluster, but the
service-account API credentials still belong to the **old** account. The app
authenticates to the CockroachDB Cloud control plane with those credentials, so every
attempt to create a shadow cluster is evaluated against the old org — whose trial has
expired.

Verified on this machine:

| Value | Points at | Status |
| --- | --- | --- |
| `DATABASE_URL` | `migration-oracle-30746…aws-us-east-1` | ✅ new account |
| `CCLOUD_API_KEY` / `CCLOUD_API_SECRET` | old org — the API lists only `migration-oracle-dev-29576` | ❌ **stale** |
| `.cursor/mcp.json` → `mcp-cluster-id` | `d44d1dfa-…` = the **old** cluster | ❌ **stale** |
| `CCLOUD_API_KEY_SECRET_ARN` → Secrets Manager | holds a `CCDB1_…` copy of the old key | ❌ **stale** |
| Deployed Lambda env (`CCLOUD_API_SECRET`) | baked in at deploy time — still the old key | ❌ **stale until redeploy** |

Confirming the mismatch yourself:

```bash
# Lists ONLY the old cluster -> proves the key belongs to the old org
curl -s -H "Authorization: Bearer $CCLOUD_API_SECRET" \
  https://cockroachlabs.cloud/api/v1/clusters | python -m json.tool
```

---

## Step 1 — Create a service account + API key in the NEW org

This is the fix. Everything else is follow-through.

1. Sign in at <https://cockroachlabs.cloud> **with the new account**.
2. Confirm you're in the right organization — the org switcher is top-left. If you
   belong to both, this is the easiest thing to get wrong.
3. Go to **Access Management → Service Accounts** → **Create Service Account**.
   - Name it something like `migration-oracle-shadow`.
   - **Role: `Cluster Creator` at org scope** (minimum that works). The app both
     creates *and* destroys shadow clusters; a service account automatically becomes
     Cluster Administrator of clusters it creates, which covers deletion. `Org
     Administrator` also works if you'd rather not think about scoping.
4. Open the new service account → **API Keys** → **Create API Key**.
5. **Copy the secret immediately.** It is shown exactly once and looks like
   `CCDB1_<something>_<something>`. If you lose it, delete the key and make another.

Put it in `.env`:

```dotenv
CCLOUD_API_SECRET=CCDB1_...the full secret shown once...
CCLOUD_API_KEY=CCDB1_...same value is fine; only the secret is used as the Bearer token...
```

> `CCLOUD_API_KEY` is metadata only. `resolve_ccloud_api_bearer_token()` in
> `backend/app/shadow/factory.py` prefers `CCLOUD_API_SECRET`, and falls back to
> `CCLOUD_API_KEY` if the secret looks truncated. Setting both to the full secret is
> safe and avoids a confusing failure mode.

**Verify before going further** — this must list your *new* cluster:

```bash
curl -s -H "Authorization: Bearer <NEW_SECRET>" \
  https://cockroachlabs.cloud/api/v1/clusters | python -m json.tool
```

And this must **not** say `free trial is not active`:

```bash
curl -s -X POST https://cockroachlabs.cloud/api/v1/clusters \
  -H "Authorization: Bearer <NEW_SECRET>" -H "Content-Type: application/json" \
  -d '{"name":"probe-delete-me","provider":"AWS","spec":{"serverless":{"regions":["us-east-1"]}}}'
```

If that succeeds it really does create a cluster — delete it:

```bash
curl -s -X DELETE -H "Authorization: Bearer <NEW_SECRET>" \
  https://cockroachlabs.cloud/api/v1/clusters/<id-from-the-response>
```

## Step 2 — Confirm / refresh `DATABASE_URL`

Yours already points at `migration-oracle-30746`. Confirm that cluster appears in the
Step 1 listing — if it doesn't, it's in the old org and you need a new control-plane
cluster in the new one.

To get a fresh connection string: **Cluster → Connect → General connection string**,
selecting (or creating) a SQL user under **SQL Users**. It must keep
`?sslmode=verify-full`; the CA cert already ships in `certs/`.

```dotenv
DATABASE_URL=postgresql://<user>:<password>@<host>:26257/migration_oracle?sslmode=verify-full
```

**If you change `DATABASE_URL`, the schema must exist on the new cluster:**

```bash
cd backend
python -m alembic upgrade head            # creates tables + both vector indexes
python scripts/seed_open_source_corpus.py # 11-record shared memory corpus
python scripts/prepare_judge_demo_db.py   # judge_ro role + 5000-row customers table
```

That last one rewrites `.local_secrets/.judge_ro_database_url`, which the demo path and
judge scripts read. Skipping it is what previously caused
`401 Invalid database credentials` on the demo button.

## Step 3 — Update the MCP cluster id

`.cursor/mcp.json` pins the **old** cluster. The Managed MCP Server is scoped per
cluster via the `mcp-cluster-id` header.

Get the new id from the Step 1 listing (`clusters[].id`), or from the Console URL when
the cluster is open (`.../cluster/<uuid>/overview`). Then:

```json
{
  "mcpServers": {
    "cockroachdb-cloud": {
      "url": "https://cockroachlabs.cloud/mcp",
      "headers": {
        "Authorization": "Bearer <NEW_SECRET>",
        "mcp-cluster-id": "<new-cluster-uuid>"
      }
    }
  }
}
```

> The runtime blast-radius investigation does **not** read this file — it scopes MCP to
> whichever shadow cluster it just provisioned, using `CCLOUD_API_SECRET`. This file is
> only for MCP from your IDE. Fixing Step 1 fixes the runtime path automatically.

## Step 4 — Rotate the Secrets Manager copy (or drop it)

`CCLOUD_API_KEY_SECRET_ARN` points at an AWS secret still holding the old key. The
sweeper Lambda can read it. Either update it:

```bash
aws secretsmanager put-secret-value --region us-east-1 \
  --secret-id "$CCLOUD_API_KEY_SECRET_ARN" --secret-string '<NEW_SECRET>'
```

…or set `CCLOUD_API_KEY_SECRET_ARN=` (empty) in `.env`, since the plain
`CCLOUD_API_SECRET` env var is what the providers actually use.

## Step 5 — Redeploy, or Lambda keeps using the old key

**This is the step that's easy to forget.** The credentials are baked into the Lambda
environment at deploy time — confirmed: the deployed
`migration-oracle-provision-shadow-cluster` currently has the old `CCLOUD_API_SECRET`.
Editing `.env` alone changes nothing in AWS.

```bash
cd infra/sam
powershell -ExecutionPolicy Bypass -File ./build.ps1
powershell -ExecutionPolicy Bypass -File ./deploy.ps1
```

`deploy.ps1` reads `.env` and passes `CCloudApiSecret` / `DatabaseUrl` as stack
parameters, so run it *after* `.env` is correct.

⚠️ **Do not edit any file under `backend/app/` while `build.ps1` is running.** It
copies `app/` per function sequentially, so mid-build edits produce Lambdas that fail at
import — this exact mistake happened on 2026-08-02.

## Step 6 — Restart the API and verify end to end

```bash
cd backend && python run_server.py 8003
```

```bash
# control plane sees the new DB
curl -s localhost:8003/health | python -m json.tool     # database: healthy, sfn_ready: true

# vector index still correct on the new cluster
curl -s localhost:8003/memories/health \
  -H "Authorization: Bearer $(python backend/scripts/clerk_test_token.py)" \
  | python -m json.tool                                  # vector_index_used: true
```

Then run one real closed loop (the thing that was blocked):

1. Dashboard → **New Migration**, or `POST /runs/debug/demo-with-db`
2. Run prediction → **Proceed** → **Start shadow test**
3. Watch it get past `ProvisionShadowCluster` — that's the step that was failing.

Finally, the MCP proof that Task 8 was blocked on:

```bash
aws logs filter-log-events \
  --log-group-name "/aws/lambda/migration-oracle-execute-migration" \
  --filter-pattern "investigation" --limit 20 \
  --query "events[].message" --output text
```

Success = `Blast-radius investigation completed` with a nonzero tool-call count.
Any `skipping MCP investigation` line means it still didn't run — read the reason.

---

## Quick reference: what changes, what doesn't

**Must change**

| Key | Where from |
| --- | --- |
| `CCLOUD_API_SECRET` | new service account API key (shown once) |
| `CCLOUD_API_KEY` | same value |
| `mcp-cluster-id` in `.cursor/mcp.json` | new cluster's UUID |
| Secrets Manager value at `CCLOUD_API_KEY_SECRET_ARN` | new secret, or blank the var |

**Check, probably already right**

| Key | Note |
| --- | --- |
| `DATABASE_URL` | already on `…-30746`; confirm it's in the new org |
| `.local_secrets/.judge_ro_database_url` | regenerate via `prepare_judge_demo_db.py` |

**Leave alone**

`CCLOUD_API_BASE_URL` (`https://cockroachlabs.cloud`), the MCP endpoint
(`https://cockroachlabs.cloud/mcp` — global, not per-org), every `SHADOW_*` tuning
value, and all AWS/Bedrock/Clerk keys.

**Can delete:** `CCLOUD_BINARY` — vestigial since the ccloud CLI provider was removed.
Harmless if left (unknown env vars are ignored).
