# Deployment status — Migration Oracle on AWS

Live tracker. Reasoning and the full audit live in
[`AWS_DEPLOYMENT_PLAN.md`](AWS_DEPLOYMENT_PLAN.md); this file is what is
actually true right now.

**Target:** Amazon Lightsail Containers, us-east-1, **$17/month**.

## Live URLs

| | URL |
|---|---|
| **Console** | https://migration-oracle.b8db7agdvksda.us-east-1.cs.amazonlightsail.com |
| **API** | https://migration-oracle-api.b8db7agdvksda.us-east-1.cs.amazonlightsail.com |
| Health | https://migration-oracle-api.b8db7agdvksda.us-east-1.cs.amazonlightsail.com/health |

| Service | Power | Cost | Runs |
|---|---|---|---|
| `migration-oracle-api` | micro (1 GB) | $10/mo | FastAPI control plane, port 8000 |
| `migration-oracle` | nano (512 MB) | $7/mo | Next.js console, port 3000 |

Chosen over ECS Express Mode (~$54/mo — two ALBs at ~$16–22 each) and AWS
Amplify (officially supports Next.js ≤ 15; this app is on 16.2.6). Lightsail
gives a managed HTTPS endpoint with no ALB, no ACM, and no domain purchase.

---

## ✅ Done and verified

**Branch.** `origin/main` and `origin/Samved` are now the same commit
(`b948a26`) with identical trees. `origin/main` had two commits Samved lacked
(a samrita merge, a LICENSE add); recorded as an `-s ours` merge rather than a
force push, so both stay in history while main's *content* is exactly the
Samved tree. Verified before doing it: LICENSE is byte-identical on both, the
samrita merge touched nothing under `backend/` or `frontend/oracle/`, and every
path Samved removes is a scratch clone, a stray debug log, or the deliberate
2026-08-02 deletion of `app/shadow/ccloud_provider.py`.

**Code fixes** (commit `e54b185`). None touch `backend/app/`, so **no SAM
rebuild is needed** — see the plan's §0.2 for the rule.

| Fix | Why it mattered |
|---|---|
| Ship `backend/data/` | The 16-record open-source corpus. `main.py:192` swallows its absence as a warning, silently emptying the memory browser and every retrieval demo. |
| Ship `backend/alembic_helpers.py` | **Found by running the container, not by reading.** Three migrations do `from alembic_helpers import Vector`; it resolves locally only because alembic runs with `backend/` as cwd. The container died at `alembic upgrade head` with `ModuleNotFoundError` before uvicorn started. |
| Declare `cryptography` + `pyjwt[crypto]` | They arrived only transitively via `mcp`. `app/auth/clerk.py` imports `jwt` at module level, and the middleware catches the ImportError in a broad `except Exception` — so a missing module surfaces as a 401 on every request, not an import error. |
| `output: "standalone"` + `outputFileTracingRoot` | Without tracing at the monorepo root, the standalone build omits hoisted `node_modules` and `@workspace/ui` and crashes at start. |
| New `frontend/oracle/Dockerfile` | Takes `NEXT_PUBLIC_API_BASE_URL` as a **build arg**. Next inlines it at build time; a runtime env var leaves `client.ts`'s `127.0.0.1:8000` default baked in, so every visitor's browser would call their own machine. |
| Generated `GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY` | Was absent entirely. `ENVIRONMENT=production` makes it a hard raise, so GitHub Connect would fail on its first real attempt. Written to `.env` (gitignored). |

**Both images build and run.** Not inspected — executed:

- API under `ENVIRONMENT=production`: `/health` returns `status: healthy`,
  `database: healthy`, `aws: healthy`, `sfn_ready: true`, account
  `630434208625`, CockroachDB v26.2.5.
- CA cert resolves to `/app/certs/cockroach-cloud-ca.crt`, confirming the
  editable install is load-bearing (a non-editable install relocates the
  package and breaks every `sslmode=verify-full` connection).
- `backend/data/open_source_corpus` present in the image.
- Web container serves the landing page HTTP 200; the API URL is confirmed
  inlined into the served client chunks.
- Image sizes: api 887 MB, web 314 MB.

**Tooling.** `lightsailctl` installed at `~/bin/lightsailctl.exe` (the AWS CLI
invokes it; `deploy.py` puts it on PATH). AWS CLI 2.34.64, Docker 29.6.2, SAM
CLI 1.163.0 all present.

**Deploy script.** [`infra/lightsail/deploy.py`](../infra/lightsail/deploy.py),
staged and idempotent:

```
python infra/lightsail/deploy.py services   # create both services  (~5 min)
python infra/lightsail/deploy.py api        # build + push + deploy (~10 min)
python infra/lightsail/deploy.py web        # build + push + deploy (~10 min)
python infra/lightsail/deploy.py finalize   # point API CORS at the console
python infra/lightsail/deploy.py status
```

The stages exist because of a genuine circular dependency: the web image cannot
be built until the API URL exists (build-time inlining), and the API's
`CORS_ORIGINS` cannot be set until the web URL exists.

---

## Resolved blockers

**Lightsail IAM** — done. There is no AWS-managed Lightsail policy (only
`LightsailExportAccess`, a service-linked role), so `lightsail:*` was added as
an inline policy named `lightsail-deploy` on `migration-oracle-backend`.

**Signed-out deep links 404'd** — fixed, and it was a real bug, not a curl
artifact. The response headers gave it away:

```
x-clerk-auth-reason: protect-rewrite, dev-browser-missing
x-middleware-rewrite: /clerk_1786691660027
```

On a Clerk *development* instance, a bare `auth.protect()` handling a request
with no `__clerk_db_jwt` cookie rewrites internally to `/clerk_<timestamp>`
instead of redirecting, which the visitor sees as a plain 404. Anyone opening
`/dashboard/...` before signing in hit that dead end. Passing
`unauthenticatedUrl` explicitly makes the redirect deterministic and
independent of the dev-browser handshake. Verified: `/dashboard` and
`/dashboard/migrations/current` now return `307 → /login`; `/` and `/login`
still 200.

**Lightsail serializes the first service creation** — the region rejects a
second `CreateContainerService` while the first is provisioning, so `deploy.py`
now creates them strictly one at a time.

---

## Remaining after that

**Me:** run the four deploy stages, then verify against the deployed stack —
health, Clerk sign-in, corpus visible in Settings, demo-database button, one
full closed loop (connect → discover → predict → approve → real shadow cluster
→ grade → memory write), and the second-migration retrieval beat.

**You, once the URLs exist** (all three need the real domain, which is why they
come last):

1. **GitHub App** — profile picture → **Settings** → **Developer settings** →
   **GitHub Apps** → **Edit**. Set **Webhook URL** to
   `https://<api-url>/webhooks/github`; under **Identifying and authorizing
   users** set **Callback URL** to
   `https://<api-url>/api/github/oauth/callback`. **Save changes** on each.
2. **Slack** — [api.slack.com/apps](https://api.slack.com/apps) → your app →
   **OAuth & Permissions** → **Redirect URLs** →
   `https://<api-url>/api/slack/oauth/callback`.
3. **Click Connect** on the deployed Settings page. This flow has never run
   end-to-end; expect one failure on a URL mismatch.

---

## Open findings, not blockers

**`/dashboard` returns 404 when signed out.** Reproduced identically on a
native `next start` against the same build, so it is **pre-existing app
behavior, not a containerization regression** — the bar I held the change to.
Clerk's `auth.protect()` is 404ing instead of redirecting, most likely because
no `NEXT_PUBLIC_CLERK_SIGN_IN_URL` is configured. `/` and `/login` both return
200, so the normal path in works. Left alone deliberately: changing frontend
auth behavior is outside deployment scope and is Samrita's surface area.

**Lambda cold starts (plan item A9, still optional).** `TODO.md` Audit 3
measured 22–24s of a 90–120s shadow run as pure Lambda init. Bumping
`discover-schema`, `collect-metrics`, and `cleanup` from 512 MB → 1024 MB is
the fix. It is the only item needing a SAM build + deploy (~23 min) and it
touches live infrastructure. Default is skip.

**Clerk is a dev instance** (`improved-panda-78.clerk.accounts.dev`). Not
domain-locked, so it works on the deployed URL. 100-user cap, irrelevant for
judging.

## Teardown

```
aws lightsail delete-container-service --service-name migration-oracle-api --region us-east-1
aws lightsail delete-container-service --service-name migration-oracle     --region us-east-1
```

Billing stops only on delete — a disabled service still bills. The SAM stack is
separate; leave it unless you also want the 15-minute sweeper stopped.
