# Phase 9: AI Prediction, Policy Checks, and Recommendation Engine

This document is the authoritative context for building Phase 9. Read it fully before writing code. Where it conflicts with an assumption you would otherwise make, this document wins. Where it is silent, follow the conventions already present in the codebase from Phases 1 through 8.

---

## 1. What this phase is, and where it sits

Migration Oracle runs a closed loop: predict, verify, grade, remember. Phase 9 is the **predict** step, plus two things that wrap around it: a deterministic safety layer that runs *before* the model, and a recommendation layer that runs *after* it. Nothing in this phase executes anything against any database. Phase 9 produces analysis and asks a human what to do next.

The order of operations for a single migration run:

```
Schema snapshot (Phase 6)
        +
Migration SQL (user submitted)
        v
Deterministic Risk and Policy Layer   <- Phase 9, code only, no model
        v
Memory retrieval                       <- Phase 9 builds the interface, Phase 10 fills it
        v
AI Prediction (Bedrock call #1)        <- Phase 9
        v
Recommendation Generation (Bedrock call #2)  <- Phase 9
        v
Human approval gate                    <- Phase 9
        v
Shadow execution (Phase 7 / Phase 8)
```

Phase 9 ends at the approval gate. It does not provision clusters, does not run migrations, and does not grade anything. Grading and memory are Phase 10.

---

## 2. Framing rules that govern all code, comments, logs, and docs

These are project wide rules, not suggestions. They have cost us rework before.

**Never describe migration risk as "lock duration."** CockroachDB runs schema changes as online background jobs. It does not take the long table locks that traditional Postgres does, and the judges for this hackathon are Cockroach Labs engineers who built the system that removed them. Blast radius in this project always means four things: backfill duration, storage growth, resource saturation, and rollback safety. Any variable name, docstring, log line, prompt template, or user facing string that frames risk as locking is wrong and will need to be rewritten. If a detected pattern genuinely involves blocking behavior, describe it in terms of backfill work and resource saturation instead.

**The memory loop is the differentiator, the policy layer is not.** Static rule engines that flag DROP TABLE already exist in several tools. What no competitor does is predict a number, verify it by execution, grade itself, and improve. Phase 9 needs the deterministic layer for safety and auditability, but nothing in the code, comments, or docs should present the rule engine as the novel contribution. It is table stakes that makes the interesting part safe.

**The policy layer is authoritative over the model.** The model analyzes and recommends. It never decides whether execution may proceed. That decision comes from deterministic code.

---

## 3. Decisions already made (do not relitigate these)

These were settled deliberately. Implement them as written.

| Question | Decision |
| --- | --- |
| Should the rule engine learn from memory? | No. Purely static and deterministic, for auditability. |
| SQL parsing approach | Use `sqlglot` with the Postgres dialect. Not regex. |
| Where policies live | A YAML config file committed to the repo. Not hardcoded, not in the database. |
| Prediction units | Absolute. Plain seconds and plain MB. Do not normalize per million rows. |
| How tier awareness works | Grading segments on `ShadowCluster.scale_tier` after the fact. The prediction itself is not normalized. |
| Prediction target | The shadow run outcome only. Never a separate production outcome prediction. |
| Rollback risk shape | The existing three value enum in `prediction.py`: `low`, `medium`, `high`. |
| Is `policy_decision = block` overridable? | Yes, but only with a recorded override rationale. It is strongly worded, not a hard stop. Always logged. |
| Confidence generation | Hybrid. The model proposes a raw confidence, then deterministic code clamps or reduces it before persisting. |
| Prediction and recommendation | Two separate Bedrock calls, not one combined output. |
| Memory retrieval | Build the interface now as a stub returning empty results. Phase 10 implements it. |
| Does the recommended plan get executed? | No. The shadow cluster only ever executes the user's own original migration SQL. |
| Where approval happens | A dedicated API endpoint plus persisted approval record, verified by script. UI is Phase 11. |
| Step Functions pause | Out of scope for Phase 9. Build the gate at the database and API layer only. |

---

## 4. Component 1: Deterministic Risk and Policy Layer

This runs first, before any model call, on every submitted migration.

### 4.1 Parsing

Use `sqlglot` with `dialect="postgres"`. CockroachDB's SQL is close enough to Postgres for parsing purposes. Parse the submitted migration SQL into an AST and walk it. Do not pattern match on raw strings for anything beyond a last resort fallback.

Handle these realities:

* A single submission may contain multiple statements. Analyze each one and aggregate the findings.
* Parsing can fail on unusual or CockroachDB specific syntax. When it does, do not crash and do not silently pass. Emit a `parse_failure` risk flag, set `requires_manual_review` to true, and set `policy_decision` to at minimum `allow_with_warning`. A migration the system could not understand is not a migration the system should quietly bless.
* Record the parsed statement types on the run so they can be shown in the explainability output.

### 4.2 What to detect, at minimum

Each detection produces a structured finding, not just a boolean. A finding should carry: a stable rule identifier, a human readable title, a severity, the specific object or objects involved (table name, column name), and a short explanation of why this pattern is risky.

Required detections:

1. **DROP TABLE.** Destructive and generally irreversible without a backup.
2. **DROP COLUMN.** Destructive, and backward incompatible with any application code still reading that column.
3. **Primary key changes.** In CockroachDB a primary key change rewrites the table and rebuilds secondary indexes. High blast radius on large tables.
4. **Foreign key additions.** Requires validating existing rows against the referenced table, which is real background work proportional to table size.
5. **Large index creation and index backfill candidates.** Creating an index requires backfilling it across every existing row. Severity should scale with the row count from the schema snapshot.
6. **Table rewrite patterns.** Column type changes and other operations that force the table to be rewritten rather than modified in place.
7. **Long running backfill candidates.** Any operation whose work is proportional to row count. Adding a column with a non null default is the classic example.
8. **Potentially destructive or backward incompatible changes.** Renames, `NOT NULL` additions to existing columns, constraint tightening, and anything that breaks a deploy where old application code is still running.

Severity must be informed by the schema snapshot, not just the statement shape. `CREATE INDEX` on a table with 400 rows and `CREATE INDEX` on a table with 400 million rows are the same statement and completely different risks. The rule engine has the snapshot available; use it. Where the snapshot has no row count for a referenced table (for example, the table does not exist yet, or discovery fell back to fixture data), say so explicitly in the finding rather than assuming small.

### 4.3 Outputs

The layer must produce all of the following, persisted with the run:

* `risk_flags`: the list of structured findings described above.
* `compatibility_risk`: an assessment of whether this change breaks application code that has not been deployed yet. Use the same three value scale as rollback risk (`low`, `medium`, `high`) for consistency.
* `requires_expand_contract`: boolean. True when the change is backward incompatible in a way that the expand, backfill, contract pattern would solve.
* `requires_manual_review`: boolean. True on parse failure, on any high severity finding, or on any condition the policy file marks as review requiring.
* `policy_decision`: exactly one of `allow`, `allow_with_warning`, `block`.

### 4.4 The policy YAML file

Policy lives in a committed YAML file. The engine loads it at startup and validates it on load, failing loudly on a malformed policy file rather than falling back to permissive defaults.

The file should express, per rule: whether the rule is enabled, its base severity, the thresholds that escalate severity (for example, row count boundaries), and what `policy_decision` the rule contributes. Aggregation across multiple findings should follow a documented precedence: the most restrictive contributing decision wins, so any single `block` produces an overall `block`.

Design the schema of this file so a human can read it and understand the safety posture in under a minute. It is a demo asset as much as a config file. Document its schema in the phase documentation you write at the end.

### 4.5 On `block`

`block` prevents the workflow from proceeding *automatically*. It does not remove human agency. A user may still override a block by explicitly choosing to proceed and supplying an override rationale, which is recorded on the approval record along with their identity and a timestamp. The distinction to implement: nothing proceeds past a block without a human decision that is attributable and logged.

---

## 5. Component 2: AI Prediction Engine

### 5.1 Model and inputs

Use Amazon Bedrock with Claude Sonnet. The prediction call receives:

* the schema snapshot from Phase 6,
* the migration SQL as submitted,
* the full structured output of the deterministic layer (findings, flags, decision),
* retrieved historical memories from the Phase 10 interface (empty for now).

Giving the model the deterministic findings matters. The model should reason *with* the rule engine's conclusions rather than rediscovering them, and its explanation should be consistent with them.

### 5.2 Structured output

The model must return JSON containing:

* `estimated_duration_seconds`: absolute seconds, matching the existing `Prediction.estimated_duration_seconds` column.
* `estimated_storage_mb`: absolute MB, matching the existing `Prediction.estimated_storage_mb` column.
* `rollback_risk`: one of `low`, `medium`, `high`, matching the existing `RollbackRisk` enum.
* `confidence_score`: the model's raw proposal, before deterministic adjustment.
* `risk_explanation`: prose explaining the reasoning.
* `key_assumptions`: the assumptions the estimate depends on.
* `uncertainty_notes`: what the model is unsure about and why.

Predictions describe **the shadow run**, not the user's production database. Make this explicit in the prompt itself, because a model given a production schema snapshot will naturally reason about production timings. The prompt must state the shadow context, including the scale tier the shadow will be seeded at, so the number the model produces is the number Phase 10 can actually grade against.

### 5.3 Implementation requirements

* **Versioned prompt templates.** Prompts live as files in the repo with an explicit version identifier. Changing a prompt means bumping the version, not editing in place silently.
* **Model version recorded on every prediction.** The existing `Prediction` model has a `model_version` field. Populate it with both the Bedrock model identifier and the prompt template version, so a prediction can always be traced to exactly what produced it.
* **Strict structured output validation.** Validate against a schema (Pydantic, consistent with the rest of the codebase). Do not accept partial or coerced output.
* **Exactly one bounded retry**, and only for malformed output. Feed the validation errors back into the retry so the model can correct itself. Do not retry on model errors, throttling, or timeouts at this layer; those are separate concerns with their own handling.
* **Hard failure if validation fails twice.** Do not fall back to a default prediction, do not persist a partial prediction, and do not let the run silently proceed. Fail the run with a clear reason. A wrong prediction that gets graded is worse than no prediction, because it poisons the memory store.
* Emit a metric when a repair retry occurs, so prompt drift is visible rather than invisible.

### 5.4 Confidence: hybrid computation

The model proposes a confidence. Deterministic code then adjusts it downward before persisting to `confidence_score`. The model's raw proposal should be retained alongside the adjusted value so the adjustment is auditable and explainable.

Confidence must be reduced when any of these four measurable conditions hold:

1. **Weak retrieval support.** Few or no similar past migrations were retrieved, or their similarity scores are low. With Phase 10 stubbed, this condition is always true right now, so every prediction should currently carry visibly reduced confidence. That is correct behavior, not a bug, and it is the honest representation of a system with no memory yet.
2. **Schema size mismatch.** The shadow scale tier differs substantially from the real table sizes in the snapshot.
3. **Uncommon migration type.** The statement shape is rare relative to what the system has seen.
4. **Unusual risk detected by the deterministic layer.** High severity findings, or a parse failure.

Each applied adjustment must be recorded with its reason, so the explainability output can state plainly why confidence is what it is. Adjustments only ever reduce confidence; deterministic code never raises the model's proposal.

### 5.5 Cost and latency budget

Target under roughly 15 to 20 seconds and under roughly $0.05 to $0.10 per prediction call at typical prompt sizes. This is a per migration operation, not a high frequency one, so this budget is comfortable. Keep it in mind when deciding how much memory context to inject once Phase 10 is real; retrieved memories are the input most likely to grow unbounded.

---

## 6. Component 3: Recommendation Engine

A **separate** Bedrock call from the prediction, with its own versioned prompt template. Separating them means either can be improved without disturbing the other, and a recommendation failure does not invalidate a valid prediction.

### 6.1 Inputs

The recommendation call receives everything the prediction call received, plus the validated prediction itself. It reasons about what to do given the predicted outcome, rather than re deriving the outcome.

### 6.2 Outputs

* `recommended_strategy`: the overall approach.
* `rollout_steps`: ordered, concrete steps.
* `suggested_deployment_window`: when to run it and why.
* `rollback_guidance`: how to undo it, or an honest statement that it cannot be cleanly undone.
* `monitoring_checklist`: what to watch while the schema change job runs.
* `safer_alternative_plan`: optional, and never auto applied.
* `rationale`: every recommendation carries an explanation. A recommendation without a stated reason is a failure of this component, not an acceptable output.

### 6.3 Strategies the engine should know

The prompt should establish these as the vocabulary of good practice:

* expand, then backfill, then contract,
* backward compatible deployments where old and new application code both work during the transition,
* additive schema changes first, destructive cleanup later as a separate change,
* staged or batched backfills rather than one large operation,
* running heavy background work off peak,
* monitoring the schema change job while it runs rather than assuming success.

### 6.4 The safer alternative plan is described, not executable

This is a firm boundary. The alternative plan is prose steps plus illustrative SQL snippets. It is **not** a complete, runnable migration artifact, and nothing in the system will ever execute it.

The reason is safety and scope. Generating a full replacement migration and running it would mean the system executes SQL the user did not write, which is a far larger correctness and trust decision than this phase is scoped for. If the user prefers the recommended approach, they take the guidance and author their own migration, then submit that as a new run.

Consequently, when a user selects the recommended plan at the approval gate, that selection is recorded as a decision, and the run does not proceed to shadow execution with AI generated SQL. Treat "chose recommended plan" as an end state for that run, with the user expected to submit a new run containing their revised migration.

### 6.5 When to skip the recommendation call

*(Assumption, flagged for override.)* If policy returns `block` and the user has already cancelled, there is nothing to recommend and the call is wasted cost. Skip the recommendation call in that case only. In every other case, including `block` where the user has not yet decided, generate recommendations, since a blocked migration is exactly the case where the user most needs to know what a safer path looks like.

---

## 7. Component 4: Human in the Loop

### 7.1 The core rule

The system never automatically modifies or executes a customer migration. Every execution requires an explicit human decision recorded before it happens. This is the single most important behavioral property of the phase.

### 7.2 The gate

Introduce an `awaiting_approval` state in the run status lifecycle. Note that this value does not currently exist in `MigrationRunStatus` and must be added, along with valid transitions into and out of it, consistent with the existing validated status transition logic in the service layer.

After prediction and recommendation complete, a run moves to `awaiting_approval` and stops. It does not proceed to shadow execution on its own.

### 7.3 The decision

The user chooses exactly one of:

* proceed with the original migration,
* accept the recommended plan (which, per section 6.4, ends this run rather than executing anything),
* cancel execution.

### 7.4 What gets recorded

Persist an approval record containing, at minimum: the run it belongs to, the approver's identity, the option selected, a timestamp, and an optional override rationale. The rationale becomes effectively mandatory when the user proceeds against a `policy_decision` of `block`; enforce that at the API layer with a clear error rather than accepting a silent override.

Follow the existing repository and service layer patterns from Phase 4 for persistence and transaction boundaries. Approval decisions are audit records: they should be append only in spirit, never overwritten.

### 7.5 The endpoint

Expose a dedicated endpoint, following the existing `runs.py` conventions and the established `PATCH /runs/{id}` plus service layer `update_status` pattern. `POST /runs/{id}/approve` is the expected shape. Map domain errors to HTTP statuses the same way existing routes do. Reject approvals for runs not in `awaiting_approval` rather than silently accepting them.

Verification is by script, matching how Phases 6, 7, and 8 were each validated before any UI existed. The frontend for this is Phase 11.

### 7.6 What is explicitly out of scope here

Wiring an actual Step Functions `waitForTaskToken` pause into the state machine is a Phase 8 follow up, not Phase 9 work. Phase 9 builds the state, the record, the endpoint, and the gate logic at the database and API layer. The workflow integration comes later. Leave a clearly marked integration point so that follow up is straightforward, and note in the phase documentation exactly what remains to be wired.

---

## 8. Component 5: Explainability

A user should finish reading the output understanding *why*, not just *what*. Every run's analysis should be able to surface:

* the deterministic findings, each with its rule identifier, the object involved, and why that pattern is risky,
* the policy decision and which specific findings drove it,
* the model's key reasoning factors, assumptions, and uncertainty notes,
* the confidence value, the model's raw proposal, and every deterministic adjustment applied with its reason,
* which retrieved memories informed the prediction (empty for now, but the structure should exist so Phase 10 populates it rather than requiring a redesign),
* the rationale attached to each recommendation.

Persist this such that it can be rendered later without re running anything. Explainability that requires a second model call to reconstruct is not explainability.

---

## 9. Memory retrieval interface (stub for Phase 10)

Define the interface Phase 10 will implement, and implement it now as a stub that returns an empty result set.

Requirements:

* The prediction path must work correctly with zero memories. No crash, no special casing scattered through the code, no fabricated placeholder memories.
* Zero retrieved memories triggers the weak retrieval confidence reduction from section 5.4, and that fact should appear in the uncertainty notes and explainability output.
* The interface should carry, per retrieved memory, enough to be useful in a prompt and displayable in a memory panel: the past migration, what actually happened, any recorded surprise, and a similarity score.
* Log every retrieval attempt from day one, including empty ones. Phase 10's demo depends on being able to show which memories influenced which prediction, and retrofitting that logging later is more work than adding it now.

Do not implement embeddings, vector storage, or similarity search in this phase. That is Phase 10.

---

## 10. Prerequisites and environment

**Bedrock model access is not yet enabled on the AWS account.** This is a hard prerequisite for any live prediction call and requires explicitly requesting access to the Anthropic models in the Bedrock console, in the correct region, before any invocation will succeed. Build the phase so this is a configuration step rather than a blocker:

* Read the model identifier and region from configuration, never hardcoded.
* Add the required environment variables to `.env.example` with explanatory comments.
* Fail with a clear, actionable error message when model access is not yet granted, rather than an opaque AWS exception.
* Make the Bedrock client injectable so the prediction and recommendation paths can be tested without live model access.

Region is `us-east-1`, consistent with the rest of the project's AWS resources.

---

## 11. Data model changes required

The current schema has no place to store several Phase 9 outputs. Expect to add columns and at least one table, with Alembic migrations, following the CockroachDB compatible patterns already established in Phase 3.

At minimum, storage is needed for:

* the deterministic layer's outputs: risk flags, compatibility risk, the expand and contract boolean, the manual review boolean, and the policy decision,
* the recommendation output, including its rationale fields,
* the approval record described in section 7.4,
* the new `awaiting_approval` status value and its transitions,
* the raw model confidence alongside the adjusted confidence, plus the applied adjustments,
* the prompt template version alongside the existing `model_version`.

Prefer extending existing models where the relationship is genuinely one to one with a run or a prediction, and introduce new tables where the data is an independent record with its own lifecycle, such as approvals. Match the existing conventions for UUID primary keys, timestamp mixins, relationships, and indexes.

---

## 12. Out of scope for Phase 9

Do not build any of the following, even if it seems adjacent:

* embeddings, vector indexing, similarity search, or grading of any kind (Phase 10),
* Step Functions integration for the approval pause (Phase 8 follow up),
* any frontend or UI (Phase 11),
* executing AI generated SQL anywhere, ever,
* predicting production database outcomes as distinct from shadow outcomes,
* normalized per million row prediction units,
* rule severities that learn or adapt from past outcomes.

---

## 13. Definition of done

Phase 9 is complete when all of the following are true:

1. A submitted migration is parsed with `sqlglot` and analyzed by the deterministic layer, producing risk flags, compatibility risk, the two booleans, and a policy decision, driven by a committed YAML policy file.
2. A parse failure produces a flagged, review requiring outcome rather than a crash or a silent pass.
3. A Bedrock prediction call returns strictly validated structured JSON with absolute duration and storage estimates, a three value rollback risk, explanation, assumptions, and uncertainty notes, with exactly one bounded repair retry and a hard failure after that.
4. Confidence is the model's proposal after deterministic reduction, with every adjustment recorded and explainable, and currently reduced on every run because retrieval is stubbed.
5. A separate Bedrock recommendation call produces strategy, steps, window, rollback guidance, monitoring checklist, an optional described safer alternative, and a rationale for every recommendation.
6. The run enters `awaiting_approval` and does not proceed on its own.
7. An approval endpoint records approver identity, selected option, timestamp, and optional override rationale, requires a rationale when overriding a block, and rejects approvals for runs in the wrong state.
8. The memory retrieval interface exists, returns empty, is logged, and degrades confidence honestly.
9. Everything above is verifiable by a script in `scripts/`, following the pattern of the existing phase verification scripts, with clear pass and fail output.
10. Phase documentation exists in `docs/` covering what was built, the policy file schema, required environment variables including the Bedrock access prerequisite, any earlier phase changes made, and exactly what remains to be wired for Step Functions.

---

## 14. Assumptions flagged for override

These were chosen in the absence of an explicit decision. They are reasonable defaults, not settled policy.

1. New database columns and an approval table are in scope for this phase, since the existing schema cannot store the outputs.
2. The recommendation call is skipped only when policy blocks and the user has already cancelled.
3. Prompt templates are versioned files in the repository rather than database stored records.
4. `compatibility_risk` uses the same three value scale as rollback risk, for consistency.
5. Selecting the recommended plan ends the run rather than queuing a modified execution, since no executable artifact exists for it.