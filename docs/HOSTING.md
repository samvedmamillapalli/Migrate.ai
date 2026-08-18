# Hosting Migration Oracle (Wave 2)

## Pieces

| Piece | Suggested host | Notes |
| --- | --- | --- |
| FastAPI control plane | Railway / Fly / ECS | Needs `DATABASE_URL`, AWS creds, CORS |
| Next.js console | Vercel / Netlify | `NEXT_PUBLIC_API_BASE_URL` → API origin |
| Step Functions + Lambdas | AWS SAM (`infra/sam`) | Shared stack `migration-oracle` |

## API container

See repo-root [`Dockerfile`](../Dockerfile) (API only).

```bash
docker build -t migration-oracle-api .
docker run --env-file .env -p 8000:8000 migration-oracle-api
```

Set production env at minimum:

```text
ENVIRONMENT=production
AUTH_ENABLED=true
AUTH_SECRET=<long-random>
CORS_ORIGINS=https://your-frontend.example
DATABASE_URL=...
MIGRATION_WORKFLOW_ARN=...
RUN_ARTIFACTS_BUCKET=...
BEDROCK_PREDICTION_MODEL_ID=...
CCLOUD_API_SECRET=...
AWS_ENABLED=true
```

Run migrations before serving:

```bash
cd backend && alembic upgrade head
```

## Frontend

```bash
cd frontend/oracle
cp apps/web/.env.example apps/web/.env.local
# NEXT_PUBLIC_API_BASE_URL=https://api.your-domain
# NEXT_PUBLIC_AUTH_ENABLED=true   # when API AUTH_ENABLED=true
npm run build
```

## SAM promote path

When Lambda/ASL code changes:

```powershell
cd infra\sam
.\build.ps1
.\deploy.ps1   # writes ARN + bucket into .env
```

Document stack name `migration-oracle`, region `us-east-1`. After deploy, restart the API so it picks up new ARN/bucket if changed.

## CORS

Add the production frontend origin to `CORS_ORIGINS` (comma-separated, no wildcards). Restart the API.

## GitHub PR integration (optional)

`POST /webhooks/github` is a route on this same FastAPI app — no separate
Lambda/API Gateway needed, since the app already has a public URL once
hosted per this doc. Set once a GitHub App is registered
([`docs/GITHUB_APP_SETUP.md`](GITHUB_APP_SETUP.md) has the exact steps):

```env
GITHUB_APP_ID=...
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
GITHUB_WEBHOOK_SECRET=...
```

Webhook URL to register on the App: `https://<your-api-domain>/webhooks/github`.
The route is public (no Bearer token — GitHub authenticates itself via
`X-Hub-Signature-256`, allowlisted in `app/api/middleware_auth.py`).

## GitHub identity OAuth (optional) — ⚠️ finish this at deploy time

**Status as of 2026-08-08: built and code-complete, deliberately NOT
live-tested end to end.** The one step that needs a human clicking
"Authorize" on a real GitHub page was deferred until this app has a
stable public URL — doing it against the ngrok tunnel used for local dev
would mean redoing it anyway once the real domain exists, since GitHub
OAuth Apps validate the callback URL exactly. Full detail:
`docs/backendfix.md`'s 2026-08-08 entry.

Distinct from the PR-integration App above — this is "who is this GitHub
identity" for workspace-invite matching only (`read:user` scope, never
touches repos). Reuses the **same** GitHub App's OAuth Client ID/Secret
(visible on the App's settings page, same place as the private key used
for PR integration) — no second App to register.

Set once the real domain is live:

```env
GITHUB_OAUTH_CLIENT_ID=Iv23liQqujW04eOgDO6u
GITHUB_OAUTH_CLIENT_SECRET=...
GITHUB_OAUTH_REDIRECT_URI=https://<your-api-domain>/api/github/oauth/callback
GITHUB_OAUTH_STATE_SECRET=<any random string>
GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY=<Fernet key — see .env.example for the generate command>
GITHUB_OAUTH_INSTALL_SUCCESS_REDIRECT=https://<your-frontend-domain>/dashboard/settings?github=connected
GITHUB_OAUTH_INSTALL_ERROR_REDIRECT=https://<your-frontend-domain>/dashboard/settings?github=error
```

**Then, before calling this done:**

1. On the App's settings page (**github.com/settings/apps/migration-oracle**),
   update **Callback URL** under "Identifying and authorizing users" to
   `https://<your-api-domain>/api/github/oauth/callback` — the value used
   during local dev (the ngrok tunnel) will be stale once redeployed.
2. Restart the API so it picks up the new env vars.
3. `GET /api/github/status` (authenticated) should report `configured: true`.
4. Click **Connect** in the real Settings page, approve on GitHub's real
   page, confirm it redirects back with `?github=connected` and shows your
   GitHub username. This is the one step that has never actually run
   end-to-end — everything up to the real `github.com` redirect has been
   verified (16 unit tests + a live check that the generated authorize URL
   gets a real `302` from GitHub, not an error), but the actual
   authorize→callback→token-exchange round trip has not.
