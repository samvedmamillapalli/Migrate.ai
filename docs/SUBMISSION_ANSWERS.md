# Devpost submission answers — Migration Oracle

Copy-paste ready. Every claim below was checked against the actual code, not
written from memory.

---

## Q1. How did you meaningfully integrate the selected CockroachDB and AWS components?

Migration Oracle predicts what a database migration will do, then **actually
proves it** by spinning up a real, disposable CockroachDB Cloud cluster, running
the migration on it, grading the prediction against what really happened, and
remembering the lesson so the next prediction is smarter. Every component below
does real work on that loop — remove any one and the loop breaks.

**CockroachDB**

- **CockroachDB Cloud** — stores all app state, and is also the thing under
  test: each run provisions a brand-new throwaway cluster through the Cloud API
  and destroys it minutes later.
- **Distributed Vector Index** — past migrations are stored as 1024-dimension
  embeddings with a real `CREATE VECTOR INDEX`, so the agent recalls a similar
  migration even when the SQL is worded completely differently.
- **Changefeeds** — a live `CREATE CHANGEFEED` streams the migration's events
  out of the shadow cluster as it runs, which is how the UI shows progress
  rather than a spinner.
- **Managed MCP Server** — an MCP client lets the AI agent investigate the
  blast radius of a change by asking the database questions itself.
- **Serializable isolation** — makes the "only N shadow clusters at once" limit
  safe under concurrent runs without any locking code of our own.

**AWS**

- **Step Functions** — orchestrates the seven-step verification workflow and
  guarantees cleanup runs even when a step fails, so no cluster is ever leaked.
- **Lambda** — eight functions do the work: discover schema, provision, load,
  execute, measure, grade, clean up, plus a sweeper.
- **Bedrock** — Claude writes the prediction and the grade; Titan turns each
  lesson into the embedding that powers memory search.
- **S3** — stores schema snapshots, execution reports, and changefeed output.
- **Secrets Manager** — customer and shadow database credentials never touch a
  database row or a log line.
- **CloudWatch + EventBridge** — real alarms on failed cleanups, and a
  15-minute sweeper that reaps any orphaned cluster.
- **IAM** — every Lambda gets its own least-privilege role; only one can reach
  Bedrock, only one can delete a secret.
- **Lightsail** — hosts the live app.

---

## Q2. What date did you start this project? (MM-DD-YY)

**07-05-26**

(The submission period opened 06-30-26. The first commit on 07-05-26 was an
empty repository scaffold — a README and a .gitignore — with substantive
development beginning 07-17-26.)

---

## Q3. Please explain any pre-existing code or work incorporated into the Project.

All application logic — backend, database schema, AI pipeline, and AWS
infrastructure — was written from scratch during the submission period. Two
AI-generated static page designs were pulled in on 07-31-26 and used **purely as
a visual reference**: they contained no backend, no API calls, and no logic, and
only their layout and styling were adapted into our own Next.js app. We also
installed CockroachDB's official skills pack (`cockroachlabs/cockroachdb-skills`)
as documentation for our AI assistants, plus the usual frameworks and libraries
(FastAPI, Next.js, SQLAlchemy, Clerk, shadcn/ui).

---

## Q4. Feedback on the CockroachDB AI tools or features (optional)

The official CockroachDB skills pack was genuinely useful — having the database's
own guidance available to our AI assistant caught real design problems early
instead of at debug time. Two things cost us the most time and would be worth
calling out more loudly in the docs: a vector index needs prefix columns that
match how you actually filter, or queries silently fall back to a full scan
with no error and no warning; and on the Basic tier several introspection
surfaces are gated, so per-table size numbers quietly come back empty. The
Managed MCP Server was the highlight — letting the agent query the database
directly turned our blast-radius analysis from guesswork into something it
could actually check.

---

## Q5. Which AI tools have you leveraged while working on this project?

We used **Claude Code** (Claude Opus 5 and Sonnet 5) as the main development
assistant and **Cursor** for in-editor work — both are credited as co-authors in
our commit history. We also connected two MCP servers during development:
**CockroachDB's Managed MCP Server**, which the shipped product itself uses at
runtime, and **Playwright MCP** for driving the real UI during testing. Inside
the product, **Amazon Bedrock** (Claude for predictions and grading, Titan for
embeddings) does the actual AI work.
