# Migration Oracle API

This document describes the application's current HTTP API.

Local base URL:

```text
http://localhost:8000
```

All request and response bodies use JSON. Timestamps use ISO 8601 format in UTC.

When `DEMO_API_KEY` is set on the server, send header `X-API-Key: <key>` on API
calls (except `/`, `/health`, `/docs`, `/ui`).

## Migration run statuses

Valid statuses are:

- `pending`
- `predicting`
- `awaiting_approval`
- `running`
- `completed`
- `failed`

Allowed transitions are:

- `pending` → `predicting` or `failed`
- `predicting` → `awaiting_approval` or `failed`
- `awaiting_approval` → `running` (proceed), `completed` (accept recommended), or `failed` (cancel)
- `running` → `completed` or `failed`
- `completed` and `failed` are terminal

Phase 9 introduces `awaiting_approval`: after prediction and recommendation, the
run stops until a human decides via `POST /runs/{id}/approve`. Selecting
`proceed` auto-starts the Step Functions verify workflow when
`MIGRATION_WORKFLOW_ARN` and a `connection_secret_arn` are available
(discover first, or pass the secret on approve / `start-workflow`).

## Error responses

Domain errors use this response shape:

```json
{
  "detail": "Error description"
}
```

FastAPI request-validation errors return `422 Unprocessable Entity` with a `detail` array identifying invalid fields.

## Root

### Get application status

- **Endpoint:** `/`
- **Method:** `GET`
- **Request body:** None

#### Example request

```bash
curl http://localhost:8000/
```

#### Response body

```json
{
  "name": "Migration Oracle",
  "status": "healthy"
}
```

#### Status codes

- `200 OK` — Application is running.

## Health

### Check application and database health

- **Endpoint:** `/health`
- **Method:** `GET`
- **Request body:** None

#### Example request

```bash
curl http://localhost:8000/health
```

#### Successful response body

```json
{
  "status": "healthy",
  "database": "healthy",
  "cockroachdb_version": "CockroachDB CCL v25.2.1"
}
```

The exact CockroachDB version string depends on the connected database.

#### Unhealthy response body

```json
{
  "status": "unhealthy",
  "database": "unhealthy",
  "cockroachdb_version": "unavailable"
}
```

#### Status codes

- `200 OK` — Application and database are healthy.
- `503 Service Unavailable` — The database connectivity check failed.

## Migration runs

### Create a migration run

- **Endpoint:** `/runs`
- **Method:** `POST`

#### Request body

```json
{
  "migration_sql": "ALTER TABLE users ADD COLUMN timezone STRING;",
  "owner_identity": "alice@example.com",
  "revises_run_id": null
}
```

`migration_sql` is required and must contain at least one non-whitespace character. Leading and trailing whitespace is removed before storage. Optional `owner_identity` (default `anonymous`) scopes Phase 10 memory retrieval. Optional `revises_run_id` links this run to an earlier recommendation for learning metrics.

#### Example request

```bash
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d "{\"migration_sql\":\"ALTER TABLE users ADD COLUMN timezone STRING;\"}"
```

#### Example response

```json
{
  "id": "68f28596-3834-4fe6-b67e-26266b56e997",
  "migration_sql": "ALTER TABLE users ADD COLUMN timezone STRING;",
  "status": "pending",
  "created_at": "2026-07-17T00:42:47.812345Z",
  "updated_at": "2026-07-17T00:42:47.812345Z",
  "schema_snapshot": null,
  "schema_discovered_at": null,
  "schema_discovery_duration_ms": null,
  "schema_database_engine": null,
  "schema_database_version": null,
  "schema_discovery_status": "pending"
}
```

After schema discovery succeeds, the same response includes a JSON schema snapshot and discovery metadata. `schema_discovery_status` is one of `pending`, `succeeded`, `failed`, or `rejected`.

#### Status codes

- `201 Created` — Migration run was stored successfully.
- `422 Unprocessable Entity` — The request body is missing, malformed, or contains empty `migration_sql`.

### List migration runs

- **Endpoint:** `/runs`
- **Method:** `GET`
- **Request body:** None

#### Query parameters

- `status` — Optional status filter. Must be a valid migration run status.
- `limit` — Optional page size from `1` to `100`. Default: `50`.
- `offset` — Optional number of records to skip. Must be `0` or greater. Default: `0`.

Runs are returned newest first. `total` is the number of records matching the status filter before pagination.

List items omit the full `schema_snapshot` JSONB payload. Use `has_schema_snapshot` and fetch `GET /runs/{run_id}` for the complete snapshot.

#### Example request

```bash
curl "http://localhost:8000/runs?status=pending&limit=10&offset=0"
```

#### Example response

```json
{
  "items": [
    {
      "id": "68f28596-3834-4fe6-b67e-26266b56e997",
      "migration_sql": "ALTER TABLE users ADD COLUMN timezone STRING;",
      "status": "pending",
      "created_at": "2026-07-17T00:42:47.812345Z",
      "updated_at": "2026-07-17T00:42:47.812345Z",
      "schema_discovered_at": null,
      "schema_discovery_duration_ms": null,
      "schema_database_engine": null,
      "schema_database_version": null,
      "schema_discovery_status": "pending",
      "has_schema_snapshot": false
    }
  ],
  "total": 1,
  "limit": 10,
  "offset": 0
}
```

#### Status codes

- `200 OK` — Run history was returned successfully.
- `422 Unprocessable Entity` — A query parameter is invalid.

### Get a migration run

- **Endpoint:** `/runs/{run_id}`
- **Method:** `GET`
- **Request body:** None

`run_id` must be a UUID.

#### Example request

```bash
curl http://localhost:8000/runs/68f28596-3834-4fe6-b67e-26266b56e997
```

#### Example response

```json
{
  "id": "68f28596-3834-4fe6-b67e-26266b56e997",
  "migration_sql": "ALTER TABLE users ADD COLUMN timezone STRING;",
  "status": "pending",
  "created_at": "2026-07-17T00:42:47.812345Z",
  "updated_at": "2026-07-17T00:42:47.812345Z",
  "schema_snapshot": null,
  "schema_discovered_at": null,
  "schema_discovery_duration_ms": null,
  "schema_database_engine": null,
  "schema_database_version": null,
  "schema_discovery_status": "pending"
}
```

#### Not-found response

```json
{
  "detail": "MigrationRun not found: 00000000-0000-0000-0000-000000000000"
}
```

#### Status codes

- `200 OK` — Migration run was returned successfully.
- `404 Not Found` — No migration run exists with the supplied UUID.
- `422 Unprocessable Entity` — `run_id` is not a valid UUID.

### Update migration run status

- **Endpoint:** `/runs/{run_id}`
- **Method:** `PATCH`

`run_id` must be a UUID.

#### Request body

```json
{
  "status": "predicting"
}
```

#### Example request

```bash
curl -X PATCH \
  http://localhost:8000/runs/68f28596-3834-4fe6-b67e-26266b56e997 \
  -H "Content-Type: application/json" \
  -d "{\"status\":\"predicting\"}"
```

#### Example response

```json
{
  "id": "68f28596-3834-4fe6-b67e-26266b56e997",
  "migration_sql": "ALTER TABLE users ADD COLUMN timezone STRING;",
  "status": "predicting",
  "created_at": "2026-07-17T00:42:47.812345Z",
  "updated_at": "2026-07-17T00:45:10.123456Z",
  "schema_snapshot": null,
  "schema_discovered_at": null,
  "schema_discovery_duration_ms": null,
  "schema_database_engine": null,
  "schema_database_version": null,
  "schema_discovery_status": "pending"
}
```

#### Conflict response

```json
{
  "detail": "Invalid status transition: predicting -> completed"
}
```

Updating a run to its current status also returns `409 Conflict`.

#### Status codes

- `200 OK` — Status was updated successfully.
- `404 Not Found` — No migration run exists with the supplied UUID.
- `409 Conflict` — The requested status transition is not allowed.
- `422 Unprocessable Entity` — `run_id`, the request body, or `status` is invalid.

### Discover schema (attach connection)

- **Endpoint:** `/runs/{run_id}/discover`
- **Method:** `POST`

Discovers customer schema read-only and stores `connection_secret_arn` on the run
for later approve → workflow.

```json
{
  "database_url": "postgresql://readonly:...@host:26257/appdb?sslmode=require"
}
```

Or pass an existing Secrets Manager pointer:

```json
{ "connection_secret_arn": "arn:aws:secretsmanager:..." }
```

### Run Phase 9 prediction pipeline

- **Endpoint:** `/runs/{run_id}/predict`
- **Method:** `POST`
- **Request body:** None

Runs deterministic policy analysis, hybrid memory retrieval, Bedrock prediction,
and Bedrock recommendation, then sets status to `awaiting_approval`. Does not
start shadow execution. Requires Bedrock config (or an injected mock client for
tests). Prefer runs that already have a Phase 6 `schema_snapshot`.

#### Status codes

- `200 OK` — Pipeline completed; run is `awaiting_approval`.
- `404 Not Found` — Run does not exist.
- `409 Conflict` — Run is not in `pending`/`predicting`, or already has a prediction.
- `422 Unprocessable Entity` — Model output failed validation twice (hard failure).
- `503 Service Unavailable` — Bedrock model id / access not configured.

### Approve a run (human gate)

- **Endpoint:** `/runs/{run_id}/approve`
- **Method:** `POST`

Requires status `awaiting_approval`.

#### Request body

```json
{
  "decision": "proceed",
  "approver_identity": "alice@example.com",
  "override_rationale": null,
  "connection_secret_arn": null,
  "start_workflow": true
}
```

`decision` must be one of:

- `proceed` — status → `running`; when workflow ARN + connection secret exist, starts Step Functions automatically
- `accept_recommended` — ends the run as `completed`; does **not** execute AI SQL
- `cancel` — ends the run as `failed`

Optional `connection_secret_arn` overrides / sets the run secret used to start SFN.
Set `start_workflow` to `false` to record proceed without starting SFN (then use
`POST /runs/{id}/start-workflow`).

When `policy_decision` on the run is `block` and `decision` is `proceed`,
`override_rationale` is required.

#### Status codes

- `200 OK` — Approval recorded and status updated.
- `404 Not Found` — Run does not exist.
- `409 Conflict` — Run is not `awaiting_approval`, or already approved.
- `422 Unprocessable Entity` — Missing override rationale for a block, or invalid body.

### Start / sync durable verify workflow

- **Endpoint:** `/runs/{run_id}/start-workflow`
- **Method:** `POST`

Requires prediction + `proceed` approval. Body may include
`connection_secret_arn` if not already on the run.

- **Endpoint:** `/runs/{run_id}/sync-workflow`
- **Method:** `POST`

Pulls Step Functions status into the run row.

### Get approval record

- **Endpoint:** `/runs/{run_id}/approval`
- **Method:** `GET`

#### Status codes

- `200 OK` — Approval returned.
- `404 Not Found` — Run or approval does not exist.

### Grade a completed run (Phase 10)

- **Endpoint:** `/runs/{run_id}/grade`
- **Method:** `POST`
- **Request body:** None

Deterministically grades the Phase 9 prediction against persisted execution
actuals, writes surprise/lessons prose, and stores an agentic memory row with a
Titan embedding. Also runs automatically after persist-results. No Step
Functions Grade state yet.

#### Status codes

- `200 OK` — Grade + memory written (idempotent on re-call).
- `404 Not Found` — Run does not exist.
- `422 Unprocessable Entity` — Missing prediction or execution result.

### Get grade / memory

- `GET /runs/{run_id}/grade`
- `GET /runs/{run_id}/memory`

### Repair pending embeddings

- **Endpoint:** `/runs/memories/repair-embeddings`
- **Method:** `POST`

```json
{ "run_id": null, "memory_id": null, "limit": 20 }
```

### Accuracy metrics (SQL)

- **Endpoint:** `/runs/metrics/accuracy`
- **Method:** `GET`

Returns scalar accuracy trend, confidence calibration, recommendation
acceptance/success rates (with denominators), memory corpus counts,
high-risk flag precision/recall, and retrieval-usefulness vs accuracy correlation.

### Shadow cluster (read-only)

- **Endpoint:** `/runs/{run_id}/shadow-cluster`
- **Method:** `GET`

Returns the Phase 7 shadow cluster lifecycle row (status, stage_timings,
error_message, destroyed_at). `404` if provision never created a row.

### Execution result (read-only)

- **Endpoint:** `/runs/{run_id}/execution-result`
- **Method:** `GET`

Returns measured shadow actuals (`actual_duration_seconds`, `actual_storage_mb`,
`success`, `timed_out`, `error_message`). `404` if verify never persisted.

### Model traces (Bedrock I/O)

- **Endpoint:** `/runs/{run_id}/model-traces`
- **Method:** `GET`

Returns durable prediction/recommendation traces from
`explainability.bedrock_traces` (system/user prompts, raw responses, parsed
JSON, latency, token counts when available, repair attempts). `404` if the run
was predicted before Phase 11 tracing.

## Memories / corpus browser

### Corpus health

- **Endpoint:** `/memories/health`
- **Method:** `GET`

Structured health: totals, counts by owner and embedding status, missing
embeddings / scale_tier / migration_type, legacy `demo-corpus` count, reserved
corpus ready count, and a loud `problems` list. Also available via:

```bash
cd backend && python scripts/corpus_health.py
```

### List memories

- **Endpoint:** `/memories`
- **Method:** `GET`

Query params: `owner_identity` (use `__migration_oracle_corpus__` for the
shared corpus), `embedding_status`, `limit`, `offset`. Each item includes
verbatim `embed_text`. Response embeds the same health summary.

### Reserved corpus identity

- **Endpoint:** `/memories/corpus-identity`
- **Method:** `GET`

```json
{ "corpus_owner_identity": "__migration_oracle_corpus__" }
```

### Closed-loop shortcut

- **Endpoint:** `/runs/{run_id}/closed-loop`
- **Method:** `POST`

```json
{
  "approver_identity": "operator",
  "connection_secret_arn": "arn:aws:secretsmanager:...",
  "override_rationale": null,
  "start_workflow": true
}
```

Runs predict if still pending, then `proceed` approval (auto-starts SFN when
configured). Prefer explicit discover → predict → approve during demos.

