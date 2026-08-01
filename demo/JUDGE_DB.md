# Judge RO database URL (local only — do not commit secrets)

Run from `backend/`:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_judge_demo_db.py
```

Copy the printed `JUDGE_RO_DATABASE_URL=...` into Current Migration → Attach database.

Password file (gitignored): `.judge_ro_password` at repo root.

See [SQL_PLAYBOOK.md](SQL_PLAYBOOK.md) for SQL A / B / C.
