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
