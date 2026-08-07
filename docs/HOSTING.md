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
