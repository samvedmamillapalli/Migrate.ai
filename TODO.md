# Performance Optimization Checklist — Migration Oracle

## Audit 1 (completed): Engine reuse + concurrent row counts
- [x] `schema_snapshot.py`: `capture_shadow_snapshot` accepts optional `engine`; `_fill_exact_row_counts` parallelized with bounded `asyncio.gather` (limit 4)
- [x] `migration_runner.py`: single engine created, passed to all 3 `capture_shadow_snapshot` calls (was 3 separate engines)
- [x] `schema_loader.py`: `ShadowSchemaLoader.load` accepts optional `engine`
- [x] `seeder.py`: `seed` + `seed_rows_only` accept optional `engine` with `owns_engine` ownership pattern
- [x] `load_schema.py`: single engine shared between loader + seeder, disposed once
- [x] `grading_pipeline_service.py`: removed 2 redundant `load_children=True` reloads
- [x] Verified: 235 tests pass, app starts

## Audit 2 (completed): Post-migration parallelization + combine DB writes
- [x] `migration_runner.py`: parallelized 3 independent post-migration read-only measurements
  - `_measure_storage_mb`, `snapshot_schema_jobs`, `capture_shadow_snapshot` now run concurrently via `asyncio.gather` on separate pooled connections
  - Added `_post_migration_measure` helper with per-operation failure isolation
  - Benchmark: 1.15x speedup on post-migration measurement (~125ms saved per migration)
- [x] `shadow_cluster_service.py`: added `merge_timings_and_snapshot` — writes stage timings + schema/row snapshots in ONE transaction
- [x] `execute_migration.py`: replaced `merge_timings` + conditional `set_schema_snapshot` (2 transactions / 8 DB round-trips) with single `merge_timings_and_snapshot` call
- [x] Verified: 235 tests pass, app starts, syntax/import clean

## Deliberately NOT implemented (with rationale)
- `_CHANGEFEED_DRAIN_SECONDS` (2s) reduction — risks losing changefeed events (enrichment); not safe without product decision
- Parallel DDL in `schema_loader.py` — CockroachDB schema-change jobs conflict
- `_POLL_INTERVAL_SECONDS` in `job_progress.py` — UX enrichment, not critical path
- Bedrock/Embedding client caching on LambdaRuntime — marginal, stale-config risk
- Removing `session.refresh` in `execution_service.py` — needed to re-sync after commit

## Audit 3 (2026-08-11, Block 8 of AUG18_FINAL_PUSH_PLAN — investigated, NOT implemented)
Cold-start audit on the 7 shadow-orchestration Lambdas, via real CloudWatch
Logs Insights data (`REPORT ... Init Duration` lines), last ~30 invocations
per function, not simulated:

| Function | Memory | Package size | Cold starts / invocations logged | Init Duration (min/avg/max) |
|---|---|---|---|---|
| discover-schema | 512MB | 37.6MB | 43/44 | 1480 / 3180 / 3773 ms |
| provision-shadow-cluster | 1024MB | 37.6MB | 38/38 | 2637 / 3378 / 3809 ms |
| load-schema | 1024MB | 37.6MB | 30/31 | 2567 / 3361 / 3895 ms |
| execute-migration | 1024MB | 37.6MB | 29/30 | 2831 / 3372 / 3786 ms |
| collect-metrics | 512MB | 37.6MB | 27/28 | 2590 / 3435 / 3939 ms |
| persist-results | 1024MB | 37.6MB | 27/28 | 2596 / 3381 / 3881 ms |
| cleanup | 512MB | 37.6MB | 35/34 (some straddle the query window) | 1277 / 3200 / 4221 ms |

**Finding:** every one of the 7 Lambdas is cold on essentially every
invocation (27-43 of ~28-44 logged calls) — expected, since each is called
once per state-machine execution and executions are spaced out enough that
containers never stay warm between demo runs. All 7 ship the same ~37.6MB
package (shared dependency bundle — boto3, SQLAlchemy, psycopg, pydantic,
etc.), averaging ~3.2-3.4s Init Duration regardless of the 512 vs 1024MB
split. Stacked across all 7 SFN states, that's roughly 22-24s of pure
Lambda init overhead inside a ~90-120s total shadow wall-clock (per
`docs/DEMO_OPS.md`'s measured timings) — a real, double-digit percentage of
what a judge watches during the live demo.

**Recommendation (not implemented this session):** bump the three
512MB functions (`discover-schema`, `collect-metrics`, `cleanup`) to
1024MB — Lambda's init-phase CPU scales with allocated memory, so this
is normally close to a free win for import-heavy cold starts, and the
1024MB functions in this same data don't show meaningfully faster init
than the 512MB ones, meaning there's real headroom left on the table for
those three specifically. Bigger, riskier follow-up (not attempted here):
splitting the shared ~37.6MB bundle so each Lambda only imports what its
own handler needs — `provision_shadow.py` almost certainly doesn't need
the same import surface as `execute_migration.py`, but confirming that
needs a real per-function import audit, not a guess.

**Why not implemented:** this is a SAM template + real AWS redeploy
(memory bump is a one-line template change, but this repo's own notes
flag that shadow Lambda changes "only take effect after a SAM redeploy"
and the deploy scripts are finicky) — a real, not-easily-reversible
infra change to make blind, under time pressure, for a [NICE]-tier block,
without the human explicitly asking for the memory bump specifically.
Documented with real numbers instead so the human can make the actual
call and redeploy directly rather than have it done silently.
