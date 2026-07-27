# Demo SQL playbook — learn loop

Use owner identity `judge-demo`. Attach the RO URL from:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\prepare_judge_demo_db.py
```

That writes `.judge_ro_database_url` (gitignored). Paste into Current Migration → Attach database.

Timings ([docs/DEMO_OPS.md](../docs/DEMO_OPS.md)): discover ~20s · predict ~60s · shadow ~90–120s.

Automated regression uses the same SQL A as `scripts/judge_path1_live.py`.

---

## SQL A — first graded run (additive column)

Talk: “Read-only discovery never writes production. We’ll verify on a disposable shadow cluster.”

```sql
ALTER TABLE customers ADD COLUMN status STRING NOT NULL DEFAULT 'active';
```

**Path:** Create → Attach RO URL → Discover → Predict → Proceed → Start shadow → Outcome + memory ready.

---

## SQL B — second run (same class, different wording)

Talk: “Same class of change. Learning should retrieve the graded run via Distributed Vector Indexing.”

```sql
-- Expand customers with an account status for billing eligibility
ALTER TABLE customers ADD COLUMN account_status STRING NOT NULL DEFAULT 'active';
```

**Expected:** Learning shows similar runs; at least one graded hit from SQL A.

---

## SQL C — backup index path

```sql
CREATE INDEX IF NOT EXISTS idx_customers_region ON public.customers (region);
```

Or switch to a fresh owner identity and re-run A→B.

---

## Clipboard checklist

- [ ] Owner = `judge-demo`
- [ ] Health green (`sfn_ready`)
- [ ] RO URL attached + Discover succeeded
- [ ] SQL A / B on clipboard
