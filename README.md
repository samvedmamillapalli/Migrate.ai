# Migration Oracle

**Predict → verify → grade → remember.** An agentic migration advisor that scores its own predictions against real shadow runs and retrieves graded memories for the next attempt.

Built for the [CockroachDB × AWS Hackathon](https://cockroachdb-ai.devpost.com/).

## Demo (judges)

| Asset | Location |
| --- | --- |
| Day-of checklist + roles | [`demo/DEMO_DAY.md`](demo/DEMO_DAY.md) |
| SQL A/B playbook | [`demo/SQL_PLAYBOOK.md`](demo/SQL_PLAYBOOK.md) |
| Shadow / closed-loop proof | [`demo/SHADOW_PROOF.md`](demo/SHADOW_PROOF.md) |
| 5–7 min talk track | [`demo/TALK_TRACK.md`](demo/TALK_TRACK.md) |
| Video script (&lt;3 min) | [`demo/VIDEO_SCRIPT.md`](demo/VIDEO_SCRIPT.md) |
| Chaos backup lines | [`demo/CHAOS_BACKUPS.md`](demo/CHAOS_BACKUPS.md) |
| Public deploy | [`demo/DEPLOY_CHECKLIST.md`](demo/DEPLOY_CHECKLIST.md) |
| Freeze / Devpost | [`demo/SUBMIT.md`](demo/SUBMIT.md) |
| E2E click path | [`docs/E2E_WALKTHROUGH.md`](docs/E2E_WALKTHROUGH.md) |
| Tool narrative | [`docs/HACKATHON_TOOLS.md`](docs/HACKATHON_TOOLS.md) |

**Thesis:** Predict → verify → grade → remember — not another risk labeler.

**Public URL:** _add after Phase 7 deploy_

## Stack

| Layer | Choice |
| --- | --- |
| API | FastAPI (Python) |
| Control-plane DB | CockroachDB Cloud |
| UI | Next.js app in `frontend/oracle` (default `http://localhost:3000`) |
| AI | Amazon Bedrock (Claude predict/recommend, Titan embeddings) |
| Orchestration | AWS Lambda + Step Functions + S3 + Secrets Manager + CloudWatch |
| Shadow verify | CockroachDB Cloud clusters (`SHADOW_PROVIDER=ccloud_api` by default) |

## CockroachDB tools used (demo claim)

1. **Distributed Vector Indexing** — hybrid retrieval over `migration_memories` embeddings (`ix_migration_memories_embedding`).
2. **Managed MCP / live job watch** — during ExecuteMigration we snapshot `SHOW JOBS` on the shadow cluster (same job surface MCP agents use) and attach attribution to run artifacts. IDE MCP config lives in `.cursor/mcp.json`.

AWS: Bedrock + Lambda + Step Functions + S3 + Secrets Manager + CloudWatch.

## Closed loop

```text
POST /runs                  → pending
POST /runs/{id}/discover    → schema snapshot + connection_secret_arn
POST /runs/{id}/predict     → awaiting_approval (policy + Bedrock + memory)
POST /runs/{id}/approve     → proceed starts Step Functions (when ARN + secret set)
                              → shadow verify → persist → auto grade + remember
GET  /runs/{id}/grade
GET  /runs/{id}/memory
```

One-shot operator shortcut (predict + proceed + start when configured):

```text
POST /runs/{id}/closed-loop
```

`WorkflowOrchestrationService.start_for_run(..., require_prediction_and_approval=True)` refuses to start SFN unless prediction + `proceed` approval exist.

## Quick start (teammates)

The AWS stack (`migration-oracle`) is **already deployed** and shared. You do
**not** run `sam deploy`, Docker, or AWS CLI for normal local use.

### What you need besides `.env`

| Need | Notes |
| --- | --- |
| **Git** | Clone / pull this branch |
| **Python 3.12+** | On `PATH` as `python` (or `python3`) |
| **Network** | Reach AWS `us-east-1` + CockroachDB Cloud |
| **Team `.env`** | Filled file at repo root (out of band — never commit) |

That is everything beyond your IDE for the **API**. For the operator console you also need **Node.js 20+** (`npm`). No Docker, SAM CLI, AWS CLI, or Make for the normal demo path. The Cockroach CA cert ships in `certs/cockroach-cloud-ca.crt`; `setup` installs it for you.

### Run it

1. Clone/pull this branch (`Samved`).
2. Place the team filled `.env` at the repo root (same folder as this README). Never commit it.
3. From the repo root, run **two commands**:

```bash
python scripts/dev.py setup
python scripts/dev.py restart
```

Windows wrapper: `.\restart.ps1`  
macOS/Linux wrapper: `./restart.sh` (or `bash ./restart.sh`)

Open **http://localhost:3000** for the Next.js operator UI (start it in a
second terminal — `scripts/dev.py` starts the **API only**). API health:
**http://127.0.0.1:8000/health** should show `integrations.sfn_ready: true`.

In a second terminal:

```bash
cd frontend/oracle
npm install
npm run dev
```

Point the web app at the API with `frontend/oracle/apps/web/.env.local`
(see `frontend/oracle/apps/web/.env.example`):

```text
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Demo click-path (real CockroachDB Cloud shadow — SFN required):

1. Set your **owner identity** in the sidebar / Settings
2. **New Migration** → paste or upload SQL → Create
3. **Attach database** → Discover schema (read-only URL or Secrets Manager ARN)
4. **Run prediction** (Bedrock + memory retrieval)
5. **Proceed to shadow test** → **Start shadow test**
6. Watch lifecycle → grade + memory appear when the workflow finishes (~1–2 min)

Local mock verify is **not** exposed in the product UI. If `sfn_ready` is false,
fix `MIGRATION_WORKFLOW_ARN` and `RUN_ARTIFACTS_BUCKET`, restart the API, and
re-check `/health`.

Check wiring anytime: `python scripts/dev.py doctor`

Port / host (optional):

```bash
# Windows PowerShell
$env:DEV_PORT=8001; python scripts/dev.py restart

# macOS / Linux
DEV_PORT=8001 python scripts/dev.py restart
```

### First-time AWS stack (once per account — not for normal clones)

Only if `MIGRATION_WORKFLOW_ARN` / `RUN_ARTIFACTS_BUCKET` are missing, or Lambda
code changed. See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

```powershell
cd infra\sam
.\build.ps1
.\deploy.ps1   # writes ARN + bucket into .env
```

Until that ARN+bucket are set, **Start shadow test** is blocked in the UI
(`sfn_ready` false). The engineer-only `POST /runs/{id}/verify-local` mock path
remains on the API but is not part of the product console.

## See All Steps Working (Dev Verification)

From `backend/`:

```bash
# API + service correctness
pytest -q
python scripts/verify_api.py
python scripts/verify_phase6_schema_analysis.py
python scripts/verify_phase9_ai_prediction.py
python scripts/verify_phase10_grading_memory.py

# Full HTTP operator path (debug fake migration -> predict -> approve -> verify -> grade -> memory)
python scripts/verify_e2e_http.py
```

For durable AWS execution-plane checks (Step Functions/Lambda/S3/Secrets/CloudWatch):

```bash
python scripts/verify_phase8_full.py --skip-lambda-chain
```

For a real browser walk-through (Next.js console — **not** the retired `/ui`):

1. Open `http://localhost:3000/dashboard`
2. Create a migration (paste SQL)
3. Discover schema, run prediction, approve **Proceed**
4. Start shadow test and wait for grade + memory
5. Or inspect via `http://127.0.0.1:8000/docs` (`/runs/{id}`, `/grade`, `/memory`)

Corpus health from the terminal (no browser):

```bash
cd backend
python scripts/corpus_health.py
```

Pending embeddings (not searchable until Titan succeeds):

```bash
# Via OpenAPI / curl when authenticated with DEMO_API_KEY if set
POST /runs/memories/repair-embeddings
```

### Demo API gate

Set `DEMO_API_KEY` in the environment and send `X-API-Key` on API calls (health and docs stay public). Leave unset for open local development. Mirror the key in the UI with `NEXT_PUBLIC_DEMO_API_KEY` if needed.

### Seed a small memory corpus (demo)

```bash
cd backend
python scripts/seed_demo_memories.py
```

### Orphan sweeper

```bash
cd backend
python scripts/run_shadow_sweeper.py
```

Schedule via EventBridge → Lambda using `infra/sam/template.yaml` (see that file).

### Minimal AWS deploy

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for the full one-command sequence.

```bash
cd infra/sam
sam build
sam deploy --guided --region us-east-1
```

Then copy stack outputs into `.env`:

- `MIGRATION_WORKFLOW_ARN`
- `RUN_ARTIFACTS_BUCKET`

## Docs

- [`docs/E2E_WALKTHROUGH.md`](docs/E2E_WALKTHROUGH.md) — real SFN shadow click-path
- [`docs/DEMO_OPS.md`](docs/DEMO_OPS.md) — local start + timings
- [`docs/HOSTING.md`](docs/HOSTING.md) — API/frontend hosting + auth env
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — SAM / Step Functions deploy + promote
- [`docs/PROJECT.md`](docs/PROJECT.md)
- [`docs/API.md`](docs/API.md) — HTTP API
- [`docs/PHASE_9_AI_PREDICTION.md`](docs/PHASE_9_AI_PREDICTION.md)
- [`docs/PHASE_10_GRADING_AND_MEMORY.md`](docs/PHASE_10_GRADING_AND_MEMORY.md)
- [`docs/HACKATHON_TOOLS.md`](docs/HACKATHON_TOOLS.md) — tool narrative for judges

## License

MIT — see [`LICENSE`](LICENSE).
