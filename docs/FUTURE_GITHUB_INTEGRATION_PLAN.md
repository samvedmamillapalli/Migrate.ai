# Future Feature Plan: GitHub Pull-Request Integration

Status: **planning only, not built. Depends on `docs/FUTURE_WORKSPACES_PLAN.md`.**
Companion document: `docs/FUTURE_CONCURRENT_SHADOW_PLAN.md`.

## Summary and Recommendation

**Do not build this before August 18, and it cannot be first regardless of
how appealing it is as a demo beat.** This feature's core mechanism —
discovering a customer's schema without a human pasting a connection URL in
the moment — requires a stored, reusable database connection tied to a
repository, and no such concept exists in this codebase today (see
`docs/FUTURE_WORKSPACES_PLAN.md`'s investigation: `connection_secret_arn` is
currently created fresh per-run, never reused). Building GitHub integration
before workspaces exist means either inventing a parallel, one-off "stored
connection for a repo" mechanism that workspaces will later duplicate or
replace, or blocking on a live human pasting a connection URL at PR-webhook
time — which defeats the entire premise of "automatically run a migration
through the full loop." Document this precisely and build it after
workspaces exist, not before.

## Current State

Zero existing GitHub-related code anywhere in this repository — verified by
grep across `backend/app` and `frontend/oracle/apps/web` for `github`,
`octokit`, `webhook`, `pull_request`, `GitHubApp`, and by extension. The only
matches found were unrelated: a URL reference to
`github.com/cockroachlabs/cockroachdb-skills` inside an MCP investigation
tool's description string (`app/shadow/blast_radius_investigator.py`), and
`openapi-typescript`'s standard boilerplate `export type webhooks =
Record<string, never>` (emitted for every OpenAPI spec regardless of
content, not a real feature). `docs/githubs.md` exists but is unrelated to
PR/webhook integration — it is the open-source **corpus** source list
(`docs/backendfix.md`: *"Source list lives in githubs.md. It is a list of
repos and documented incidents, not data"*), used for seeding the memory
corpus with documented migration incidents, not for watching a live
repository. No prior planning document for this feature exists.

## Proposed Mechanism: GitHub App + webhook, not polling

**Recommend a GitHub App subscribed to `pull_request` webhook events** over
a polling approach.

Reasoning:

- A GitHub App gets fine-grained, repo-scoped installation permissions
  (contents: read, checks: write, pull requests: write) rather than a
  personal-access-token's broad account-wide scope — this matters
  specifically because this app already treats credential scope carefully
  everywhere else (`connection_secret_arn` pointers, never raw passwords at
  rest; discover is read-only against the *customer's* database). A GitHub
  App is the same posture applied to the *code* side of the integration.
- Real-time: a webhook fires the moment a PR is opened/synchronized, which
  is what "automatically run a migration through the full loop whenever a
  PR contains a database migration file" actually requires. Polling would
  mean iterating every linked repository's open PR list on some interval,
  which is both slower (a PR sits unprocessed until the next poll) and
  wasteful against GitHub's REST rate limits once more than a handful of
  repos are linked.
- Posting results back (check run + comment, below) requires the same
  installation-scoped write permissions a GitHub App already has — polling
  wouldn't avoid needing an App/token for that half of the feature anyway,
  so there's no scope-reduction benefit to polling even for the "detect"
  half.

This does introduce real new infrastructure this project doesn't have yet: a
public HTTPS endpoint to receive GitHub's webhook POST (API Gateway + a new
Lambda, or a route on the existing FastAPI app if it's reachable from the
internet at demo time), webhook signature verification
(`X-Hub-Signature-256`), and GitHub App credential storage (an App private
key + installation tokens) — none of which exist in `infra/sam/` today.

## Proposed Detection Heuristic

**File path pattern matching this project's own Alembic versions folder
convention** (`backend/alembic/versions/*.py`) is the most defensible
starting heuristic — it is exactly correct for detecting a migration inside
*this project's own repository*, which is what a live demo would plausibly
showcase (this app watching its own or a structurally-identical repo).

State plainly, not glossed over: **this heuristic does not generalize to
arbitrary customer repositories using different migration tooling** (Django
migrations, Rails `db/migrate`, Flyway, Liquibase, raw hand-written `.sql`
files with no framework at all, or a monorepo with migrations nested
somewhere non-standard). Building a general-purpose "detect any migration
tool's file convention" classifier is a real, separate research problem —
explicitly out of scope for this plan, not something to half-solve with a
brittle multi-framework path-matching table. The heuristic should be
configurable per linked repository (a glob pattern stored alongside whatever
repo-to-workspace link exists — see the dependency section below) so a
demo/pilot repo can be pointed at the right pattern without the backend
needing to guess it, rather than trying to auto-detect the migration
framework in use.

## Proposed Approval Model — recommend (a), flag (b) explicitly

There is no human sitting in the UI clicking Approve in real time for a
PR-triggered run — the person opening the PR may not even be the person who
should approve a shadow run against a real (if disposable) database
connection. Two real options:

**(a) — recommended.** Run discover and predict automatically on webhook
receipt, and **hold at the existing approval gate** exactly as every other
run does today. Post the prediction, recommendation, and policy decision as
a PR comment (or check run summary) with a link that takes a human into the
app to review and click Approve, using the exact same
`POST /runs/{id}/approve` flow, the exact same three-option decision
(`proceed` / `accept_recommended` / `cancel`), and the exact same mandatory
override-rationale requirement when `policy_decision=block` that every other
run already goes through. **This requires zero change to the approval model
itself** — the run created by the webhook is, from the approval system's
perspective, indistinguishable from a run created through the UI. The only
new work is *where the run comes from* (a webhook payload instead of a form
submission) and *where the resulting prediction gets surfaced* (a PR comment
in addition to the app).

This also fits the ASL's existing, locked design constraint directly:
`infra/stepfunctions/migration_workflow.asl.json`'s own top comment states
*"Prediction and human approval are API-side gates before this workflow
starts — not `waitForTaskToken`"* and `docs/backendfix.md` records
*"Step Functions does not pause for approval... A `waitForTaskToken` pause is
deliberately deferred."* A PR-triggered run needs exactly the same
gate-before-start behavior any other run needs — nothing about the
asynchronous, no-human-in-the-UI-yet nature of a PR trigger requires
inventing a different approval mechanism, it just requires a different
place to *ask* for approval (a PR comment/check-run link) than a UI button
click.

**(b) — flagged, not recommended, needs an explicit human decision.**
Auto-approving anything below some risk threshold without a human in the
loop is a real, material change to a decision recorded as locked in
`docs/backendfix.md`: *"Approval is `POST /runs/{id}/approve` with a
persisted decision record... `policy_decision=block` is strongly worded but
overridable, always with a recorded rationale. It is never a hard stop."*
The entire premise of that design is that a human always makes the final
call, with an audit trail, even when the deterministic policy layer is
confident. Auto-approval — even scoped to "only when policy_decision=allow
and confidence is high" — removes the human from that specific path
entirely, which is a different safety posture than what's currently locked,
not an extension of it. This plan takes no position on whether that
tradeoff is ever worth making; it only insists that if it's ever built, it
must be an explicit, separately-approved decision, never a default anyone
lands on by building the "convenient" version of PR-triggered runs without
noticing the approval model changed underneath it.

## Proposed Result Reporting

A GitHub **Check Run** (`conclusion`: `success` / `failure` / `neutral`,
mapped from `policy_decision` and, once graded, the actual outcome) plus a
**PR comment** containing:

- The prediction summary (`estimated_duration_seconds`,
  `estimated_storage_mb`, `rollback_risk`) and confidence score, matching
  what the UI's assessment panel already shows.
- The recommendation summary (steps + illustrative SQL — never
  fully-generated executable SQL, per the locked recommendation-engine
  decision in `docs/backendfix.md`, which applies identically here).
- `policy_decision`, and the specific `risk_flags` that produced it.
- A direct link into the app (`/dashboard/migrations/{run_id}`) — this is
  the human's entry point to actually approve or cancel, per the approval
  model above.
- Once the run reaches a terminal state (shadow-verified and graded): a
  follow-up comment or check-run update with the actual measured outcome vs.
  the prediction — the same predicted-vs-measured comparison the UI already
  renders, posted back to where the human is actually looking (the PR), not
  only inside the app.

## The Credential Problem — explicit dependency on Workspaces

Stated plainly, as the task requires: **`discover` needs a read-only
connection to a real database, and a pull request carries no such thing.**
A PR is just a diff against a git repository; it has no relationship to any
database connection unless something in this system already knows "PRs
against repository X should be tested against database Y." That mapping
does not exist today, and building it as a one-off ("store a connection
string keyed by GitHub repo") would create a second, parallel
stored-connection concept alongside whatever `docs/FUTURE_WORKSPACES_PLAN.md`
eventually builds — duplicated now, needing to be reconciled or migrated
away from later.

**This is why GitHub integration is downstream of workspaces, not
independent of it.** The dependency, concretely: a linked repository needs
to resolve to a `workspace_id` (a new `github_repo_full_name` column on
`Workspace`, or a small join table if one repo should ever map to more than
one workspace), and the webhook handler's job — once workspaces exist — is
simply: receive `pull_request` event → detect a migration file via the
configured heuristic → resolve the repo to its linked workspace → create a
`MigrationRun` with `workspace_id` set and `connection_secret_arn` defaulted
from `workspace.connection_secret_arn` (exactly the wiring
`docs/FUTURE_WORKSPACES_PLAN.md` already proposes for the UI-driven create
flow, reused here for the webhook-driven one) → run discover/predict → hold
at approval → report back to the PR.

Without workspaces, the only honest alternative is requiring a human to
paste a connection URL into some other new UI *before* GitHub integration
can do anything with a given repo — which is just workspaces again, built
smaller and worse, under a different name.

## Feasibility Before August 18

Not recommended, for two independent reasons, either one sufficient on its
own:

1. It depends on Feature 1 (Workspaces), which this plan and
   `docs/FUTURE_WORKSPACES_PLAN.md` both recommend against building before
   the deadline.
2. Even ignoring the dependency, it requires new infrastructure this project
   doesn't have (a public webhook receiver, GitHub App credential handling,
   webhook signature verification) layered on top of the existing SAM stack,
   which is real infrastructure work with its own failure modes to get
   right — not a good candidate to rush in the same window as whatever else
   is still open before a hard deadline.

## Open Questions

- Auto-approval below a risk threshold (option (b) above) — needs an
  explicit human decision if it's ever wanted; this plan recommends against
  it and recommends (a) instead.
- One repo → one workspace, or should a monorepo be able to map different
  migration-file paths to different workspaces (e.g. a repo with two
  services, each owning a different database)? This plan assumes one
  repo → one workspace for simplicity; the richer mapping is a real question
  if the eventual customer base has monorepos, but not knowable without a
  real customer to design against.
- Who gets notified/tagged in the PR comment when a human decision is
  needed — the PR author, a fixed reviewer list, whoever owns the linked
  workspace? Not decidable without knowing how workspace membership/roles
  eventually work, which doesn't exist yet.
- Does a failed/blocked migration (`policy_decision=block`, or a shadow run
  that fails) actually fail the GitHub check run (blocking merge if the repo
  requires passing checks), or only post a warning comment? This is a real
  product decision about how much authority this tool gets over a team's
  merge process, not a technical one.

## Prompt

Paste the following into a fresh session, after both this plan and
`docs/FUTURE_WORKSPACES_PLAN.md` are ready to act on (workspaces should be
built and verified first):

```
Read docs/FUTURE_GITHUB_INTEGRATION_PLAN.md in full before doing anything
else, then confirm docs/FUTURE_WORKSPACES_PLAN.md has actually been
implemented and verified (real workspace_id column on migration_runs, real
stored connection reuse) — this feature is not buildable correctly without
it; do not attempt a shortcut where a repo's connection is stored somewhere
other than a real workspace, even temporarily, since this plan explicitly
warns that creates a second, duplicated stored-connection concept to
reconcile later.

Also re-read docs/backendfix.md's "Decisions already locked" section,
specifically the Human in the loop and Recommendation engine subsections —
this plan's approval model (option (a): auto-predict, hold at the existing
approval gate, report to the PR, human approves via a link into the app)
was chosen specifically because it requires no change to those locked
decisions. Do not build auto-approval (option (b) in this plan) unless a
human has explicitly signed off on it as a deliberate, separate decision —
if that hasn't happened, build (a) only and raise (b) as a question rather
than deciding it yourself.

Build, in this order: (1) GitHub App registration + webhook receiver
(new Lambda + API Gateway route, or a route on the existing FastAPI app if
it has a stable public URL by then) with signature verification, (2) the
repo-to-workspace link (github_repo_full_name on Workspace, or a join table
if the open question about monorepos needs a many-to-one shape), (3) the
migration-file detection heuristic, configurable per linked repo rather
than hardcoded to this project's own alembic/versions/ convention, (4)
webhook handler: detect -> resolve workspace -> create MigrationRun with
workspace-defaulted connection_secret_arn -> discover -> predict -> stop at
awaiting_approval exactly like every other run, (5) the PR comment + check
run reporting, both the initial prediction/recommendation post and the
terminal predicted-vs-measured follow-up.

Verify end to end with a real test repository and a real PR containing a
real migration file matching the configured heuristic: confirm the webhook
fires, the run is created under the correct workspace with the correct
connection, the PR receives a comment/check-run with real (not fabricated)
prediction data and a working link into the app, a human approving through
that link correctly starts the shadow workflow, and the terminal outcome
gets posted back to the same PR. Run the full backend test suite and
frontend typecheck before reporting done.
```
