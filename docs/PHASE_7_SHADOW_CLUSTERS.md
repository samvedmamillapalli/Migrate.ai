# Phase 7 — Shadow Cluster Orchestration

The "verify" step of Migration Oracle's core loop (predict → **verify** → grade →
remember). A shadow cluster is a temporary, disposable CockroachDB cluster that
exists only to run one migration safely, measure what really happens, and then
get destroyed. The customer's real database is never touched by a migration — it
is only read (structure) in Phase 6. All migration execution happens on the
shadow.

> **Framing.** Blast radius here always means **backfill duration, storage
> growth, resource saturation, and rollback safety** — never "lock duration".
> CockroachDB runs schema changes as online background jobs; there are no long
> table locks to describe.

---

## What was built

A `create → await ready → seed → run migration → destroy` lifecycle, wired into
the service layer the same way earlier phases are, plus a concurrency cap, an
orphan sweeper, and a hand-runnable verification script.

### New module: `app/shadow/`

| File | Responsibility |
| --- | --- |
| `provider.py` | `ShadowClusterProvider` abstract interface (create / await_ready / destroy / list_app_clusters). Teardown is idempotent by contract. |
| `ccloud_provider.py` | **Real** provider. Shells out to the `ccloud` CLI, parses the JSON every command emits, provisions CockroachDB Basic clusters in `aws / us-east-1`, mints a SQL user, and idempotently deletes. |
| `mock_provider.py` | **Offline** provider. Provisions an isolated scratch **database** on the control-plane cluster so the full seed→migrate→destroy path runs for real with no ccloud install or API key. Teardown drops the database. |
| `factory.py` | `create_shadow_provider(settings)` — selects the provider from `SHADOW_PROVIDER`. |
| `seeder.py` | Recreates the customer's schema *shape* from a Phase 6 `DatabaseMetadata` snapshot and loads capped synthetic rows sized to a scale tier. |
| `concurrency.py` | `acquire_slot(...)` — DB-backed admission control that waits for a free slot instead of provisioning beyond the cap. |
| `orchestrator.py` | `ShadowClusterOrchestrator.run_lifecycle(...)` — drives the whole lifecycle with **teardown guaranteed on every path** via `finally`, and measures each stage. |
| `sweeper.py` | `ShadowClusterSweeper.sweep()` — reaps app-tagged clusters older than the max lifetime, from both stale DB rows and the provider directly. |
| `models.py` | Value objects: `ScaleTier`, `ProvisionSpec`, `ProvisionedCluster`, `StageTimings`, `SeedReport`, `LifecycleReport`. |

### New service + repository (Phase 4 pattern)

- `app/services/shadow_cluster_service.py` — owns `ShadowCluster` persistence,
  status-transition validation, and transaction boundaries (`with_txn_retry` +
  service-owned commit), exactly like `MigrationRunService`.
- `app/repositories/shadow_cluster_repository.py` — `count_active`,
  `list_active`, `list_expired_active`, `get_by_migration_run_id`, etc.
- Wired into `app/dependencies.py` (`ShadowClusterSvc`).

### Lifecycle states

`PROVISIONING → READY → SEEDING → MIGRATING → DESTROYING → DESTROYED`, with
`FAILED` reachable only from `DESTROYING` (teardown itself failed → cluster may
be leaked → the sweeper is the backstop). `status` tracks the **cluster
resource**; whether the migration under test passed is a separate fact carried
in the `LifecycleReport` (and later the `ExecutionResult`).

---

## Design decisions

- **Concurrency cap = 2, overflow queues (waits).** Enforced in the database:
  `try_admit` counts active clusters and inserts the `PROVISIONING` row in a
  single serializable transaction, so the count-then-insert is race-safe across
  processes (with a 40001 retry). Callers past the cap wait and retry rather
  than provisioning a third cluster. This is admission control, not a persisted
  job queue (that overlaps with Phase 8 Step Functions).
- **Scale tiers, free-tier safe.** Row volume is hard-capped per tier
  (`small=1k`, `medium=10k`, `large=50k`) chosen from the snapshot's total
  estimated rows, so a shadow run stays comfortably inside CockroachDB Basic
  free usage.
- **Seeding recreates shape, not constraints.** Columns, types (mapped by
  family), primary keys and secondary indexes are recreated. Foreign-key and
  CHECK constraints are intentionally omitted to keep synthetic-data generation
  tractable; this does not change how CockroachDB runs the schema change under
  test.
- **Provisioning latency is measured, never assumed.** Every stage
  (`provision / ready / seed / migrate / teardown`) is timed and persisted on
  the `ShadowCluster.stage_timings` JSONB column and returned in the
  `LifecycleReport`. The demo's timing claims must come from these real numbers.

### Deferred (documented, not built)

- **Pre-warmed cluster pool.** On-demand `create` is the only strategy
  implemented. If provisioning latency proves too slow, a warm pool slots in
  behind the same `ShadowClusterProvider` interface (a warm provider returns an
  already-ready cluster from `create` and makes `await_ready` a no-op). See the
  note in `provider.py`. **Not built in this phase.**
- **AWS Step Functions / Lambda orchestration** — Phase 8.
- **Prediction (Phase 9) and grading (Phase 10).**

---

## Environment variables

Added to `.env.example` (all have safe defaults; only the ccloud provider needs
the API key):

| Variable | Purpose | Default |
| --- | --- | --- |
| `SHADOW_PROVIDER` | `mock` (offline scratch DB) or `ccloud` (real) | `mock` |
| `SHADOW_APP_TAG` | Name/tag prefix on every cluster (sweeper matches this) | `migration-oracle` |
| `SHADOW_CLUSTER_CLOUD` | Cloud for provisioning | `aws` |
| `SHADOW_CLUSTER_REGION` | Single region | `us-east-1` |
| `SHADOW_MAX_CONCURRENT` | Concurrency cap | `2` |
| `SHADOW_MAX_LIFETIME_MINUTES` | Sweeper reaps clusters older than this | `30` |
| `SHADOW_SLOT_WAIT_TIMEOUT_SECONDS` | How long to wait for a slot | `600` |
| `SHADOW_SLOT_POLL_INTERVAL_SECONDS` | Slot poll interval | `2.0` |
| `SHADOW_PROVISION_TIMEOUT_SECONDS` | Readiness ceiling (not a promise) | `600` |
| `SHADOW_READY_POLL_INTERVAL_SECONDS` | Readiness poll interval | `5.0` |
| `SHADOW_SEED_TIMEOUT_SECONDS` | Seed statement timeout | `300` |
| `SHADOW_MIGRATE_TIMEOUT_SECONDS` | Migration statement timeout | `600` |
| `CCLOUD_BINARY` | ccloud executable name/path | `ccloud` |
| `CCLOUD_API_KEY` | Non-interactive service-account API key (**secret**) | — |

The API key is never logged and never committed. It is passed to `ccloud` via
the subprocess **environment**, not as a command-line argument. Later phases move
it into AWS Secrets Manager.

### CockroachDB Cloud API key setup (for the real provider)

1. In the CockroachDB Cloud Console → **Access Management → Service Accounts**,
   create a service account with a role that permits cluster **create** and
   **delete** (Cluster Creator / appropriate admin cloud role, scoped as narrowly
   as possible).
2. Create an **API key** for that service account. Copy it immediately — it is
   shown only once.
3. Put it in `.env` as `CCLOUD_API_KEY=...` (gitignored) and set
   `SHADOW_PROVIDER=ccloud`.
4. Install the `ccloud` CLI and verify the exact subcommand surface once
   (`ccloud cluster create basic --help`, `ccloud cluster sql-users create
   --help`). `ccloud_provider.py` marks the small number of version-sensitive
   command strings with comments; adjust them if your CLI version differs. The
   control flow, JSON parsing, idempotent teardown and tagging are stable.

---

## Running the verification script

```bash
cd backend
# offline / default — provisions scratch databases on the control-plane cluster
python scripts/verify_phase7_shadow_clusters.py

# real CockroachDB Cloud (after installing ccloud + setting a real key)
SHADOW_PROVIDER=ccloud python scripts/verify_phase7_shadow_clusters.py
```

It prints a JSON report and exits non-zero on failure. It checks:

1. **Full lifecycle** — create → await ready → seed → run migration → destroy,
   with measured per-stage timings; final row status `DESTROYED`.
2. **Idempotent teardown** — destroying an already-destroyed (and a never-created)
   cluster returns success.
3. **Concurrency cap of 2** — a third simultaneous admission is refused a slot,
   and the overflow run queues then times out.
4. **Guaranteed teardown on the failure path** — a deliberately broken migration
   still tears the cluster down (`torn_down: true`, status `DESTROYED`).
5. **Sweeper** — an expired DB-tracked cluster and an old provider-tagged orphan
   database are both reaped.

**Checkpoint:** temporary clusters are created and destroyed automatically,
including on failure paths, driven through the provider interface (ccloud CLI in
production), with a working concurrency cap of 2, an orphan sweeper, and a
documented (not built) warm-pool fallback.

---

## Earlier-phase changes (flagged)

- **`ShadowCluster` model (Phase 3) extended.** Added `SEEDING` and `MIGRATING`
  states (replacing the unused `RUNNING`), and lifecycle columns: `cluster_name`,
  `scale_tier`, `expires_at`, `stage_timings` (JSONB), `error_message`. Made
  `cluster_id` nullable so the `PROVISIONING` row can be inserted *before* the
  provider returns an id (so the sweeper/concurrency accounting see in-flight
  clusters). Migration: `alembic/versions/c3f8a72b1e40_shadow_cluster_lifecycle_fields.py`.
  *Why:* the original model had no way to track where in the lifecycle a cluster
  was, when it should expire, or how long each stage took — all required by this
  phase.
- No other earlier-phase behavior changed.

---

## Update — Phases 7A–7C complete, mock seeder retired from the default path

Everything below supersedes the "offline mock-first" framing above. The real
CockroachDB Cloud REST API provider (`ccloud_api_provider.py`) is now the
**default** (`SHADOW_PROVIDER=ccloud_api` in `config.py` and `.env`/`.env.example`),
verified end to end on real clusters:

| Phase | Verified | Script |
| --- | --- | --- |
| 7A Provisioning | 14/14 PASS on real clusters (~5s provision) | `scripts/verify_phase7a_provisioning.py` |
| 7B Schema loading | 9/9 PASS — schemas/tables/columns/PKs/FKs/indexes/UNIQUE+CHECK recreated and compared against the snapshot | `scripts/verify_phase7b_schema_loading.py` |
| 7C Execution | 6/6 PASS — ALTER TABLE, CREATE INDEX, ADD/DROP COLUMN, missing-table error, syntax error, CHECK-constraint violation, each persisted as an `ExecutionResult` and re-read back from the database | `scripts/verify_phase7c_execution.py` |

**Mock seeder retired from the default lifecycle.** `ShadowClusterOrchestrator`'s
seed stage now calls the real, FK/CHECK-aware `ShadowSchemaLoader` (the Phase 7B
path) instead of `ShadowSeeder` (which inserted slow, per-row synthetic data and
omitted FK/CHECK constraints). Every shadow cluster in the default path is a
real, disposable CockroachDB Cloud cluster carrying the customer's *actual*
recreated structure — never a mock/offline database, and never synthetic rows.
`LifecycleReport.seed` now holds a `SchemaLoadReport` (schemas/tables/columns/
PKs/FKs/indexes/constraints created) instead of a row-count report.

`mock_provider.py`, `seeder.py`, and `scripts/verify_phase7_shadow_clusters.py`
are kept in the repo (unused by default) for optional offline demos where no
CockroachDB Cloud API key is available; they are not part of the default
`ccloud_api` path or its verification.
