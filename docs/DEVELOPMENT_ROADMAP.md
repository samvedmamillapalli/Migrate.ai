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



# **Phase 1 — Backend Foundation ✅**

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



# **Phase 2 — CockroachDB Cloud Integration ✅**

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



# **Phase 3 — Domain Model & Database Schema ✅**

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



# **Phase 4 — Repository & Service Layer ✅**

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



# **Phase 5 — REST API ✅**

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

Documented in docs/[API.md](http://API.md).

Still deferred from the original Phase 5 stretch goals:

- Clerk authentication and server-side user scoping
- Idempotency keys for POST /runs

Checkpoint:

Migration runs can be created and queried.



---



# **Phase 6 — Database Schema Discovery✅**

Goal:

Read customer database metadata.

Implemented so far (app/schema_analysis/):

- Async PostgreSQL / CockroachDB connection management
- Schema / table / column / index / constraint discovery
- Estimated row counts
- Estimated table and database sizes when the engine exposes them
- Strongly typed Pydantic metadata models (DatabaseMetadata, …)
- Production verification via scripts/verify_phase6_schema_[analysis.py](http://analysis.py)

Documented in docs/SCHEMA_[ANALYSIS.md](http://ANALYSIS.md).

Schema inspection module status: **production-ready** for read-only metadata collection.

Still remaining in this phase:

- Enforced read-only connection validation
- Active write probe that rejects write-capable credentials
- Secrets Manager storage for customer database credentials
- Persisted JSONB schema snapshot on each MigrationRun
- DatabaseConnection persistence model (application-side)

Checkpoint:

Application can inspect external PostgreSQL-compatible databases.



---



# **Phase 7 — Shadow Cluster Orchestration✅**

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

# **Phase 8 — AWS Workflow✅**

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
- run_id correlation across Lambda and CloudWatch logs
- Alarm for failed teardown or orphaned clusters

Checkpoint:

Migration execution becomes asynchronous and survives control-plane restarts.

---



  




---



# **Phase 9 — AI Prediction, Policy Checks & Recommendation Engine**

## **Goal**

Predict migration impact, detect known unsafe patterns using deterministic rules, and generate evidence-backed rollout recommendations before any execution occurs. Every execution decision remains under explicit human approval.

## **Implement**

### **1. Deterministic Risk & Policy Layer**

Run a deterministic rule engine before invoking the LLM. This layer identifies known high-risk operations and enforces organization-defined safety policies rather than relying solely on model reasoning.

Detect at minimum:

- DROP TABLE
- DROP COLUMN
- Primary key changes
- Foreign key additions
- Large index creation / index backfill candidates
- Table rewrite patterns
- Long-running backfill candidates
- Potentially destructive or backward-incompatible changes

Generate:

- risk_flags
- compatibility_risk
- requires_expand_contract
- requires_manual_review
- policy_decision (allow, allow_with_warning, block)

The policy engine is authoritative. The LLM provides analysis and recommendations, but the policy layer determines whether the workflow may proceed to shadow execution.



---



### **2. AI Prediction Engine**

Use Amazon Bedrock (Claude Sonnet) to predict migration outcomes using:

- schema snapshot
- migration SQL
- deterministic rule output
- retrieved historical memories (Phase 10)

Generate structured JSON containing:

- predicted runtime
- predicted storage impact
- predicted rollback risk
- confidence score
- risk explanation
- key assumptions
- uncertainty notes

Implementation requirements:

- Versioned prompt templates
- Model version recorded for every prediction
- Strict structured-output validation
- One bounded retry for malformed output only
- Hard failure if validation still fails

Confidence should be conservative and decrease when:

- retrieval support is weak
- schema size mismatch is high
- migration type is uncommon
- deterministic rules detect unusual risk



---



### **3. Recommendation Engine**

Generate actionable recommendations rather than simply identifying risk.

Produce:

- recommended migration strategy
- recommended rollout steps
- suggested deployment window
- rollback guidance
- monitoring checklist
- optional safer migration plan (never auto-applied)
- explanation for every recommendation

Support established migration practices including:

- expand → backfill → contract
- backward-compatible deployments
- additive schema changes before destructive cleanup
- staged backfills
- off-peak execution for heavy background work
- monitoring during schema change jobs

Recommendations must always explain *why* they are being suggested.



---



### **4. Human-in-the-Loop (HITL)**

All recommendations require explicit user approval before execution.

The system may:

- explain risks
- recommend safer rollout strategies
- generate an alternative migration plan
- recommend cancelling execution

The system must **never automatically modify or execute customer migrations.**

The user chooses between:

- original migration
- recommended migration plan
- cancel execution

Record:

- approver identity
- selected option
- timestamp
- optional override rationale



---



### **5. Explainability**

Every prediction and recommendation should be explainable.

Show:

- deterministic risk findings
- key reasoning factors
- confidence explanation
- recommendation rationale

Users should understand why the system reached its conclusion rather than receiving only a risk score.



---



### **Workflow**

Schema Snapshot

        +

Migration SQL

        ↓

Deterministic Risk & Policy Layer

        ↓

AI Prediction

        ↓

Recommendation Generation

        ↓

Human Approval (HITL)

        ↓

Shadow Execution

### **Checkpoint**

Predictions and actionable recommendations are generated before execution, deterministic policies prevent known unsafe operations from proceeding automatically, recommendations are explainable, and every execution requires explicit human approval.



---



# **Phase 10 — Grading, Agentic Memory & Continuous Improvement**

## **Goal**

Continuously improve prediction accuracy and recommendation quality using verified execution history, retrieval-augmented memory, and explicit feedback from user decisions.

## **Implement**

### **1. Prediction Evaluation**

After shadow execution, deterministically compare predictions with actual outcomes.

Track:

- runtime prediction error
- storage prediction error
- rollback prediction accuracy
- confidence calibration
- high-risk flag precision and recall
- surprise-note generation

Store:

- predicted values
- actual values
- grading result
- acceptable error bands
- calibration outcome

Evaluation should be size-tier aware so the system does not over-generalize from small shadow environments.



---



### **2. Agentic Memory**

Store execution history as reusable operational memory inside CockroachDB using:

- VECTOR embeddings
- CockroachDB vector storage
- CockroachDB distributed vector indexes
- similarity search

Each memory should contain:

- migration summary
- schema summary
- deterministic risk flags
- prediction summary
- recommendation summary
- approval decision
- execution outcome
- lessons learned
- surprise notes
- embedding vector



---



### **3. Hybrid Retrieval Pipeline**

Before every new prediction retrieve:

- previous migrations by the same user
- shared seeded migration corpus
- similar schema changes
- similar execution outcomes
- similar accepted and rejected recommendations

Rank results using:

- semantic similarity
- migration type
- schema size tier
- index count
- table complexity
- deterministic risk flags

Use hybrid retrieval rather than vector search alone to remain effective even with a smaller corpus.



---



### **4. Explainable Memory**

Every prediction and recommendation must disclose the historical evidence that influenced it.

Record:

- RetrievalLog
- similarity scores
- retrieved summaries
- source attribution
- memories included in the prompt

The system should be able to explain statements such as:

"This recommendation is based on seven similar migrations with comparable schema size and index count."

or

"Previous migrations involving large index backfills showed significantly higher runtime and storage growth."



---



### **5. Recommendation Learning**

Improve recommendations as well as predictions.

Track:

- recommendation acceptance
- recommendation rejection
- override reason
- whether runtime improved
- whether risk was reduced
- whether execution succeeded
- whether the recommendation prevented a predicted failure
- recommendation acceptance rate
- recommendation success rate

A recommendation is considered successful only if it measurably improved safety, predictability, or execution outcome compared with the original migration plan.



---



### **6. Accuracy & Learning Metrics**

Continuously compute:

- prediction accuracy trend
- confidence calibration curve
- recommendation acceptance rate
- recommendation success rate
- retrieval usefulness rate
- learning curve by migration type
- learning curve by schema size tier

These metrics demonstrate that the system becomes more reliable as additional migrations are executed.



---



### **Workflow**

Prediction

        ↓

Recommendation

        ↓

Human Approval

        ↓

Shadow Execution

        ↓

Comparison / Grading

        ↓

Memory Update

        ↓

Hybrid Retrieval

        ↓

Better Future Predictions

        ↓

Better Future Recommendations

  




---



# **Phase 11 — Frontend**

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



# **Phase 12 — Testing & Deployment**

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

