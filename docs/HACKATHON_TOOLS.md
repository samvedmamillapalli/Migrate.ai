# Hackathon tools narrative

Judging expects clear use of **≥2 CockroachDB tools** and **≥1 AWS service**.

## CockroachDB (exactly two, proven in demo)

| Tool | Where it lives | What to show on camera |
| --- | --- | --- |
| **Distributed Vector Indexing** | Alembic `h3c9f6a2b041`, index `ix_migration_memories_embedding`, hybrid retrieval in `backend/app/memory/retrieval.py` | Predict a second similar migration; inspector shows retrieved memories + ranks/attribution in `explainability.memory` |
| **Managed MCP / job watch** | IDE: `.cursor/mcp.json`. Runtime: `backend/app/shadow/job_watch.py` polled during ExecuteMigration | Shadow run artifacts / outcome include `job_watch` rows (`SHOW JOBS`) + `mcp_tool_attribution()` strings |

We keep `SHADOW_PROVIDER=ccloud_api` as the default provision path (REST automation). The second CRDB tool for judging is **MCP/job-watch**, not flipping the default to `ccloud` CLI. Set `SHADOW_PROVIDER=ccloud` only if you deliberately demo the CLI.

## AWS

| Service | Role |
| --- | --- |
| Amazon Bedrock | Predict, recommend, Titan embeddings, optional grade prose |
| AWS Lambda | Workflow step handlers under `backend/app/lambdas/` |
| AWS Step Functions | `infra/stepfunctions/migration_workflow.asl.json` |
| Amazon S3 | Run artifacts |
| AWS Secrets Manager | Customer connection secrets |
| Amazon CloudWatch | Accuracy metrics published on grade + orphan alarms |

## Closed-loop gate

SFN is started only after Phase 9 prediction + human `proceed` (`WorkflowOrchestrationService.require_prediction_and_approval`).
