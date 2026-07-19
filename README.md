# Migration Oracle

**Predict → verify → grade → remember.** An agentic migration advisor that scores its own predictions against real shadow runs and retrieves graded memories for the next attempt.

Built for the [CockroachDB × AWS Hackathon](https://cockroachdb-ai.devpost.com/).

## Stack

| Layer | Choice |
| --- | --- |
| API | FastAPI (Python) |
| Control-plane DB | CockroachDB Cloud |
| UI | Static debug console at `/ui` (no Next.js) |
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

## Quick start

```bash
cp .env.example .env
# set DATABASE_URL (CockroachDB Cloud connection string)

cd backend
python -m venv .venv
# Windows: .\.venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --app-dir .
```

Open `http://127.0.0.1:8000/ui` and `http://127.0.0.1:8000/docs`.

### Demo API gate

Set `DEMO_API_KEY` in the environment and send `X-API-Key` on API calls (health and `/ui` stay public). Leave unset for open local development.

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

- [`docs/PROJECT.md`](docs/PROJECT.md) — product thesis
- [`docs/API.md`](docs/API.md) — HTTP API
- [`docs/PHASE_9_AI_PREDICTION.md`](docs/PHASE_9_AI_PREDICTION.md)
- [`docs/PHASE_10_GRADING_AND_MEMORY.md`](docs/PHASE_10_GRADING_AND_MEMORY.md)
- [`docs/HACKATHON_TOOLS.md`](docs/HACKATHON_TOOLS.md) — tool narrative for judges

## License

MIT — see [`LICENSE`](LICENSE).
