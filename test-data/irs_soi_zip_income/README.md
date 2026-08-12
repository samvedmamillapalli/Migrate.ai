# Test dataset: IRS SOI Individual Income Tax, ZIP Code data (2022)

Real, public IRS data — not synthetic. One row per (state, ZIP code, income
bracket), with ~160 columns of tax return counts and dollar amounts (returns
filed, AGI, wages, dividends, deductions, credits, etc). 165 columns total,
166,131 rows, ~216 MB as CSV.

Source: https://www.irs.gov/statistics/soi-tax-stats-individual-income-tax-statistics-2022-zip-code-data-soi
Record layout / field definitions: https://www.irs.gov/pub/irs-soi/22zpdoc.doc
Raw file used here: https://www.irs.gov/pub/irs-soi/22zpallagi.csv (fetched and
verified 2026-08-08 — 165 columns, no blank fields, plain CSV with header row)

This is real production-style data of the kind government, fintech, and
healthcare-adjacent teams migrate — wide, denormalized, natural composite
key, mixed count/amount columns — a reasonable stand-in for the kind of
target table teams running schema migrations actually have.

## Files, in order of preference

1. **`01_create_and_import.sql`** — primary path. `CREATE TABLE` (165
   columns) + `IMPORT INTO ... CSV DATA ('https://www.irs.gov/...')`. Your
   CockroachDB cluster fetches the file directly from irs.gov server-side —
   nothing large passes through your browser. Loads the full 166,131 rows.

2. **`02_fallback_userfile_import.sql`** — use only if `01` fails with a
   network/fetch error (some cluster configs block outbound HTTP to
   arbitrary hosts). Uploads the same CSV to CockroachDB's own per-cluster
   `userfile` storage via the `cockroach` CLI, then imports from there.
   Still the full, real 166,131-row dataset.

3. **`03_fallback_inline_inserts_TX.sql`** — use only if `IMPORT INTO` isn't
   available at all on your cluster/plan. No import, no external URL — just
   literal `INSERT` statements built from the same real IRS file, filtered
   to Texas (9,714 rows: every ZIP code x every income bracket for TX),
   batched 500 rows/statement. Real data, just a smaller slice, sized to be
   safely pasteable into the SQL Shell.

## Steps (CockroachDB Cloud Console)

1. Cluster page → **SQL Shell** (or **SQL Users → Connect** → open the web
   SQL shell for your database).
2. Paste the whole contents of `01_create_and_import.sql` and run it.
3. Wait for the `IMPORT INTO` job to finish — the shell will show a job ID
   and block until it completes (~a few minutes; billed in Request Units,
   comfortably inside the monthly free RU allowance on Basic tier).
4. Verify:
   ```sql
   SELECT count(*) FROM irs_zip_income;          -- expect 166131
   SELECT * FROM irs_zip_income LIMIT 5;
   ```
5. If step 2/3 errors out on the fetch, fall back to file `02`, then `03`.

## Notes

- Primary key is the file's natural grain: `(statefips, zipcode, agi_stub)`
  — no synthetic surrogate key, matching how this data is actually keyed.
- All ~160 measure columns are `DECIMAL(20,4)` because the source file
  formats every count/amount with 4 decimal places (e.g. `659530.0000`).
- Swap the year in the URL (`22zpallagi.csv` → `21zpallagi.csv`,
  `20zpallagi.csv`, ...) if you want a different year's file; the schema is
  the same back through several tax years (verify column count if you go
  further back, since the IRS has occasionally added/removed fields).
