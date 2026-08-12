# Test dataset: 10 real-world SaaS table schemas, synthetic data

Ten tables, each a real schema pulled from a well-known open-source
project (see `00_schema_catalog.md` for source citations and full column
lists), seeded with synthetic-but-type-correct data — 20-50 columns/table,
2,000-8,000 rows/table (all under the 10,000-row cap), 41,500 rows total.
Together they read as one plausible multi-tenant SaaS customer's Postgres
database: forum, issue tracker, CRM, scheduling, billing, e-commerce,
support inbox, CMS, and analytics tables side by side.

This is the kind of wide, denormalized, real-shaped target database
Migration Oracle's demo run points at — richer than a bare handful of toy
columns, but still fast to load and cheap in Request Units.

## Files, in order

1. **`00_schema_catalog.md`** — the source doc: which real project/file each
   table's column list came from, and why (Block 2's deliverable).
2. **`generate_seed_sql.py`** — the generator (Block 3's deliverable).
   Stdlib-only Python, no `pip install` needed; deterministic (fixed RNG
   seed) so re-running it reproduces the same output byte-for-byte.
3. **`01_wp_posts.sql` .. `10_lago_invoices.sql`** — one file per table,
   each a self-contained `CREATE TABLE` + batched `INSERT` script (500
   rows/statement), copy-paste-ready for the CockroachDB Cloud SQL Shell.

## Judgment call: no `IMPORT INTO`, so no fallback file needed

The block asked for "a fallback path if any table hits CockroachDB Cloud
IMPORT restrictions (inline batched INSERTs, same approach as the existing
`03_fallback_inline_inserts` file)." Since this data is synthetic (not a
real external CSV to fetch), the **primary path already is** the fallback
approach from the IRS dataset — plain batched `INSERT`s, no `IMPORT INTO`,
no external URL, no userfile upload. That means every one of these 10
files already works on every CockroachDB Cloud tier with zero fetch/import
prerequisites, so there's no separate `02_fallback_*.sql` file to add —
the "restriction" the fallback exists to route around doesn't apply here.

## Steps (CockroachDB Cloud Console)

1. Cluster page → **SQL Shell**, on whatever database you want this seeded
   into. (Verification below used a separate `demo_saas_seed` database on
   the same cluster the app's control-plane `migration_oracle` database
   lives on — same cluster, different database, so the app's own
   workspace/run data is never touched by this seed.)
2. Paste and run each `NN_<table>.sql` file, in any order (tables are
   independent — no cross-table foreign keys enforced, so load order
   doesn't matter).
3. Verify:
   ```sql
   SELECT count(*) FROM wp_posts;               -- expect 4000
   SELECT count(*) FROM discourse_topics;        -- expect 3500
   SELECT count(*) FROM gitea_issues;            -- expect 2500
   SELECT count(*) FROM chatwoot_conversations;  -- expect 3000
   SELECT count(*) FROM calcom_bookings;         -- expect 4500
   SELECT count(*) FROM odoo_res_partner;        -- expect 5000
   SELECT count(*) FROM medusa_products;         -- expect 2000
   SELECT count(*) FROM posthog_events;          -- expect 8000
   SELECT count(*) FROM redmine_issues;          -- expect 3000
   SELECT count(*) FROM lago_invoices;           -- expect 6000
   ```

## Verified 2026-08-11

All 10 files were run against the real cluster in `.env`'s `DATABASE_URL`
(`migration-oracle-30746...cockroachlabs.cloud`), against a fresh
`demo_saas_seed` database created for this purpose — zero errors, no
reserved-word collisions, every row count matched exactly:

```
wp_posts                4000
discourse_topics        3500
gitea_issues            2500
chatwoot_conversations  3000
calcom_bookings         4500
odoo_res_partner        5000
medusa_products         2000
posthog_events          8000
redmine_issues          3000
lago_invoices           6000
```

## Notes

- Every column identifier is double-quoted in the generated SQL (matching
  `test-data/irs_soi_zip_income`'s convention), which sidesteps reserved-word
  collisions entirely — several source schemas use words like `index`
  (`gitea_issues`) that would otherwise need escaping.
- Primary keys match each table's real natural grain (surrogate integer,
  UUID, or prefixed text id — whichever the real upstream project actually
  uses), per `00_schema_catalog.md`; no synthetic surrogate key was added
  to any table that doesn't already have one in its real schema.
- Regenerate with `python test-data/saas_seed/generate_seed_sql.py` from
  the repo root — no arguments, no external services, overwrites the 10
  `NN_*.sql` files in place.
