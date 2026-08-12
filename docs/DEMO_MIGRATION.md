# Demo migration — the exact run to click through for judging/recording

One migration statement, against one real-shaped seeded table, chosen to
produce a **real backfill** (not a no-op) so the shadow-execution dashboard
has something visually interesting to show. Copy-paste-runnable start to
finish by someone who has never used the app before.

Target data: `calcom_bookings` from [`test-data/saas_seed/`](../test-data/saas_seed/)
(see Block 4 in [`AUG18_FINAL_PUSH_PLAN.md`](AUG18_FINAL_PUSH_PLAN.md) — this
table is already loaded, 4,500 rows, on the `demo_saas_seed` database on the
same CockroachDB Cloud cluster referenced by this repo's `.env`).

## The migration statement

```sql
ALTER TABLE calcom_bookings
  ADD COLUMN "duration_minutes" INT4
  AS ((extract(epoch FROM ("end_time" - "start_time")) / 60)::INT4) STORED;
```

(Note the explicit `::INT4` cast on the whole expression — CockroachDB's
`extract(epoch FROM ...)` division returns `float`, and a computed column
typed `INT4` requires the stored expression to actually type as `INT4`, not
just be castable. Verified against the real seeded table 2026-08-11 — see
below.)

Why this one, not a plain `ADD COLUMN ... DEFAULT`: a computed `STORED`
column forces CockroachDB to evaluate the expression against every existing
row immediately — a genuine backfill over 4,500 rows derived from two
existing timestamp columns, not an instant metadata-only change. That's
what makes the shadow-execution metrics (backfill duration, rows affected)
non-trivial to look at on camera, versus a constant-default column which
CockroachDB applies without touching existing rows at all.

## Prerequisites

- Local dev running: `python scripts/dev.py restart` (backend), then in a
  second terminal `cd frontend/oracle && npm run dev` (frontend). Confirm
  `GET http://127.0.0.1:8003/health` (or whatever port `dev.py` printed)
  returns `sfn_ready: true`.
- The read-only demo credential below already exists on the cluster
  (created and verified 2026-08-11 — `SELECT` works, `INSERT`/`CREATE TABLE`
  are rejected; the schema's default `PUBLIC` `CREATE` grant was also
  revoked after the app's own read-only-credential check caught it —
  CockroachDB/Postgres both grant `CREATE` on the `public` schema to every
  user by default via the `PUBLIC` pseudo-role, so a plain `GRANT SELECT`
  alone is not actually read-only until that default is revoked too):

  ```text
  postgresql://migration_oracle_demo_ro:DemoSeedRO_2026Aug@migration-oracle-30746.j77.aws-us-east-1.cockroachlabs.cloud:26257/demo_saas_seed?sslmode=verify-full
  ```

  (Same cluster as the app's own control-plane `migration_oracle` database,
  different database — this connection can only ever `SELECT` from
  `demo_saas_seed`, never touch the app's own data.)

## Click path

1. Open `http://localhost:3000/dashboard` → set an **owner identity** in
   the sidebar if not already set (any string, e.g. `demo`).
2. Sidebar workspace switcher → either create a fresh workspace or use an
   existing one — doesn't matter which, this doesn't depend on workspace
   history.
3. Go to **Current Migration** (`/dashboard/migrations/current`).
4. **Section "1. Connect your database"** → paste the read-only connection
   string above into the database URL field. (Do *not* use the "Use demo
   database" button — that connects the app's own built-in demo dataset,
   not this seeded one.)
5. **Section "2. Your migration SQL"** → paste the `ALTER TABLE` statement
   above into the SQL textarea.
6. Click **"Create run & discover schema"**. Wait for schema discovery to
   finish — the sidebar connection indicator should now read "connected"
   immediately (this is the Block 1 fix: it reflects the workspace's own
   persisted connection, not just this run).
7. **Section "3. Prediction"** → click **"Run prediction"**. Wait for the
   assessment (policy + Bedrock + retrieved memories).
8. Review the assessment, then click **"Approve — run shadow test"**.
9. **Shadow cluster** section → click **"Start shadow test"** (or it may
   auto-start depending on policy) → watch provision → seed → migrate →
   collect metrics → teardown. The backfill on `calcom_bookings.duration_minutes`
   is what's actually executing here, against a disposable clone, not
   `demo_saas_seed` itself.
10. Confirm the grade + memory panel populates on the run once shadow
    execution finishes; open "Why this confidence" / Agent Memory to see
    the retrieved-memory trail.

## Verify it worked

```sql
-- Run this against demo_saas_seed directly (not through the app) to
-- confirm the shadow cluster's migration would have produced correct data
-- if it had run against the real table:
SELECT "id", "start_time", "end_time",
       ((extract(epoch FROM ("end_time" - "start_time")) / 60)::INT4) AS expected_minutes
FROM calcom_bookings
LIMIT 5;
```

All 4,500 rows have `end_time` strictly after `start_time` (15-240 minutes
later, by construction in the generator), so `expected_minutes` is always a
sane positive number — no negative-duration rows to explain away on camera.

Compare `expected_minutes` against whatever the shadow cluster's own
post-migration metrics report for `duration_minutes` on the same rows —
they should match, since the shadow cluster is seeded from the same
schema/data snapshot at the time `discoverSchema` ran.

## If something looks broken

This doc was write-once against a specific, already-verified environment
state (seed data loaded and read-only user confirmed working — see
Block 4's README). If the click path itself breaks when actually run
end-to-end, that's exactly what Block 13 (full dry run) exists to catch
and fix before recording — this doc describes the intended path, not a
guarantee nothing regresses between now and Aug 18.
