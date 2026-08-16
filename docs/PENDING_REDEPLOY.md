# ⚠️ Uncommitted work waiting for the next redeploy

Written 2026-08-14. **Deliberately not committed and not deployed** — the
changes below are sitting in the working tree by request. Read this before the
next `git commit` / SAM deploy / Lightsail deploy so nothing is lost or
double-applied.

```
 M backend/app/shadow/seeder.py           <- needs a SAM redeploy to take effect
?? backend/scripts/reap_orphaned_secrets.py   <- runnable now, no deploy needed
```

---

## 1. Seeding is 21× faster — `backend/app/shadow/seeder.py` (MODIFIED)

### The problem, measured

Real stage timings pulled from the last 26 runs' `shadow_clusters.stage_timings`:

| stage | median | max |
|---|---|---|
| **seed_ms** | **11,234 ms** | **697,940 ms (11.6 min)** |
| ready_ms | 7,790 ms | 8,445 ms |
| migrate_ms | 4,285 ms | 16,269 ms |
| provision_ms | 2,825 ms | 595,167 ms |

Seeding was the slowest stage by median and had by far the worst tail.

### What was actually wrong

Benchmarked against a **real CockroachDB Cloud cluster** at the demo shape
(10 tables × 40 columns × 4,500 rows = 45,000 rows):

| version | time | rate |
|---|---|---|
| Original (sequential tables, 500-row `executemany`) | **72.10 s** | 624 rows/s |
| + multi-row VALUES + 4-way parallel | 49.65 s | 906 rows/s |
| + cached type family + 8-way parallel | 45.26 s | 994 rows/s |
| **+ server-side generation (shipped)** | **3.37 s** | **13,339 rows/s** |

Going from 4-way to 8-way concurrency bought almost nothing, which is what
identified the real bottleneck: the seed was **data-transfer bound**, not
round-trip bound. 45,000 × 40 values were being generated in Python and pushed
over the wire to a BASIC cluster. Generating them *inside* the database removes
the transfer entirely.

A separate profile found `_type_family()` was being called **per value** —
1.8 M calls, a measured 4.2 s — for an answer that cannot change within a
column.

### What changed

1. **Server-side generation (the 21× win).** `_load_rows` now builds
   `INSERT INTO t (...) SELECT <exprs> FROM generate_series(1, N) AS g`, so no
   row data crosses the wire. `_sql_value_expr` maps each type family to a SQL
   generator mirroring `_value_for`; `g` (the counter) backs primary keys so
   they stay unique.
   **Falls back to the old client-side path** on any failure (unmappable
   column, rejected expression), so a seed can degrade in speed but never in
   correctness.
2. **Multi-row VALUES** in the fallback path — one statement per batch instead
   of `executemany`, batch size derived per table from the 65535 bind-parameter
   protocol limit.
3. **Parallel tables** — a fixed worker pool (`_TABLE_CONCURRENCY = 8`), each
   worker holding one connection for its lifetime so `pool_pre_ping` and the
   `statement_timeout` SET cost once per worker, not once per table.
4. **Type family resolved once per column**, passed into `_value_for`.

### Correctness — verified, not assumed

A dedicated check seeded every type family and all three primary-key shapes
against a real cluster:

```
t_int_pk:    rows=300 distinct_pk=300 OK   (STRING/TIMESTAMPTZ/BOOL/FLOAT8/DATE/JSONB/BYTES all distinct, 0 nulls)
t_uuid_pk:   rows=300 distinct_pk=300 OK
t_string_pk: rows=300 distinct_pk=300 OK
RESULT: PASS
```

JSONB is `'{}'` for every row — unchanged from the old behaviour, where
`_value_for` also returned `"{}"`. Not a regression.

### ⚠️ Deploy requirement

`app/shadow/seeder.py` lives under `backend/app/`, and
`package_lambda_for_sam.py` copies that whole tree into all 8 Lambda packages.
**This change does nothing in production until a SAM build + deploy runs**
(~8 min build + ~15 min deploy). Run it from Bash, not PowerShell — see
`docs/AWS_DEPLOYMENT_PLAN.md` §0.2 for the exact commands and the warning that
a bare `sam deploy` blanks `DatabaseUrl`/`CCloudApiSecret`.

The Lightsail control plane does **not** need redeploying for this.

---

## 2. Secrets Manager cost — `backend/scripts/reap_orphaned_secrets.py` (NEW)

### Already applied to AWS — no deploy needed

This one is **done**, because it is an operational cleanup rather than a code
deploy:

| | before | after |
|---|---|---|
| Active secrets | 128 | **18** |
| Monthly cost | **$51.20** | **$7.20** |

110 secrets were scheduled for deletion. **Reversible until 2026-08-21** —
deletion used the default 7-day recovery window, not
`ForceDeleteWithoutRecovery`:

```
aws secretsmanager restore-secret --secret-id <name> --region us-east-1
```

API health was re-checked immediately afterward: healthy DB, healthy AWS,
`sfn_ready: true`.

### Why it had grown

Every run given an explicit `database_url` gets its own
`migration-oracle/connections/{run_id}` secret, and **nothing ever deleted
them**. `CleanupFunction` only removes `migration-oracle/shadow*`, and its IAM
policy does not even permit deleting anything else. 105 had accumulated since
2026-07-22. Runs that resolve their connection through a *workspace* reuse one
shared secret and were never the problem.

What was deleted: 73 for runs that no longer exist, 11 shadow secrets whose
cluster was already destroyed, 17 for completed/failed runs, 5 for runs
abandoned >7 days, 4 shadow secrets for missing runs.
What was kept: the 5 persistent workspace connections, 10 still referenced by
live runs, 1 updated within 24 h, and the 2 standalone credentials.

Note: the status set was **verified against the live database, not guessed** —
`migration_runs.status` is `completed` / `pending` / `failed` /
`awaiting_approval` / `running`. There is no `succeeded`, and an early version
of the script that assumed one under-deleted by 24 secrets.

### 🔴 The leak is stopped for now, but not fixed permanently

The script is a one-off. **Without one of the follow-ups below, secrets start
accumulating again at roughly $0.40 per direct-`database_url` run per month.**

Options, cheapest effort first:

1. **Schedule the script** (no code deploy): run
   `python backend/scripts/reap_orphaned_secrets.py --apply` weekly. Safe to
   re-run; it is idempotent and conservative.
2. **Wire it into the control plane's background sweep** — `app/main.py`'s
   `_shadow_sweep_loop` already runs every 30 s and the Lightsail task has full
   Secrets Manager access. Needs only a Lightsail redeploy, no SAM.
3. **Stop creating per-run secrets at all** (the real fix). A run whose
   connection came from a workspace already reuses that secret; the per-run
   copy only exists for the direct-`database_url` path. Either point those at a
   workspace secret too, or store the URL Fernet-encrypted in CockroachDB — the
   app already does exactly that for Slack and GitHub tokens. This would take
   Secrets Manager to ~$2/month permanently, but it touches the Lambda read
   path (`discover_schema` resolves by ARN) and so needs a SAM redeploy plus
   real testing.

---

## Suggested order for the next session

1. Commit both files.
2. SAM build + deploy (Bash) so the seeder change reaches the Lambdas.
3. Run one real shadow migration and confirm `seed_ms` drops from ~11 s to
   ~1–3 s in `shadow_clusters.stage_timings`.
4. Pick a follow-up from §2 so the secret leak does not restart.
