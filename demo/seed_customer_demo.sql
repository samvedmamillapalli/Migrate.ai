-- Demo "production" database for the Shadow Execution comparison view.
--
-- Run this against the CockroachDB database you attach on Current Migration
-- (the one behind `connection_secret_arn`). It creates the five tables the
-- shadow page's Production Cluster card renders, sized so the card shows
-- non-trivial real numbers:
--
--   users       5 columns  2 indexes  (PK + email lookup)
--   orders      6 columns  2 indexes  (PK + user_id lookup)
--   payments    4 columns  1 index    (PK only)
--   products    5 columns  1 index    (PK only)
--   categories  3 columns  1 index    (PK only)
--   ----------------------------------------------------
--   5 tables               7 indexes
--
-- Index counts include the primary-key index, which is what
-- app.schema_analysis.inspector reports and what the card totals.
--
-- Idempotent: safe to re-run. Row counts are reset each time so repeated demo
-- runs always start from the same numbers.
--
-- IMPORTANT — run this against the `customer_demo` database as an ADMIN user,
-- not as the read-only role the app discovers with. Discovery connects as
-- `judge_ro`, which has no CREATE privilege; the GRANT block at the end is
-- what makes these new tables visible to it. Without that grant the app will
-- discover an empty schema.
--
-- Usage (cockroach sql):
--   cockroach sql --url "postgresql://<admin-user>:<pw>@<host>:26257/customer_demo?sslmode=verify-full" \
--     -f demo/seed_customer_demo.sql
--
-- Usage (psql):
--   psql "postgresql://<admin-user>:<pw>@<host>:26257/customer_demo?sslmode=verify-full" \
--     -f demo/seed_customer_demo.sql
--
-- NOTE: CockroachDB commits DDL per statement — an interrupted run leaves the
-- tables it already created. Re-running finishes the job.

-- ---------------------------------------------------------------- categories
CREATE TABLE IF NOT EXISTS categories (
    id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name STRING NOT NULL,
    slug STRING NOT NULL
);

-- ------------------------------------------------------------------ products
CREATE TABLE IF NOT EXISTS products (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id UUID NOT NULL,
    name        STRING NOT NULL,
    price_cents INT8 NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- --------------------------------------------------------------------- users
CREATE TABLE IF NOT EXISTS users (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email        STRING NOT NULL,
    display_name STRING NOT NULL,
    is_active    BOOL NOT NULL DEFAULT true,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS users_email_idx ON users (email);

-- -------------------------------------------------------------------- orders
CREATE TABLE IF NOT EXISTS orders (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL,
    product_id   UUID NOT NULL,
    quantity     INT8 NOT NULL DEFAULT 1,
    total_cents  INT8 NOT NULL,
    placed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS orders_user_id_idx ON orders (user_id);

-- ------------------------------------------------------------------ payments
CREATE TABLE IF NOT EXISTS payments (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id   UUID NOT NULL,
    status     STRING NOT NULL DEFAULT 'captured',
    paid_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------ row data
-- Cleared first so re-running does not stack duplicate demo rows on top of the
-- previous run's. Child-to-parent order avoids tripping any FK you add later.
DELETE FROM payments   WHERE true;
DELETE FROM orders     WHERE true;
DELETE FROM products   WHERE true;
DELETE FROM users      WHERE true;
DELETE FROM categories WHERE true;

INSERT INTO categories (name, slug)
SELECT 'Category ' || i::STRING, 'category-' || i::STRING
FROM generate_series(1, 8) AS g(i);

INSERT INTO products (category_id, name, price_cents)
SELECT
    (SELECT id FROM categories ORDER BY random() LIMIT 1),
    'Product ' || i::STRING,
    (500 + (i * 137) % 9500)::INT8
FROM generate_series(1, 240) AS g(i);

INSERT INTO users (email, display_name, is_active)
SELECT
    'user' || i::STRING || '@example.com',
    'Demo User ' || i::STRING,
    (i % 11) <> 0
FROM generate_series(1, 1200) AS g(i);

INSERT INTO orders (user_id, product_id, quantity, total_cents)
SELECT
    (SELECT id FROM users    ORDER BY random() LIMIT 1),
    (SELECT id FROM products ORDER BY random() LIMIT 1),
    (1 + i % 4)::INT8,
    (1200 + (i * 313) % 40000)::INT8
FROM generate_series(1, 3000) AS g(i);

INSERT INTO payments (order_id, status)
SELECT
    o.id,
    CASE WHEN random() < 0.06 THEN 'refunded' ELSE 'captured' END
FROM orders AS o;

-- Refresh the statistics the Production Cluster card reads for ROWS. Without
-- this the estimates lag behind the inserts above by a few minutes.
ANALYZE categories;
ANALYZE products;
ANALYZE users;
ANALYZE orders;
ANALYZE payments;

-- ------------------------------------------------------------------- grants
-- Schema discovery connects as a read-only role, so it can only see tables it
-- has SELECT on. Without this the app discovers an empty schema and the
-- Production Cluster card renders nothing.
--
-- Change `judge_ro` here if your read-only role is named differently. If the
-- role does not exist, create it first (see backend/scripts/prepare_judge_demo_db.py).
GRANT SELECT ON TABLE categories TO judge_ro;
GRANT SELECT ON TABLE products   TO judge_ro;
GRANT SELECT ON TABLE users      TO judge_ro;
GRANT SELECT ON TABLE orders     TO judge_ro;
GRANT SELECT ON TABLE payments   TO judge_ro;

-- Sanity check — what the Production Cluster card should show.
SELECT 'categories' AS table_name, count(*) AS rows FROM categories
UNION ALL SELECT 'products',   count(*) FROM products
UNION ALL SELECT 'users',      count(*) FROM users
UNION ALL SELECT 'orders',     count(*) FROM orders
UNION ALL SELECT 'payments',   count(*) FROM payments
ORDER BY table_name;

-- ---------------------------------------------------------------------------
-- Companion migration SQL — paste this as the migration on Current Migration
-- to reproduce the Changes Detected strip (one added table, one modified
-- column, four untouched tables):
--
--   CREATE TABLE user_sessions (
--       id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
--       user_id    UUID NOT NULL,
--       token      STRING NOT NULL,
--       expires_at TIMESTAMPTZ NOT NULL
--   );
--   ALTER TABLE users ALTER COLUMN email DROP NOT NULL;
--
-- The nullability flip is what the diff classifies `users.email` as "changed"
-- on — see app.shadow.schema_snapshot._column_signature, which compares
-- (data_type, is_nullable).
