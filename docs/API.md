# Migration Oracle API

This document describes the application's current HTTP API.

Local base URL:

```text
http://localhost:8000
```

All request and response bodies use JSON. Timestamps use ISO 8601 format in UTC.

## Migration run statuses

Valid statuses are:

- `pending`
- `predicting`
- `running`
- `completed`
- `failed`

Allowed transitions are:

- `pending` → `predicting` or `failed`
- `predicting` → `running` or `failed`
- `running` → `completed` or `failed`
- `completed` and `failed` are terminal

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
  "migration_sql": "ALTER TABLE users ADD COLUMN timezone STRING;"
}
```

`migration_sql` is required and must contain at least one non-whitespace character. Leading and trailing whitespace is removed before storage.

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

