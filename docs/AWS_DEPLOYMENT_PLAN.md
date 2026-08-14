# AWS Deployment Plan — Migration Oracle

**Status: planning only. Nothing here has been executed.**

Written 2026-08-12 by reading the codebase, querying the live AWS account
`630434208625`, diffing the deployed Lambda package against local source, and
checking every third-party console path against current vendor documentation.
Where an existing doc in this repo is wrong, this plan says so.

Work is split into five parts:

| Part | Who | What |
|---|---|---|
| **A** | **ME** | Code fixes before deployment |
| **B** | **YOU** | Setup before deployment |
| **C** | **YOU + ME** | The deployment itself |
| **D** | **ME** | Verification after deployment |
| **E** | **YOU** | Third-party console work after deployment |

---

## 0. Things you should know before we start

### 0.1 The AWS execution plane is already deployed **and current**

The `migration-oracle` SAM stack is `UPDATE_COMPLETE`, last updated
2026-08-12 06:23 UTC. I verified this isn't just a timestamp: I downloaded the
deployed `discover-schema` Lambda package (37.8 MB) and hashed five files
against local source, including every file changed by your most recent commit
(`65d0c88`, the shadow bug fixes):

```
SAME   app/lambdas/handlers/discover_schema.py      5402B
SAME   app/lambdas/handlers/load_schema.py          6645B
SAME   app/lambdas/handlers/provision_shadow.py     9161B
SAME   app/shadow/changefeed_watch.py              11233B
SAME   app/services/connection_secrets.py           7724B
```

**Byte-identical. The deployed Lambdas are running your current code.** The
commit landed at 08:32 UTC, two hours *after* the deploy, but the files were
written before it — so the "commit is newer than the stack" signal was a false
alarm. No SAM rebuild is needed to deploy. See §0.2 for when one *would* be.

### 0.2 When a SAM build + deploy **is** required

You were right to raise this — it's a real trap in this repo, and one your own
notes already flag: *"editing `app/shadow/*` or `app/lambdas/handlers/*`
locally changes nothing about a real run until the SAM stack is redeployed."*
On 2026-07-30 that cost a long debug session with 5-day-stale Lambdas.

The packaging script (`backend/scripts/package_lambda_for_sam.py:192`) does
`shutil.copytree(backend/app → artifacts/app)` — **the entire `backend/app`
tree goes into all 8 Lambda packages.** So:

| Change | Rebuild needed? |
|---|---|
| **Anything** under `backend/app/**` | ✅ **Yes** — even a control-plane-only file |
| `infra/sam/template.yaml` or the ASL JSON | ✅ Yes |
| `backend/requirements-lambda.txt` | ✅ Yes |
| Root `Dockerfile`, `backend/pyproject.toml`, `backend/requirements.txt` | ❌ No — control plane only |
| Anything under `frontend/` | ❌ No |
| `certs/` | ✅ Yes (bundled into the package) |

**None of my Part A fixes touch `backend/app/`.** They're the root Dockerfile,
`pyproject.toml`, `next.config.ts`, a new frontend Dockerfile, and docs. So the
baseline plan needs **no SAM rebuild**. The one thing that would change that is
optional item **A9** (the Lambda memory bump) — your call.

**If we do need one**, run it from **Bash, not PowerShell**. `build.ps1` and
`deploy.ps1` fail under this environment: PowerShell 5.1 wraps a native
command's stderr in an ErrorRecord, and `$ErrorActionPreference = "Stop"` then
kills the script even when `sam` exits 0.

```bash
cd infra/sam
export PATH="$PATH:/c/Users/samve/AppData/Local/Microsoft/WinGet/Packages/ezwinports.make_Microsoft.Winget.Source_8wekyb3d8bbwe/bin:/c/Program Files/Amazon/AWSSAMCLI/bin"
export BACKEND="<repo>/backend"
set -a && source ../../.env && set +a && unset AWS_PROFILE
rm -rf .aws-sam/build          # OneDrive locks dist-info files; pre-clean
sam.cmd build --no-use-container
sam.cmd deploy --stack-name migration-oracle --region us-east-1 \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM --resolve-s3 \
  --no-confirm-changeset --disable-rollback \
  --parameter-overrides "ProjectName=migration-oracle" "EnvironmentName=demo" \
    "DatabaseUrl=$DATABASE_URL" "CCloudApiSecret=$CCLOUD_API_SECRET" \
    "CCloudApiKey=$CCLOUD_API_KEY" "CCloudApiKeySecretArn=$CCLOUD_API_KEY_SECRET_ARN" \
    "BedrockPredictionModelId=$BEDROCK_PREDICTION_MODEL_ID" \
    "BedrockEmbeddingModelId=amazon.titan-embed-text-v2:0"
```

Budget **~8 min build + ~15 min deploy** (~240 MB of artifacts). Tooling is
confirmed present: SAM CLI 1.163.0, GNU make at the ezwinports path above,
Docker 29.6.2 (not needed — we build natively with `--no-use-container`).

⚠️ `sam deploy` **must** be given every parameter override. There are no
`parameter_overrides` in `samconfig.toml`, and CloudFormation will not reuse
previous values automatically — a bare `sam deploy` would blank out
`DatabaseUrl` and `CCloudApiSecret` and break all 8 Lambdas.

Correction to `docs/DEPLOYMENT.md`: it claims the runtime IAM user "cannot
deploy alone — it needs `iam:CreateRole`". That's now **false**. The inline
policy `migration-oracle-policy` on `migration-oracle-backend` grants
`cloudformation:*`, `iam:*`, `lambda:*`, `states:*`, `s3:*`, `events:*`,
`logs:*`. It can deploy the stack fine.

### 0.3 🔴 App Runner is dead — the hosting target changed

My first draft of this plan recommended AWS App Runner. **That was wrong, and
I'm glad you asked me to check.** Per AWS's own documentation:

> "AWS App Runner is no longer open to new customers. Existing customers can
> continue to use the service as normal."

It closed to new customers on **2026-04-30**. This account has never used it,
so it isn't available to us. AWS's stated replacement is **Amazon ECS Express
Mode**, and it's genuinely a better fit here:

- **One CLI call** — `aws ecs create-express-gateway-service` provisions an
  ECS Fargate service, an internet-facing ALB, target groups, security groups,
  auto-scaling, and CloudWatch logging.
- **Automatic HTTPS on a managed URL** — `https://<name>.ecs.us-east-1.on.aws/`
  with a real certificate, no domain purchase, no ACM setup. This was the whole
  reason I picked App Runner, and Express Mode keeps it.
- **No extra charge** for Express Mode itself; you pay only for the Fargate
  tasks and ALB underneath.
- **Verified available to us**: your AWS CLI 2.34.64 already has the command
  (including `--task-role-arn`), and account `630434208625` has a default VPC
  in us-east-1 (`vpc-0b430d22c76eef674`), which Express Mode requires.

**And it removes my one caveat.** I was worried about a proxy timeout killing
the shadow-cluster SSE stream. Reading the actual generator
(`runs.py:820-874`), it emits a `heartbeat` event **every 1–3 seconds** — far
under any ALB idle timeout. SSE will work fine. No degradation, no fallback
needed.

### 0.4 Everything else about the current state

| Piece | State |
|---|---|
| FastAPI control plane | Local only — never containerized for deploy |
| Next.js frontend | Local only — no Dockerfile, no standalone output |
| CockroachDB control-plane DB | Live, 25 Alembic revisions applied |
| `customer_demo` DB (demo button) | Live, 12 tables — but reachable only via a gitignored local file (**A6**) |
| Clerk | Works; **dev instance** `improved-panda-78.clerk.accounts.dev` |
| GitHub App | Built + verified; URLs point at a dead ngrok tunnel |
| GitHub OAuth identity | Built, **never completed end-to-end once** |
| Slack | Built; redirect points at `localhost:8003` |
| Git branch | `Samved` is **34 commits ahead of `main`** |

---

## Part A — Code fixes I do before deployment  **[ME]**

Every one of these is a real defect found in this audit, not speculative
hardening. **None touch `backend/app/`, so none trigger a SAM rebuild.**

### 🔴 A1 — Dockerfile doesn't ship the open-source corpus
`Dockerfile` copies `backend/app`, `backend/alembic`, `alembic.ini`, and
`certs` — but not `backend/data/`. `open_source_corpus.py:50` resolves
`_DATA_DIR = backend/data/open_source_corpus`, holding all **16 curated
incident records**. In the container that directory won't exist, and
`main.py:192` swallows the failure as a warning. The corpus your memory and
retrieval demo beats depend on would be silently empty.
**Fix:** `COPY backend/data ./backend/data`.

### 🔴 A2 — The image installs the wrong dependency list
`Dockerfile` runs `pip install -e .`, using `backend/pyproject.toml`, which is
missing `cryptography` and `pyjwt[crypto]`. `requirements.txt` has both, and
the app needs both — `app/auth/clerk.py:14` has a top-level
`from jwt import PyJWKClient`, and Fernet token encryption needs
`cryptography`. Today they arrive only *transitively* through `mcp>=2.0.0`.
If that resolution shifts, Clerk auth fails **silently**: the middleware
catches the ImportError in a broad `except Exception`
(`middleware_auth.py:98`) and returns a misleading 401 on every request.
**Fix:** add both to `pyproject.toml`, and install from `requirements.txt`.

### 🔴 A3 — `NEXT_PUBLIC_API_BASE_URL` is baked in at build time
The single easiest way to ship a broken frontend. Next.js inlines
`NEXT_PUBLIC_*` into the JS bundle during `next build`, not at container start.
Without it as a **Docker build arg**, `client.ts:12` falls back to
`DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"` and every deployed browser
calls the *viewer's own laptop* — over HTTP from an HTTPS page, so also blocked
as mixed content. Setting it as a runtime env var will not help.
**Fix:** frontend Dockerfile takes it as `ARG`; build command passes it.

### 🔴 A4 — No frontend Dockerfile, no `output: "standalone"`
`next.config.ts` is three lines. Without standalone output the image carries
the whole Turborepo `node_modules` tree.
**Fix:** add `output: "standalone"`; write a multi-stage Dockerfile handling
the `apps/web` + `packages/ui` workspace layout.

### 🔴 A5 — `GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY` doesn't exist
Absent from `.env` entirely. With `ENVIRONMENT=production`,
`github_identity_oauth_service.py:71-75` raises
`"GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY is required in production"` — so the GitHub
Connect flow (the one thing `docs/HOSTING.md` explicitly defers to deploy time)
fails on its first real attempt.
**Fix:** I generate a Fernet key and write it into `.env` (gitignored).

### 🔴 A6 — The demo-database button has no production path
`POST /runs/debug/demo-with-db` (`runs.py:366-374`) reads
`DEMO_READONLY_DATABASE_URL`, else falls back to
`.local_secrets/.judge_ro_database_url` — gitignored, not in the image. Unset,
the judge demo button returns a validation error.
**Fix:** I read the value from your local file and put it in the service env.

### 🔴 A7 — Fifteen config values still point at localhost
`CORS_ORIGINS`, `FRONTEND_URL`, `SLACK_REDIRECT_URI`,
`SLACK_INSTALL_SUCCESS_REDIRECT`, `SLACK_INSTALL_ERROR_REDIRECT`,
`GITHUB_OAUTH_REDIRECT_URI`, `GITHUB_OAUTH_INSTALL_SUCCESS_REDIRECT`,
`GITHUB_OAUTH_INSTALL_ERROR_REDIRECT`, plus the frontend's API base URL.
**Fix:** parameterized now, filled with real URLs in Part C.

### 🟡 A8 — Doc corrections
`docs/HOSTING.md` says `cp apps/web/.env.example`; the real file is
`.env.local.example`. It also recommends Railway/Fly/Vercel — superseded by
this plan. `docs/DEPLOYMENT.md`'s IAM claim is wrong (§0.2).

### ⚪ A9 — Lambda memory bump *(optional, needs your yes)*
`TODO.md` Audit 3 measured all 7 Lambdas cold on ~every invocation, ~3.2–3.4s
init each — **22–24s of a 90–120s shadow run**, a visible chunk of what a judge
watches. The recommendation was bumping `discover-schema`, `collect-metrics`,
and `cleanup` from 512MB → 1024MB, since Lambda init CPU scales with memory.

This is the **only** item that requires a SAM build + deploy (~23 min) and it
touches live infrastructure. I'd do it *after* the web deploy is green so it
can't complicate the critical path. **Default is skip** unless you say
otherwise.

### 🟡 A10 — Debug routes are ungated server-side
`/runs/debug/demo-with-db` and `/runs/debug/fake-migration` have no environment
guard; the frontend only hides the *buttons* behind
`NEXT_PUBLIC_ENABLE_DEBUG_TOOLS`. You almost certainly want `demo-with-db` live
(it's the judge demo button). **Plan: keep both, leave
`NEXT_PUBLIC_ENABLE_DEBUG_TOOLS` unset** so the fake-migration button is hidden.
Say so if you'd rather I gate them server-side.

---

## Part B — What you set up before deployment  **[YOU]**

Four things. Details and exact commands are in the chat message accompanying
this plan.

**B1 — Grant your IAM user ECS + ECR permissions.** `migration-oracle-backend`
has broad Lambda/SFN/S3/IAM/CFN access but **no `ecs:*` and no `ecr:*`**, so I
can't create the services. Because the user already has `iam:*`, this is two
commands you can run yourself (or two clicks in the IAM console).

**B2 — Decide the deploy branch.** `Samved` is 34 commits ahead of `main`.
Deploy from `Samved` as-is, or merge `Samved → main` first.
⚠️ Do **not** merge `samrita` in afterwards without checking — that branch has
previously reverted merged features back to "coming soon" stubs.

**B3 — Confirm the three decisions** (hosting = ECS Express Mode, Clerk stays
on the dev instance, API gets an ECS task role instead of access keys).

**B4 — Say yes or no to A9** (the Lambda memory bump and its ~23-minute SAM
redeploy).

---

## Part C — The deployment  **[YOU + ME]**

**Ordering is the crux.** The frontend needs the API's URL *at build time*
(A3); the API needs the frontend's URL in its CORS config. Neither URL exists
until ECS creates the service. So: **API first, frontend second, then one
config pass back over the API.** It cannot be done in one shot.

| # | Step | Who |
|---|---|---|
| C1 | Create the two Express Mode IAM roles (`ecsTaskExecutionRole`, `ecsInfrastructureRoleForExpressServices`) and an API task role carrying the app's AWS permissions | **ME** |
| C2 | Create ECR repos `migration-oracle-api` and `migration-oracle-web` | **ME** |
| C3 | Build the API image, run it locally against the real DB, push to ECR | **ME** |
| C4 | `create-express-gateway-service` for the API: port 8000, `--health-check-path /health`, task role from C1, full env var set | **ME** |
| C5 | Record the API URL `https://<name>.ecs.us-east-1.on.aws` | **ME** → I tell you |
| C6 | Build the frontend image **with the C5 URL as a build arg**, test locally, push | **ME** |
| C7 | `create-express-gateway-service` for the web app: port 3000, health check `/` | **ME** |
| C8 | Update the API service's env with the real frontend URL (the 8 values in A7) and redeploy | **ME** |
| C9 | Spot-check both services in the ECS console; confirm you're happy before I run the full verification | **YOU** |

Note: the API image's `CMD` already runs `alembic upgrade head` before uvicorn,
so migrations self-apply on boot. All 25 revisions are already applied, so
first boot is a no-op — but future migrations will deploy themselves.

⚠️ IAM roles are eventually consistent. AWS's own docs warn that
`create-express-gateway-service` can fail with an assume-role error if run
immediately after role creation; the fix is to wait ~60s and retry. I'll
account for that rather than treating it as a real failure.

---

## Part D — Verification after deployment  **[ME]**

Not "it deployed." Actually exercised, with observed results written up:

1. `GET /health` → `healthy`, `sfn_ready: true`, `database: healthy`.
2. Clerk sign-in on the deployed frontend — this is where a missing `jwt`
   import (A2) would show up, as a 401 wall.
3. Overview loads with real charts, no CORS errors in the console.
4. **Corpus check (A1):** Settings → memory browser shows the 16 open-source
   incidents, not an empty list.
5. **Demo button (A6):** "Try the demo database" creates a run and completes
   schema discovery.
6. **One full closed loop on the deployed stack:** connect → discover →
   predict → approve → real shadow cluster → grade → memory write. The only
   test that proves the hosted API can drive the already-live state machine.
7. Shadow live view updates over SSE during that run (§0.3 says it should).
8. A second, similar migration retrieves the first from memory.
9. Update `HOSTING.md` / `DEPLOYMENT.md` / `DEMO_OPS.md` with the real URLs.

Steps 1–8 minus the GitHub piece, which needs Part E first.

---

## Part E — Third-party consoles after deployment  **[YOU]**

These need the real deployed URLs, which is exactly why they come last. I
can't do any of them — they're external sites requiring your login. Exact
click paths are in the chat message; all three were verified against current
vendor docs.

**E1 — GitHub App: webhook URL + callback URL.** Both point at a dead ngrok
tunnel today. GitHub validates the callback URL *exactly*.

**E2 — Slack app: OAuth redirect URL.**

**E3 — Click Connect on GitHub in the deployed Settings page.** This is the
one flow that has never run end-to-end. Everything up to the real `github.com`
redirect is verified (16 unit tests + a live 302 check); the
authorize → callback → token-exchange round trip is not. **Expect it to fail
once on a URL mismatch and need a retry — budget real time.**

**E4 — Tell me the results** so I can finish the verification runbook.

---

## Cost, rollback, teardown

**Running cost:** two Express Mode services ≈ two Fargate tasks (1 vCPU / 2 GB
default) + two ALBs. Ballpark **$40–60/month** if left running — the ALBs are
the bulk of it (~$16/mo each). Express Mode itself adds no charge. Notably
*more* than App Runner would have been; if that matters, both services can run
at reduced CPU/memory, and everything is deletable in one command after
judging.

**Rollback:** I'll tag images with the git SHA rather than `latest`, so
reverting is redeploying a previous tag. Express Mode also does canary
deployments with 5XX rollback alarms by default.

**Teardown:** `aws ecs delete-express-gateway-service` ×2, delete the two ECR
repos. Leave the SAM stack alone unless you also want the 15-minute sweeper
schedule stopped.

**Deliberately not in scope:** custom domain, CDN, CI/CD pipeline, staging
environment, WAF, production Clerk instance. None affect judging; all cost
time you don't have before Aug 18.

---

## Appendix A — API service environment variables

**Carried over unchanged from `.env`:** `DATABASE_URL`, `AWS_DEFAULT_REGION`,
`MIGRATION_WORKFLOW_ARN`, `RUN_ARTIFACTS_BUCKET`, `BEDROCK_PREDICTION_MODEL_ID`,
`BEDROCK_RECOMMENDATION_MODEL_ID`, `BEDROCK_EMBEDDING_MODEL_ID`,
`BEDROCK_REGION`, `SHADOW_PROVIDER`, the `SHADOW_*` tuning values,
`CCLOUD_API_KEY`, `CCLOUD_API_SECRET`, `CCLOUD_API_BASE_URL`,
`USER_DATABASE_SECRET_PREFIX`, `AWS_CLOUDWATCH_NAMESPACE`, `CLERK_SECRET_KEY`,
`CLERK_PUBLISHABLE_KEY`, `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`,
`SLACK_SIGNING_SECRET`, `SLACK_STATE_SECRET`, `SLACK_TOKEN_ENCRYPTION_KEY`,
`GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_WEBHOOK_SECRET`,
`GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`,
`GITHUB_OAUTH_STATE_SECRET`.

**Changed for production:** `ENVIRONMENT=production`, `DEBUG=false`,
`AWS_ENABLED=true`, plus the eight URL values from A7.

**New, must be created:** `GITHUB_OAUTH_TOKEN_ENCRYPTION_KEY` (A5),
`DEMO_READONLY_DATABASE_URL` (A6).

**Deliberately omitted:** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_PROFILE` — the ECS task role supplies credentials, and their *presence*
would override it.

`ENVIRONMENT=production` is not cosmetic. It makes AWS client-factory failure
fatal at startup (`main.py:137`), makes `/health` return 503 when AWS is
unhealthy (`health.py:37`), forbids the in-process connection-secret fallback
(so Secrets Manager must work), and makes both Fernet keys mandatory. All
correct — but a missing key becomes a hard failure, not a warning. I'll
pre-flight every one before flipping it on.

## Appendix B — Frontend build args vs runtime env

| Variable | When | Why it matters |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | **Build arg** | Inlined into the bundle. Wrong = app calls `127.0.0.1` (A3). |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | **Build arg** *and* runtime | Needed at build to prerender pages mounting `ClerkProvider`. |
| `CLERK_SECRET_KEY` | Runtime | Server-side only; used by `clerkMiddleware`. |
| `NEXT_PUBLIC_ENABLE_DEBUG_TOOLS` | Build arg | **Leave unset** in production (A10). |
| `NEXT_PUBLIC_DEMO_API_KEY` | Build arg | Only if `DEMO_API_KEY` is set on the API. Currently unset — keep it that way. |

## Appendix C — Sources for the external facts in this plan

- [AWS App Runner availability change](https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html) — closed to new customers; ECS Express Mode is the recommended replacement
- [Create your first Express Mode service using the AWS CLI](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-getting-started.html) — required IAM roles, parameters, `https://<name>.ecs.<region>.on.aws` URL format, default-VPC requirement
- [Modifying a GitHub App registration](https://docs.github.com/en/apps/maintaining-github-apps/modifying-a-github-app-registration) — navigation to Webhook URL and Callback URL
- [About the user authorization callback URL](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/about-the-user-authorization-callback-url) — callback vs setup URL distinction
- [Installing with OAuth (Slack)](https://docs.slack.dev/authentication/installing-with-oauth) — Redirect URL lives under **OAuth & Permissions**
