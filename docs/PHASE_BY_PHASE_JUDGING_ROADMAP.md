# Phase-by-Phase Roadmap, Cross-Referenced Against Judging

This follows the exact 12 phases already laid out in
`docs/DEVELOPMENT_ROADMAP.md` — nothing renamed or reorganized. For each
phase: what it actually built, which of the 5 judging categories it feeds,
where it honestly stands today, and what to check or improve before demo
day. The 5 judging categories, for reference:

**A** = Agentic Memory Design · **T** = Technical Implementation ·
**R** = Real-World Impact · **P** = Production Readiness ·
**C** = Creativity & Originality

Nothing in this doc has been built yet as a result of writing it — this is a
checklist to work through, not a record of new work.

---

## Phase 1 — Backend Foundation
**What it built:** The basic skeleton — the web server, settings/config
system, logging, and a database connection layer. Nothing user-facing.

**Feeds:** T (a little), P (a little) — this is plumbing, not something a
judge evaluates directly.

**Where it stands:** Done, stable, not a risk.

**Check before judging:** Nothing. Leave it alone.

---

## Phase 2 — CockroachDB Cloud Integration
**What it built:** The connection from your backend to your real
CockroachDB Cloud database, with proper encrypted (SSL) connections.

**Feeds:** T, P — this is "does the app actually talk to real CockroachDB,"
which judges will assume but rarely verify directly.

**Where it stands:** Done and working — confirmed live during this session
(a real schema change was applied against it).

**Check before judging:** Nothing new. Just make sure whatever copy of the
app judges see points at the same real database, not a stale local one.

---

## Phase 3 — Domain Model & Database Schema
**What it built:** The actual data tables — migration runs, predictions,
results, shadow clusters, and so on — plus the versioned scripts
(Alembic migrations) that create and update those tables safely.

**Feeds:** T, P — this is the foundation everything else sits on, including
the memory system judges will score under Agentic Memory.

**Where it stands:** Done, and actively still growing — new columns were
added this session for the shadow live view. All changes go through proper
versioned migration files, which is exactly the discipline a judge checking
"is this real engineering or a demo hack" would want to see.

**Check before judging:** Nothing to fix. If you want a talking point: "every
schema change in this app went through a reviewable migration file, the same
discipline we're asking users to trust us with."

---

## Phase 4 — Repository & Service Layer
**What it built:** The internal code organization — keeping "talk to the
database" code separate from "business rules" code. Invisible to users.

**Feeds:** T — this is code-quality/architecture, which matters for the
"Technical Implementation" score if a judge reads code, but isn't something
you demo.

**Where it stands:** Done, consistently followed throughout the whole
project, including every feature added this session.

**Check before judging:** Nothing. Not demo material.

---

## Phase 5 — REST API
**What it built:** The actual endpoints the frontend (and any outside tool)
calls — create a migration run, look one up, list them, update status.

**Feeds:** T, P.

**Where it stands:** Done, and expanded well past the original list (there
are now roughly 25 endpoints, including live-streaming updates added this
session). Two things the roadmap doc itself flagged as originally deferred —
real login and duplicate-request protection — are **both now actually done**:
real login (Clerk) is live, and idempotency wasn't separately needed once
the workflow gating logic was built.

**Check before judging:** The roadmap doc still says these are "deferred" —
that line is now out of date and should be corrected so nobody reading it
thinks login is still missing.

---

## Phase 6 — Database Schema Discovery
**What it built:** The part that reads a customer's real database structure
(tables, columns, indexes) safely, without ever being able to write to it.

**Feeds:** R (this is the "connect your database" step every real user goes
through), P (the read-only safety guarantee matters a lot for trust), T.

**Where it stands:** Done, and substantially upgraded this session — the
connect screen was reordered to come first, got a copyable "how to create a
safe read-only login" helper, and now shows step-by-step progress instead of
a spinner while it works. The roadmap's original "still remaining" list
(read-only enforcement, safe credential storage, saved schema snapshots) is
now fully done, not just planned.

**Check before judging:** Update the roadmap doc's "still remaining" list —
it's stale, everything on it is finished. Also make sure the one-click demo
database (for judges without their own database) is switched on for the
version judges will actually open — this is the single biggest thing
standing between a judge and being able to use the product at all.

---

## Phase 7 — Shadow Cluster Orchestration
**What it built:** The heart of the product — spinning up a real, temporary
CockroachDB cluster, loading a copy of the customer's table structure onto
it, running the actual migration on it, and then deleting the cluster
automatically, even if something goes wrong partway through.

**Feeds:** C (this *is* the differentiator — verify on a real disposable
database instead of just guessing), T, P (guaranteed cleanup, cost caps),
R (this is what makes the prediction trustworthy instead of just an AI
opinion).

**Where it stands:** Done and proven — a real judge-facing test run is
documented (`demo/SHADOW_PROOF.md`) with real timings. This session added
real live job-tracking (capturing CockroachDB's own background job as it
runs) and a real before/after structural diff of what changed, which is new
capability past what this phase originally asked for.

**Check before judging:** Run at least one full shadow test on the actual
judge-facing deployment before demo day to confirm the new live-tracking
code behaves the same way in that environment as it did locally — this
specific piece could not be fully tested end-to-end during this session due
to an unrelated local environment issue (documented in `backendfix.md`).

---

## Phase 8 — AWS Workflow
**What it built:** Moved the slow parts (provisioning a cluster, running a
migration) out of the web server and into AWS Step Functions + Lambda, so
they run reliably in the background, survive restarts, and always clean up
after themselves.

**Feeds:** P (this is the core "production readiness" story), T.

**Where it stands:** Done. Guaranteed cleanup, retry logic, and an automatic
"sweeper" that catches anything that slipped through are all real and
working. Real CloudWatch alarms exist for failure cases too.

**Check before judging:** The CloudWatch alarms are real but currently
invisible anywhere in the actual product — worth one sentence in the pitch
("we alarm on orphaned clusters and failed teardowns") since it's true and
currently unclaimed.

---

## Phase 9 — AI Prediction, Policy Checks & Recommendation Engine
**What it built:** Three layers working together: (1) a rule-based checker
that catches known-dangerous SQL patterns *before* asking any AI, (2) an AI
model (Claude via Bedrock) that predicts how long a migration will take and
how much storage it'll use, and (3) a second AI call that recommends a
safer rollout plan. A human always has to approve before anything runs for
real.

**Feeds:** T, R, C (the "rules first, AI second, human always decides" shape
is a real design point worth stating out loud, not just building silently).

**Where it stands:** Done and working, and the wording of the AI's
explanations was rewritten this session — they were previously long and
full of jargon; they're now capped at one or two plain sentences.

**Check before judging:** Run a fresh prediction before demo day so the
rewritten explanation style is what's actually on screen, not old
already-generated text sitting in the database from before the rewrite.

---

## Phase 10 — Grading, Agentic Memory & Continuous Improvement
**What it built:** After a shadow run finishes, the system grades its own
prediction against what actually happened, and stores that graded outcome
as a searchable memory (using CockroachDB's vector search) so future
predictions can learn from real history instead of starting from zero every
time.

**Feeds:** A — this is the whole category. This phase *is* "Agentic Memory
Design."

**Where it stands:** Done, and this session found and fixed a real bug in
the accuracy numbers being shown — two of the headline statistics were
quietly measuring the wrong thing (comparing unrelated groups of runs
instead of a consistent one). That's fixed now, plus a bug in a related
precision/recall calculation that was silently under-counting failures.

**Check before judging:** This is your strongest category — lean on it hard
in the pitch. One honest caveat to state out loud rather than hope nobody
asks: the memory collection is intentionally small (11 real sourced
examples plus your own test runs), not thousands. Say that's a deliberate
choice, not an unfinished one.

---

## Phase 11 — Frontend
**What it built:** Everything a person actually sees and clicks — the
dashboard, the migration submission flow, the live view of a shadow test
running, and the history of past runs.

**Feeds:** R, C, and indirectly all the others — this is what a judge
actually watches during the demo, so it's the delivery mechanism for every
other category's story.

**Where it stands:** This phase saw the most work this session by far:
- Reordered the migration-submission flow so connecting a database comes
  before pasting SQL (previously backwards).
- Added a working one-click demo database option for judges without their
  own database.
- Rebuilt the live shadow-execution view from a generic progress bar into
  something that shows real CockroachDB job status, a real before/after
  structural diff of the schema, and a live event log — fed by a real
  live-streaming connection instead of the old repeated polling.
- Fixed a broken "watch live" button, cleaned up a duplicate on-screen
  panel bug, hid the raw internal user ID, and made the accuracy numbers on
  the dashboard match what they claim to measure.
- Two sections that were previously always-expanded are now collapsed by
  default with a toggle, so the screen reads cleaner.

**Check before judging:** Do one full click-through on the actual
judge-facing deployment, start to finish, before demo day — this is the
single highest-value hour you can spend, since this phase changed the most.

---

## Phase 12 — Testing & Deployment
**What it built:** Automated tests, a way to package the app (Docker), and
automatic checks that run on every code change (CI/CD).

**Feeds:** P, T.

**Where it stands:** Partially done. What exists and is real: 33 automated
tests that all currently pass, a working Docker packaging setup, and
automatic CI checks on both the backend and frontend. What the original plan
asked for but isn't built: broader integration tests (tests that check
multiple pieces working together, not just one at a time), a formal written
security review, and a "batch corpus runner" that would produce a real
chart of accuracy improving over time from a large batch of test runs.

**Check before judging:** You don't need to build the missing pieces before
demo day — they're "nice to have," not blockers. What you should actually
do instead: rehearse the demo itself start to finish at least once, on the
real judge-facing deployment, under a timer. That's the one item from this
phase's original list that directly determines how the demo goes.

---

## One-page summary

| Phase | Feeds | Status | Before judging |
|---|---|---|---|
| 1. Backend Foundation | T, P | Done | Nothing |
| 2. CockroachDB Cloud | T, P | Done | Nothing |
| 3. Domain Model & Schema | T, P | Done | Nothing |
| 4. Repository & Service Layer | T | Done | Nothing |
| 5. REST API | T, P | Done | Fix stale "deferred" note in the roadmap doc |
| 6. Schema Discovery | R, P, T | Done | Confirm demo database is switched on for judges |
| 7. Shadow Cluster Orchestration | C, T, P, R | Done | Run one real end-to-end test on the judge deployment |
| 8. AWS Workflow | P, T | Done | Mention real CloudWatch alarms in the pitch |
| 9. AI Prediction & Recommendation | T, R, C | Done | Run a fresh prediction so new plain-English text shows |
| 10. Grading & Agentic Memory | A | Done | Lead with this category; state small-corpus size on purpose |
| 11. Frontend | R, C | Done, most recently changed | Full click-through rehearsal on judge deployment |
| 12. Testing & Deployment | P, T | Partially done | Timed full demo rehearsal, not more test-writing |

If you only have time for three things: **Phase 6's demo database switch,
Phase 11's full click-through, and Phase 12's timed rehearsal.** Everything
else is either already solid or is a nice-to-have, not a blocker.
