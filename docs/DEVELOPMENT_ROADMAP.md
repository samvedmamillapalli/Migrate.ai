# Migration Oracle - Development Roadmap

## Project Goal

Migration Oracle is an AI-powered database migration prediction platform.

The system should:

1. Accept SQL database migrations.

2. Predict migration runtime, storage impact, rollback risk, and confidence using AI.

3. Provision a temporary CockroachDB shadow cluster.

4. Execute the migration safely.

5. Measure actual execution metrics.

6. Compare predictions with reality.

7. Learn from every execution using an agentic memory system.

8. Improve future predictions over time.

---

# Development Principles

- Build incrementally.

- Every phase must compile and run before moving to the next.

- Prefer clean architecture over shortcuts.

- Keep business logic separate from persistence.

- Generate production-quality code.

- Maintain CockroachDB compatibility.

- Use SQLAlchemy 2.0.

- Use Alembic for every schema change.

- Explain architecture only when requested.

- Keep user database credentials out of CockroachDB and application logs.

- Add structured `run_id` correlation to logs as soon as migration runs are exposed.

- Design every long-running workflow to be idempotent and safely retryable.

- Treat cleanup of temporary infrastructure as a required workflow outcome.

---

# Phase 1 — Backend Foundation ✅

Completed.

Includes:

- Project structure

- FastAPI

- Configuration

- Logging

- Dependency injection scaffolding

- Health endpoint

- SQLAlchemy foundation

- Alembic foundation

- Environment management

Checkpoint:

Backend starts successfully.

---

# Phase 2 — CockroachDB Cloud Integration ✅

Completed.

Includes:

- CockroachDB Cloud cluster

- SQL user

- SSL configuration

- Database connectivity

- Health verification

Checkpoint:

Backend successfully connects to CockroachDB Cloud.

---

# Phase 3 — Domain Model & Database Schema ✅

Completed.

Models:

- MigrationRun

- Prediction

- ExecutionResult

- LearnedOutcome

- ShadowCluster

Implemented:

- UUID primary keys

- Timestamp mixins

- Relationships

- Foreign keys

- Indexes

- Alembic migrations

- CockroachDB-compatible schema

Checkpoint:

Database schema successfully migrated.

---

# Phase 4 — Repository & Service Layer ✅

Completed.

Includes:

- BaseRepository

- MigrationRunRepository

- MigrationRunService

- Explicit async SQLAlchemy session dependency

- Transaction boundaries owned by the service layer

- Validated MigrationRun status transitions

- Unit tests for repository and service behavior

Checkpoint:

Business logic separated from persistence.

---

# Phase 5 — REST API ✅

Completed.

Includes:

- GET /

- GET /health

- POST /runs

- GET /runs/{id}

- GET /runs

- PATCH /runs/{id}

- Pydantic request/response models

- Domain error → HTTP status mapping

- Pagination for GET /runs

Documented in `docs/API.md`.

Still deferred from the original Phase 5 stretch goals:

- Clerk authentication and server-side user scoping

- Idempotency keys for `POST /runs`

Checkpoint:

Migration runs can be created and queried.

---

# Phase 6 — Database Schema Discovery ✅

Goal:

Read customer database metadata.

Completed (`app/schema_analysis/` + application wiring):

- Async PostgreSQL / CockroachDB connection management

- Schema / table / column / index / constraint discovery

- Estimated row counts

- Estimated table and database sizes when the engine exposes them

- Strongly typed Pydantic metadata models (`DatabaseMetadata`, …)

- `DatabaseConnection` application model (URL built internally; credentials never logged)

- Read-only validation: DDL write probe (always rolled back) + DML privilege scan +
  session `default_transaction_read_only`

- CockroachDB dialect fallback on the discovery path

- Serialization-failure (40001) retry on service commits

- JSONB schema snapshot + discovery metadata persisted on `MigrationRun`

- Configurable connection and discovery timeouts

- List API omits full `schema_snapshot` (`has_schema_snapshot` instead)

- Production verification via `scripts/verify_phase6_checklist.py`,
  `scripts/verify_phase6_schema_analysis.py`, and `scripts/verify_phase6_remaining.py`

Documented in `docs/SCHEMA_ANALYSIS.md`.

Schema discovery application status: **complete for Phase 6 inspection + persistence**
(excluding AWS Secrets Manager).

Still deferred from this phase:

- Secrets Manager storage for customer database credentials

- Dedicated HTTP discovery endpoint (service is wired; route deferred to a later phase)

Checkpoint:

Application can inspect external PostgreSQL-compatible databases.

---

# Phase 7 — Shadow Cluster Orchestration

Goal:

Execute migrations safely.

Implement:

- Early technical spike for ccloud provisioning latency and free-tier limits

- CockroachDB Cloud API integration

- Shadow cluster provisioning

- Schema loading

- Migration execution

- Automatic cleanup

- Sweeper for orphaned clusters

- Maximum cluster lifetime

- Concurrency cap and queued runs

- Pre-warmed cluster pool fallback if on-demand provisioning is too slow

Checkpoint:

Temporary clusters are created and destroyed automatically, including failure paths.

---

# Phase 8 — AWS Workflow

Goal:

Move long-running work into AWS.

Implement:

- Lambda

- Step Functions

- Secrets Manager

- CloudWatch

- S3

- Durable run state in CockroachDB and Step Functions

- Guaranteed teardown catch paths

- Per-step retries with idempotency protection

- `run_id` correlation across Lambda and CloudWatch logs

- Alarm for failed teardown or orphaned clusters

Checkpoint:

Migration execution becomes asynchronous and survives control-plane restarts.

---

# Phase 9 — AI Prediction

Goal:

Predict migration outcomes.

Implement:

- Amazon Bedrock

- Prompt templates

- Structured JSON responses

- Runtime prediction

- Storage prediction

- Rollback prediction

- Confidence scoring

- Strict structured-output validation

- One bounded retry for malformed model output

- Model and prompt version recorded with every Prediction

Checkpoint:

Predictions generated before execution.

---

# Phase 10 — Grading & Agentic Memory

Goal:

Learn from previous executions.

Implement:

- Deterministic prediction-versus-actual grading rules

- Size-tier-aware accuracy thresholds

- Prediction error and surprise-note generation

- Embedding generation

- Similarity search

- Memory retrieval

- Learning updates

- Replace `LearnedOutcome.embedding_id` placeholder with CockroachDB VECTOR storage

- CockroachDB distributed vector index

- RetrievalLog model recording which memories informed each Prediction

- User history plus shared seeded-corpus retrieval

- Accuracy curve computed from real completed runs

Workflow:

Prediction

↓

Execution

↓

Comparison

↓

Memory Update

↓

Better Future Prediction

Checkpoint:

Predictions improve using historical executions, and every retrieved memory is auditable.

---

# Phase 11 — Frontend

Goal:

Build user interface.

Pages:

- Dashboard

- Submit Migration

- Run Details

- History

- Settings

Stack:

- Next.js

- React

- TypeScript

- Tailwind CSS

- shadcn/ui

Demo-critical components:

- Prediction shown before verification completes

- Live shadow-cluster execution status

- Prediction-versus-actual comparison

- Retrieved-memory panel with similarity scores

- Accuracy-over-time chart

Checkpoint:

Complete end-to-end application.

---

# Phase 12 — Testing & Deployment

Implement:

- Unit tests

- Integration tests

- Migration downgrade/upgrade tests

- Mid-run failure and guaranteed-cleanup tests

- Security review for IAM, secrets, logging, and read-only enforcement

- Seeded corpus ingestion from licensed open-source migration histories

- Synthetic migrations for corpus coverage gaps

- Batch corpus runner producing a real accuracy curve

- Docker

- CI/CD

- Monitoring

- Production deployment

- Two-run concurrency and queue behavior test

- Fresh-browser demo verification

- Feature freeze and under-three-minute demo rehearsal

Checkpoint:

Production-ready demo.

---

# Explicit MVP Boundaries

Build for the hackathon:

- Single AWS region

- Basic user authentication and per-user data isolation

- Maximum two concurrent shadow runs with queued overflow

- Free-tier or small shadow clusters with clearly stated size limitations

- Shared seeded corpus plus user-specific migration history

Document as future work:

- Billing

- Multi-region execution

- Very large production-scale database simulation

- Shared team memory

- GitHub integration

- Deeper compliance automation