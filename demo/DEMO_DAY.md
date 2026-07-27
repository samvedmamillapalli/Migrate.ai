# Demo day — baseline freeze & roles

**Status:** Phase 0 complete when doctor + `/health` are green on two machines.

## Roles

| Role | Owner | Responsibility |
| --- | --- | --- |
| Demo operator | | Browser console; paste SQL A/B; click path |
| Narrator | | Talk track; never touch mouse during live run |
| AWS / Cockroach watcher | | SFN + CloudWatch + Cockroach Cloud tabs (secondary) |
| Backup laptop | | Same `.env`; doctor green; SQL clipboard ready |

## Machine checklist (each laptop)

1. Repo-root `.env` present (never commit).
2. `python scripts/dev.py setup`
3. `python scripts/dev.py doctor` → **RESULT: ready**
4. `python scripts/dev.py restart` (API)
5. `GET http://127.0.0.1:8000/health` → `sfn_ready: true`, `shadow_provider: ccloud_api`, `bedrock_configured: true`
6. `cd frontend/oracle && npm run dev`
7. `frontend/oracle/apps/web/.env.local`:

```text
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Do **not** set `NEXT_PUBLIC_ENABLE_DEBUG_TOOLS=true` on the public/demo machine.

8. Overview → System Health shows **Ready** for API, Shadow, Predictions.
9. Set **owner identity** once (e.g. `judge-demo`) in Settings / sidebar.

## Required env keys (demo)

`DATABASE_URL`, AWS credentials, Bedrock model IDs, `MIGRATION_WORKFLOW_ARN`, `RUN_ARTIFACTS_BUCKET`, `CCLOUD_API_SECRET`, `SHADOW_PROVIDER=ccloud_api`, `CORS_ORIGINS` (include public frontend origin when deployed).

## Exit

- [x] Doctor ready + `/health` green (this machine, 2026-07-25)
- [ ] Second teammate confirms doctor + health (human)
- [x] Demo pack under `demo/` (roles, SQL, talk, chaos, deploy, submit)
- [x] Owner identity for proofs: `judge-demo`
