# Schema Analysis

This document describes schema inspection and the Phase 6 application wiring that
validates read-only credentials and persists discovery snapshots on migration runs.

Roadmap mapping: Development Roadmap Phase 6 (Database Schema Discovery).

AWS Secrets Manager storage for customer credentials is intentionally deferred.

---

## Purpose

Before Migration Oracle predicts a migration, it needs a reliable picture of the target database:

- What tables exist
- Column types and nullability
- Primary keys, foreign keys, indexes, and constraints
- Approximate row counts and storage size (when the engine exposes them)

That snapshot becomes input for Bedrock prediction in a later phase.

---

## Package layout

```text
backend/app/schema_analysis/
├── __init__.py              # Public exports
├── models.py                # Pydantic metadata models
├── database_connection.py   # Host/port/user/password/ssl model + URL builder
├── connection.py            # Async connection lifecycle
├── read_only.py             # Active write probe
├── inspector.py             # Raw catalog collection (SQL only)
└── analyzer.py              # Orchestration + structured assembly

backend/app/services/
└── schema_discovery_service.py   # Validate → discover → persist on MigrationRun
```

### Responsibility split

| Module | Responsibility |
| --- | --- |
| `database_connection.py` | Strongly typed connection parameters; builds URLs; never logs passwords |
| `connection.py` | Create/dispose async engines; redact credentials in logs |
| `read_only.py` | Transactional write probe; raises `ReadWriteCredentialsError` |
| `inspector.py` | Read-only SQL against catalogs |
| `analyzer.py` | Turn raw inspection into frozen Pydantic models |
| `SchemaDiscoveryService` | Application orchestration + JSONB persistence |

Inspection behaviour is owned by `schema_analysis`. Application persistence and
credential policy live in the service layer.

---

## DatabaseConnection

```python
from app.schema_analysis import DatabaseConnection, SslMode

connection = DatabaseConnection(
    host="db.example.com",
    port=26257,
    database="appdb",
    username="readonly_user",
    password="secret",
    ssl_mode=SslMode.VERIFY_FULL,
)

url = connection.to_database_url()
# Use connection.redacted_label() for logs — never log to_database_url().
```

| Field | Type | Notes |
| --- | --- | --- |
| `host` | `str` | Required |
| `port` | `int` | Default `5432` |
| `database` | `str` | Required |
| `username` | `str` | Required |
| `password` | `SecretStr` | Never printed by `repr()` |
| `ssl_mode` | `SslMode` | Default `require` |

Credentials are **not** stored on `MigrationRun`. Only the discovered metadata snapshot is persisted.

---

## Read-only validation

Before discovery, `discover_database_metadata`:

1. Connects and pings the target (`SELECT version()`)
2. Runs an active write probe: `CREATE TABLE "__migration_oracle_write_probe"` inside a transaction that is **always rolled back**
3. Scans privileges for `INSERT` / `UPDATE` / `DELETE` / `TRUNCATE` (and database `CREATE`) so DML-only writers are also rejected
4. If any write capability is detected → raises `ReadWriteCredentialsError` (HTTP 403 when surfaced by the API)
5. For the analysis session, sets `default_transaction_read_only = on` so discovery cannot modify customer data even if privileges change mid-flight

If role `public` retains `CREATE` on schema `public` (common CockroachDB Cloud default), every user can create tables and will be rejected. Harden customer databases by revoking `CREATE` from `public`.

---

## Persisting snapshots on MigrationRun

| Column | Description |
| --- | --- |
| `schema_snapshot` | JSONB `DatabaseMetadata` |
| `schema_discovered_at` | UTC timestamp |
| `schema_discovery_duration_ms` | Wall-clock duration including probe + inspection |
| `schema_database_engine` | `cockroachdb` / `postgresql` / `unknown` |
| `schema_database_version` | Raw `version()` string |
| `schema_discovery_status` | `pending` / `succeeded` / `failed` / `rejected` |

```python
updated_run = await discovery_service.discover_and_persist(run_id, connection)
```

---

## Timeouts (configuration)

| Setting | Env var | Default |
| --- | --- | --- |
| Connection timeout | `SCHEMA_CONNECTION_TIMEOUT_SECONDS` | `30` |
| Discovery timeout | `SCHEMA_DISCOVERY_TIMEOUT_SECONDS` | `60` |

---

## Quick start (inspection only)

```python
from app.schema_analysis import SchemaAnalyzer

metadata = await SchemaAnalyzer().analyze(database_url)
print(metadata.model_dump(mode="json", by_alias=True))
```

---

## What is collected

See models in `app/schema_analysis/models.py`:

- `DatabaseMetadata`
- `SchemaMetadata`
- `TableMetadata`
- `ColumnMetadata`
- `IndexMetadata`
- plus FK / constraint models

System schemas excluded: `information_schema`, `pg_catalog`, `pg_toast`, `crdb_internal`, `pg_extension`.

---

## Failure modes

All of the following raise meaningful ``AppError`` subclasses (not unhandled 500s):

| Situation | Exception |
| --- | --- |
| Wrong password | `SchemaAuthenticationError` |
| Database missing | `SchemaDatabaseNotFoundError` |
| Timeout | `SchemaTimeoutError` |
| SSL failure | `SchemaSSLError` |
| Network failure | `SchemaNetworkError` |
| Unsupported engine/URL | `UnsupportedDatabaseError` |
| Writable credentials | `ReadWriteCredentialsError` |

## Logging policy

Never log passwords, connection strings, or database URLs.

Only log: `host`, `database`, `run_id`, `duration_ms` (and non-sensitive counts).

---

## Verification

```bash
cd backend
python -m scripts.verify_phase6_schema_analysis
python -m scripts.verify_phase6_remaining
```

| Check | Status |
| --- | --- |
| Inspection against CockroachDB | Pass |
| `DatabaseConnection` URL builder + redaction | Pass |
| Write probe rejects writable credentials | Pass |
| Snapshot persistence on `MigrationRun` | Pass |
| Configurable timeouts | Pass |

---

## Out of scope

- Dedicated discovery REST endpoint (snapshot fields already appear on `/runs` responses)
- AWS Secrets Manager for customer credentials
- AI prediction and migration execution
