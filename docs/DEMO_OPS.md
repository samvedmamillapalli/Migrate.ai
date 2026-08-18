# Demo ops — timings, cost, local start

## Local start (Windows-known-good)

1. Repo root `.env` filled (team secrets). Never commit it.
2. API (reload mode — required on Windows for Cockroach/psycopg):

```powershell
python scripts/dev.py restart
# or: cd backend; .\.venv\Scripts\python.exe _run_api_reload.py
```

3. Next UI (second terminal):

```powershell
cd frontend/oracle
npm run dev
```

4. `frontend/oracle/apps/web/.env.local`:

```text
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

(Use `:8003` if that is where the API is listening — check `GET /health`.)

5. Check `GET /health` → `sfn_ready: true`, `shadow_provider: ccloud_api`,
   `local_verify_available: false` (product UI requires real SFN).

6. Browser path: see [`docs/E2E_WALKTHROUGH.md`](E2E_WALKTHROUGH.md).

Legacy `/ui` is retired. Use only the Next app.

## Demo timings (measured 2026-07-25 PATH1)

| Stage | Typical |
| --- | --- |
| Discover | ~20s |
| Predict (Bedrock) | ~60s |
| Shadow wall (start → done) | ~90–120s |
| Cluster visible lifetime | ~60s |
| Second predict (closed loop) | ~60s |

**Talk track budget:** 5–7 minutes for the full closed loop on camera.

## Per-run shadow cost

Not billed as a fixed USD line item in-app. Judge run used Cockroach **BASIC**
plan, ~58s cluster lifetime, scale tier `medium`. Check your Cockroach Cloud
invoice / RU usage for the exact amount. For the video, say:

> “We spin up a real disposable cluster for about a minute, then tear it down.”

## Deployed frontend CORS

When the Next app has a public URL, add it to `.env` / hosting env:

```text
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://YOUR_FRONTEND_HOST
```

Restart the API after changing `CORS_ORIGINS`.

## Abort mid-shadow

Next UI → Shadow test → **Abort shadow + tear down cluster**. That stops Step
Functions and runs cleanup so the Cloud cluster is destroyed (sweeper is backup).
