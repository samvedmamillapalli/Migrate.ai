# Public deploy checklist (hackathon)

Follow [docs/HOSTING.md](../docs/HOSTING.md). Goal: incognito create → discover → predict works.

## API

1. Build: `docker build -t migration-oracle-api .` (requires Docker Desktop running)
2. Or deploy FastAPI to Railway/Fly/ECS with the same env as local `.env`
3. Set env: `ENVIRONMENT=production`, `DATABASE_URL`, AWS + Bedrock, `MIGRATION_WORKFLOW_ARN`, `RUN_ARTIFACTS_BUCKET`, `CCLOUD_API_SECRET`, `SHADOW_PROVIDER=ccloud_api`
4. Hackathon gate: prefer `AUTH_ENABLED=false` + optional `DEMO_API_KEY` over forcing signup
5. `CORS_ORIGINS=https://YOUR_FRONTEND_ORIGIN,http://localhost:3000`
6. `alembic upgrade head` before serve
7. Smoke: `GET /health` → `sfn_ready: true`

**Local proof (2026-07-25):** API healthy on `:8000` with `sfn_ready: true`. Docker Desktop was not running on the build machine — use Railway/Fly or start Docker for container build.

## Frontend (Vercel / Netlify)

```text
NEXT_PUBLIC_API_BASE_URL=https://YOUR_API_ORIGIN
# Do NOT set NEXT_PUBLIC_ENABLE_DEBUG_TOOLS on public
# NEXT_PUBLIC_DEMO_API_KEY=...  # only if API DEMO_API_KEY set
```

## After deploy

1. Incognito: land on `/` → Open console
2. Set owner identity
3. Create migration → attach RO URL → Discover → Predict
4. Document public URL in README **Demo** section

## Lambda code changes

If ExecuteMigration / ASL changed (e.g. job_watch → stage_timings): `cd infra/sam` → `.\build.ps1` → `.\deploy.ps1`, restart API, smoke one shadow.
