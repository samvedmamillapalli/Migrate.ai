Phase 7: Shadow Cluster Orchestration — Knowledge & Context
What this phase is
Shadow cluster orchestration is the "verify" step of Migration Oracle's core loop (predict → verify → grade → remember). A shadow cluster is a temporary, disposable CockroachDB Cloud cluster that exists only to run one migration safely, measure what really happens, and then get destroyed. The real customer database is never touched by a migration; it is only read (structure) in Phase 6. All actual migration execution happens on the shadow.
Framing rules that govern all code and copy

Never use the word "lock" to describe migration blast radius. CockroachDB runs schema changes as online background jobs; it does not take long table locks the way traditional Postgres does. The judges are Cockroach Labs engineers who built the system that eliminated long-running locks. Blast radius in this project always means: backfill duration, storage growth, resource saturation, and rollback safety. Any variable name, comment, log line, or doc string that frames risk as "lock duration" is wrong for this project and should be avoided.
The novelty being protected is the closed loop, not shadow testing alone. Shadow testing by itself is not novel (Neon, PlanetScale, Eugene, pgfence do versions of it). What makes this project different is that it predicts numbers, verifies them, grades itself, and remembers. Phase 7 is infrastructure that serves that loop; keep it clean and reliable but do not let it become the whole story.

How this connects to the rest of the app

Phase 6 (already built) produces a DatabaseMetadata schema snapshot of the customer's real database (table names, column types, row counts, index info, sizes) via read-only inspection. Phase 7 consumes that snapshot to know what shape and scale of data to recreate on the shadow.
Phase 7 does NOT do prediction (Phase 9), grading (Phase 10), or AWS Step Functions orchestration (Phase 8). For now, Phase 7 should be callable directly from the service layer and from a verification script, so it can be tested end to end by hand. Phase 8 will later wrap this in Step Functions.
The existing models from Phase 3 include ShadowCluster. Phase 7 should use and, if necessary, extend that model to track lifecycle state.

CockroachDB Cloud tier and cost reality

Use CockroachDB Basic (formerly Serverless). It is billed by actual usage (Request Units and storage), not by how long a cluster exists. A pay-as-you-go account gets $15/month of free resource usage plus $400 in free credits for new accounts. A short-lived shadow that seeds a modest table, runs one migration, and is destroyed costs a negligible amount of Request Units, comfortably inside the free allowance for hackathon-scale volume.
Because billing is usage-based, the shadow's max-lifetime sweeper is about hygiene (never leaking orphaned clusters) rather than avoiding large time-based charges. Keep the sweeper anyway; leaked clusters are sloppy and the sweeper is itself a Production Readiness talking point.
Provision shadow clusters in a single region: AWS us-east-1. It is the most widely used and best-supported region and colocates with the AWS services (Bedrock, Lambda, S3) used elsewhere in the project.

Which CockroachDB tool Phase 7 uses, and why it matters for judging
Phase 7 must provision and destroy clusters using the ccloud CLI, not the raw REST API. The hackathon requires using at least two CockroachDB tools, and the ccloud CLI is explicitly one of the qualifying tools (alongside Distributed Vector Indexing, which the project uses in Phase 10). The ccloud CLI emits JSON on every command, which makes it script-friendly. The project writeup should state that the agent provisions and tears down shadow clusters via the ccloud CLI.
ccloud CLI authentication and credentials — how to check what you have and how to get it
The orchestration needs a way to authenticate to CockroachDB Cloud non-interactively (from backend code), which means a service account API key, not just an interactive login.
To check whether you already have what you need:

Check for an existing database connection string (you already have this): it looks like postgresql://user:pass@host:26257/db?sslmode=verify-full. This is for connecting to a database, NOT for provisioning clusters. It is necessary but not sufficient for Phase 7.
Check for a CockroachDB Cloud API key: in the CockroachDB Cloud Console, go to the organization's Access Management / Service Accounts area and look for an existing service account with an API key. If a key was already created, it would have been shown only once at creation, so if nobody saved it, you'll need to create a new one.
Check your local machine for existing ccloud auth: if the ccloud CLI has been used before, running ccloud auth list or checking for a stored credential will show it. A fresh environment will have none.

To get a service account API key if you don't have one:

In the CockroachDB Cloud Console, open the organization settings and find Service Accounts (under Access Management).
Create a service account with a role that permits cluster creation and deletion (Cluster Creator / appropriate admin-level cloud role; scope it as narrowly as the console allows while still permitting create and delete).
Create an API key for that service account. Copy it immediately and store it in a secret manager or .env that is never committed. It will not be shown again.
This API key is what the backend uses to authenticate ccloud CLI commands non-interactively.

Store the API key as an environment variable (for example CCLOUD_API_KEY) and never log it or commit it. Later phases move it into AWS Secrets Manager; for now .env is acceptable but must be gitignored.
Lifecycle the orchestration must implement
Create → await ready → seed (recreate schema shape + load synthetic rows at the matched scale tier) → (baseline measure) → run migration → (measure) → destroy. Teardown must run on every path, including failure and timeout. A separate sweeper destroys any cluster tagged as belonging to this app that is older than the max lifetime (30 minutes), catching cases where the process itself died.
Constraints and known risks for this phase

Provisioning latency is the biggest unknown. Measure it for real in a spike before promising any timing in the demo. Do not hardcode optimistic assumptions.
Concurrency cap: allow at most 2 simultaneous shadow clusters. Runs beyond that should queue.
Pre-warmed cluster pool: NOT built in this phase. Leave a clearly documented interface/TODO where a warm pool could later replace on-demand creation if latency proves too slow. Do not implement it now.
Every shadow cluster must be tagged/labelled at creation (for example with the app name and the run id) so the sweeper can identify and reap orphans reliably.
Teardown must be idempotent: destroying an already-destroyed cluster returns success, not an error.

Definition of done (this phase's checkpoint)
Temporary clusters are created and destroyed automatically, including on failure paths, driven through the ccloud CLI, wired into the existing service layer, tested via a verification script, with a working concurrency cap of 2, a sweeper for orphans, and a documented (not built) warm-pool fallback.