# Deploying the Migration Oracle execution plane (us-east-1)

> **Teammates:** you usually **skip this file**. The shared stack
> `migration-oracle` is already up. Put the team's filled `.env` at the repo
> root, then run:
> `python scripts/dev.py setup` and `python scripts/dev.py restart`.
> Only re-deploy here when Lambda / ASL / stack params change.

## Promote checklist (after Lambda/ASL changes)

1. `cd infra/sam` → `.\build.ps1` → `.\deploy.ps1`
2. Confirm `.env` has updated `MIGRATION_WORKFLOW_ARN` / `RUN_ARTIFACTS_BUCKET`
3. Restart the API (`python scripts/dev.py restart` or redeploy the hosted control plane)
4. `GET /health` → `integrations.sfn_ready: true`
5. Smoke one real shadow run — [`docs/E2E_WALKTHROUGH.md`](E2E_WALKTHROUGH.md)

Control-plane + frontend hosting: [`docs/HOSTING.md`](HOSTING.md).

One-command repeatable deploy for: **S3 artifacts bucket**, **seven workflow
Lambdas** (ZIP packages using `SHADOW_PROVIDER=ccloud_api`), **EventBridge orphan
sweeper**, and the **Step Functions** state machine whose ASL is
`infra/stepfunctions/migration_workflow.asl.json` with Lambda ARNs substituted
at deploy time.

Predict / approve stay on the FastAPI control plane (Phase 9). They are **not**
SFN states — the state machine starts after human `proceed`.

Region is **us-east-1** everywhere (Bedrock + shadow cluster defaults).

---

## Prerequisites

1. AWS CLI v2 configured for an account that can create IAM, Lambda, SFN, S3, EventBridge (region `us-east-1`).
   - Runtime user `migration-oracle-backend` cannot deploy alone — it needs `iam:CreateRole` (attach `infra/sam/iam/deployer-policy.json` as admin, or use an admin principal).
   - Prefer `.\deploy.ps1` on Windows: it survives missing `DescribeStackEvents` and writes stack outputs into `.env`.
2. [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) installed and on `PATH`.

   **Windows (winget):**

   ```powershell
   winget install --id Amazon.SAM-CLI -e --accept-source-agreements --accept-package-agreements
   ```

   Then **close and reopen** the terminal (or Cursor) so `sam` is on `PATH`. Confirm:

   ```powershell
   sam --version
   ```

   If you still get “term 'sam' is not recognized”, log out/in once, or open a **new** PowerShell and check:

   ```powershell
   Get-Command sam
   # typically under: C:\Program Files\Amazon\AWSSAMCLI\bin\sam.cmd
   ```
3. **Docker Desktop running** — `samconfig.toml` defaults to `use_container = true`.

   - Start **Docker Desktop** and wait until it says engine is running.
   - Confirm: `docker info` (should not say “cannot connect to the docker API”).
   - If `~/.docker/config.json` is invalid JSON, Docker will fail even when open — fix/remove trailing commas.

   Windows native build (no Docker) — preferred on this repo:

   ```powershell
   winget install -e --id ezwinports.make   # once
   cd infra\sam
   .\build.ps1
   ```

   (`build.ps1` uses a thin `lambda_src/` CodeUri so SAM does not copy all of `backend/`.)
4. CockroachDB Cloud control-plane `DATABASE_URL` (same DB Alembic migrated).
5. CockroachDB Cloud **service account secret** for `ccloud_api` (`CCLOUD_API_SECRET`).
6. Bedrock model access in **us-east-1** for:
   - Claude (prediction / grade prose) — console “Model access”
   - Titan Embeddings `amazon.titan-embed-text-v2:0`

### Manual console actions (only these)

| Action | Where | Why |
| --- | --- | --- |
| Request Bedrock model access | Bedrock → Model access → us-east-1 | InvokeModel fails until granted |
| Create CockroachDB Cloud service account | CockroachDB Cloud console | Provides `CCLOUD_API_SECRET` for shadow provision |
| (Optional) Store CCloud secret in Secrets Manager | Secrets Manager | Pass ARN as `CCloudApiKeySecretArn` instead of plaintext param |

Everything else is IaC under `infra/sam/`.

---

## One-command deploy

From the repo root (PowerShell or bash):

```bash
cd infra/sam

# Windows: .\build.ps1
# Linux/macOS (Docker): sam build --use-container
sam build --no-use-container

sam deploy \
  --stack-name migration-oracle \
  --region us-east-1 \
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
  --resolve-s3 \
  --parameter-overrides \
    "ProjectName=migration-oracle \
    EnvironmentName=demo \
    DatabaseUrl=postgresql://USER:PASS@HOST:26257/migration_oracle?sslmode=verify-full \
    CCloudApiSecret=YOUR_CCLOUD_API_SECRET \
    BedrockPredictionModelId=us.anthropic.claude-sonnet-4-6 \
    BedrockEmbeddingModelId=amazon.titan-embed-text-v2:0"
```

First time on a machine you can use guided mode (prompts for parameters):

```bash
cd infra/sam
sam build
sam deploy --guided --region us-east-1
```

`--guided` writes overrides into `samconfig.toml` locally — **do not commit secrets**.

---

## Retrieve outputs → `.env`

```bash
aws cloudformation describe-stacks \
  --stack-name migration-oracle \
  --region us-east-1 \
  --query "Stacks[0].Outputs" \
  --output table
```

Or key/value pairs:

```bash
aws cloudformation describe-stacks \
  --stack-name migration-oracle \
  --region us-east-1 \
  --query "Stacks[0].Outputs[?OutputKey=='MigrationWorkflowArn' || OutputKey=='ArtifactsBucket'].[OutputKey,OutputValue]" \
  --output text
```

Put into repo-root `.env` (never commit):

```env
AWS_ENABLED=true
AWS_DEFAULT_REGION=us-east-1
ENVIRONMENT=demo
MIGRATION_WORKFLOW_ARN=arn:aws:states:us-east-1:ACCOUNT:stateMachine:migration-oracle-migration-workflow
RUN_ARTIFACTS_BUCKET=migration-oracle-artifacts-ACCOUNT
BEDROCK_PREDICTION_MODEL_ID=us.anthropic.claude-sonnet-4-6
BEDROCK_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0
BEDROCK_REGION=us-east-1
SHADOW_PROVIDER=ccloud_api
CCLOUD_API_SECRET=...
DATABASE_URL=...
```

With `ENVIRONMENT=demo` (or `AWS_REQUIRE_WORKFLOW_CONFIG=true`), the FastAPI process **refuses to start** if the workflow ARN or artifacts bucket are missing, and prints how to fetch stack outputs.

---

## Verify deploy without a full migration

1. **Stack CREATE_COMPLETE**

   ```bash
   aws cloudformation describe-stacks --stack-name migration-oracle --region us-east-1 \
     --query "Stacks[0].StackStatus" --output text
   ```

2. **State machine exists and definition has Lambda ARNs (no `${...}` left)**

   ```bash
   ARN=$(aws cloudformation describe-stacks --stack-name migration-oracle --region us-east-1 \
     --query "Stacks[0].Outputs[?OutputKey=='MigrationWorkflowArn'].OutputValue" --output text)

   aws stepfunctions describe-state-machine --state-machine-arn "$ARN" --region us-east-1 \
     --query "definition" --output text | findstr /C:"arn:aws:lambda" 
   # bash: | grep -c 'arn:aws:lambda'  → expect 7
   ```

3. **Smoke-invoke discover Lambda with a nonsense payload (expect validation error, not Auth/Import fail)**

   ```bash
   FN=$(aws cloudformation describe-stacks --stack-name migration-oracle --region us-east-1 \
     --query "Stacks[0].Outputs[?OutputKey=='DiscoverSchemaFunctionArn'].OutputValue" --output text)

   aws lambda invoke --function-name "$FN" --region us-east-1 \
     --payload "{\"run_id\":\"00000000-0000-0000-0000-000000000000\"}" \
     --cli-binary-format raw-in-base64-out /tmp/out.json
   type /tmp/out.json   # bash: cat /tmp/out.json
   ```

   You want a controlled handler / validation error mentioning `run_id` or DB — not `Unable to import module`.

4. **Control plane**

   ```bash
   cd backend
   uvicorn app.main:app --app-dir .
   curl http://127.0.0.1:8000/health
   ```

   Logs should show `AWS startup validation succeeded` with both ARN and bucket present.

---

## What the stack creates

| Resource | Purpose |
| --- | --- |
| `*-discover-schema` | Read-only customer schema → snapshot (+ S3 artifact) |
| `*-provision-shadow-cluster` | CockroachDB Cloud cluster via **REST** `ccloud_api` (timeout 900s) |
| `*-load-schema` | Apply schema onto shadow (“seed” step in the loop) |
| `*-execute-migration` | Run migration SQL on shadow |
| `*-collect-metrics` | Collect duration / storage metrics (“verify” measurements) |
| `*-persist-results` | Write `ExecutionResult` + grade + memory (Bedrock InvokeModel) |
| `*-cleanup` | Tear down shadow + delete shadow secrets |
| `*-shadow-sweeper` | EventBridge every 15m — orphan cluster hygiene |
| `*-migration-workflow` | Step Functions STANDARD SM from ASL + substitutions |
| Artifacts bucket | `RUN_ARTIFACTS_BUCKET` |

IAM is least-privilege per function: S3 limited to that bucket, Secrets Manager limited to `migration-oracle/connections*` / `migration-oracle/shadow*`, Bedrock only on PersistResults (`InvokeModel`), CloudWatch `PutMetricData` scoped by namespace where supported.

---

## Update / destroy

```bash
cd infra/sam
sam build && sam deploy --region us-east-1

aws cloudformation delete-stack --stack-name migration-oracle --region us-east-1
```

After delete, clear `MIGRATION_WORKFLOW_ARN` and `RUN_ARTIFACTS_BUCKET` from `.env` or local API start will fail in `demo`/`production`.
