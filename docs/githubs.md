# Open-source migration corpora (for graded memory / retrieval)

Curated sources for pulling real-world DDL, documented incidents, and schema
evolution histories into Migration Oracle's shared corpus
(`__migration_oracle_corpus__`).

**Seeded in this repo today:** one Temporal visibility index migration (see
`backend/data/open_source_corpus/temporal_fix_root_workflow_info.json`), loaded
automatically on API startup and via `python scripts/seed_open_source_corpus.py`.

---

## Tier 1 — best fit (plain SQL or trivial conversion)

### Temporal (primary — already seeded)
- **Repo:** https://github.com/temporalio/temporal
- **License:** MIT
- **Migrations:** https://github.com/temporalio/temporal/tree/main/schema/postgresql/v12
- **Incident:** https://github.com/temporalio/temporal/issues/6273 — blocking
  `CREATE INDEX` on busy `executions_visibility` (~120GB) failed in prod;
  fix uses `CREATE INDEX CONCURRENTLY`
- **Also:** https://github.com/temporalio/temporal/issues/10358 — generated
  column + GIN index migration caused long exclusive locks (~1h on 35M rows)
- **Why:** Plain SQL versioned files; real production pain around hot-table indexes

### Apache Superset
- **Repo:** https://github.com/apache/superset
- **License:** Apache 2.0
- **Migrations:** https://github.com/apache/superset/tree/master/superset/migrations/versions
- **Why:** Alembic Python but 1:1 SQL; high volume of additive DDL

### Apache Airflow
- **Repo:** https://github.com/apache/airflow
- **License:** Apache 2.0
- **Migrations:** https://github.com/apache/airflow/tree/main/airflow-core/src/airflow/migrations/versions
- **Why:** Clean upgrade/downgrade pairs; good rollback examples

### GitLab (Rails, but SQL in structure.sql snapshots)
- **Repo:** https://gitlab.com/gitlab-org/gitlab
- **License:** MIT
- **Migrations:** https://gitlab.com/gitlab-org/gitlab/-/tree/master/db/migrate
- **Why:** Massive real-world corpus; many index/backfill patterns (heavier to parse)

### PostGIS / pgRouting
- **PostGIS:** https://github.com/postgis/postgis/tree/master/postgis
- **Why:** Extension DDL on PostgreSQL; index-heavy geospatial patterns

---

## Tier 2 — research datasets (schema evolution, not always runnable DDL)

### Schema Evolution Datasets (DAINTINESS)
- **Repo:** https://github.com/DAINTINESS-Group/Schema_Evolution_Datasets
- **Paper:** ICDE 2021 schema biography profiles
- **Why:** Versioned schema histories across FOSS projects; good for metadata mining

### SchemaPile (Amsterdam)
- **Repo:** https://github.com/amsterdata/schemapile
- **Data:** https://github.com/amsterdata/schemapile/blob/main/sqlfiles-and-licenses.md
- **Why:** Large collection of relational schemas + licenses; pipeline for collection

### schema-evolution-samples
- **Repo:** https://github.com/viniciusccarvalho/schema-evolution-samples
- **Why:** Small Avro/codec evolution examples; useful for compatibility narratives

### Schema evolution bibliography
- **Site:** http://www.cs.uoi.gr/~pvassil/projects/schemaBiographies/index.html

---

## Tier 3 — messier (Django/Rails ORM migrations)

### Zulip
- **Repo:** https://github.com/zulip/zulip
- **Migrations:** https://github.com/zulip/zulip/tree/main/zerver/migrations
- **License:** Apache 2.0

### NetBox
- **Repo:** https://github.com/netbox-community/netbox
- **Migrations:** https://github.com/netbox-community/netbox/tree/develop/netbox/dcim/migrations
- **License:** Apache 2.0

---

## Similar incident write-ups (no migration files, good lessons)

- **Stripe:** https://stripe.com/blog/online-migrations (online MySQL migrations pattern)
- **Braintree:** https://github.com/braintree/ps-grid (Postgres online schema change tooling)
- **pganalyze:** blocking DDL on large tables — search "postgres create index concurrently production"

---

## How we use these in Migration Oracle

1. Pick one migration + documented outcome (issue/blog post).
2. Store under `backend/data/open_source_corpus/*.json`.
3. `ensure_open_source_corpus()` seeds `migration_memories` with Titan embedding.
4. Hybrid retrieval matches test migrations like `CREATE INDEX idx_users_email …`
   to the Temporal hot-table index lesson during `/predict`.

Add more JSON files to grow the corpus; re-run:
`python backend/scripts/seed_open_source_corpus.py --verify-retrieval`
