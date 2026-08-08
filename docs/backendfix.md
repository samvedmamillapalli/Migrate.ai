# backendfix.md

Shared working memory for the Migration Oracle build. Every task reads this
first and updates it before finishing. If something in here is wrong, fix it
here rather than working around it silently.

## Project

Migration Oracle. CockroachDB x AWS hackathon submission.
Predicts the blast radius of a schema migration, verifies the prediction on a
real disposable shadow cluster, grades the prediction against measured reality,
and stores the graded outcome as memory that sharpens future predictions.

Deadline: August 18.
Team: two people. Samved owns all backend and infrastructure.

The differentiator, the thing no competitor does: the closed loop.
Predict, verify on real infrastructure, grade, remember. Existing tools
(Bytebase, Squawk) do static rule checks and stop there. Protect this loop
above all else. Anything that weakens it is the wrong tradeoff.

## Current state

- Backend: Phases 1 through 10 code complete.
- AWS: Shared stack `migration-oracle` is `UPDATE_COMPLETE` (redeployed
  2026-07-25). Physical sweeper Lambda is `migration-oracle-shadow-sweeper`
  (EventBridge scheduled). Manual invoke with `{}` returns
  `{swept_db_rows:[], swept_provider_clusters:[], errors:[], orphan_candidates:0}`
  — `require_run=False` is live.
- Bedrock: working. Prediction uses Haiku 4.5 (local `.env`); Titan embeddings
  work. Recommendation is a separate Bedrock call. Predict explainability includes
  `bedrock_traces.prediction` with `attempts` + `repair_retried`.
- Shadow: `SHADOW_PROVIDER=ccloud_api`, `SHADOW_MAX_CONCURRENT=2`,
  `SHADOW_APP_TAG=migration-oracle`. Real BASIC clusters provision with
  `labels.app` / `labels.run`, execute, and tear down (~58s visible lifetime).
  Mid-flight abort: `POST /runs/{id}/abort-workflow` stops SFN and runs cleanup
  explicitly (ASL Cleanup does not run on StopExecution alone).
- Legacy `/ui` StaticFiles mount **retired**. Operators use Next.js
  (`frontend/oracle`, `npm run dev` on :3000).
- New frontend wired through real predict → proceed → SFN shadow → grade →
  memory → second predict. Prefer matching `NEXT_PUBLIC_API_BASE_URL` to the
  live API port (8001/8002). CORS must include both `localhost:3000` and
  `127.0.0.1:3000`; set `CORS_ORIGINS` when a public frontend URL exists.
- Shadow UI: `ShadowLiveView` (2026-07-28 rebuild) — SSE-driven 3-band live
  view (lifecycle rail / stage panel / event log) + schema diff + cost strip;
  doubles as the replay view for finished runs (no mock verify fallback;
  fake-migration debug still gated, demo-database button is not). Full
  Shadow Execution page also has a real before/after row-sample panel
  (2026-07-29) — up to 20 real synthetic rows per referenced table, matched
  by primary key across before/after.
- Ops: `docs/DEMO_OPS.md` (Windows start, demo timing ~5–7 min, cost note,
  abort). Chaos driver: `backend/scripts/judge_chaos_checks.py` (fail-fast
  predict ceilings; `JUDGE_SKIP_DUAL=1` to avoid dual-cloud spend).
- Demo readiness: **demo-ready for the closed-loop beat**. Remaining human items:
  public frontend URL for CORS; exact USD from Cockroach invoice.

## Decisions already locked. Do not relitigate these.

Policy layer
- Deterministic rules are strictly static. Severity is never tuned by memory.
  Auditability wins over a slightly better learning narrative.
- Rules live in a YAML file in the repo, not hardcoded and not per user in the DB.
- SQL parsing uses sqlglot, not regex. Regex cannot reliably detect table
  rewrites or backfill candidates.
- policy_decision=block is strongly worded but overridable, always with a
  recorded rationale. It is never a hard stop.

Prediction
- Units are absolute seconds and MB. Grading becomes tier aware by segmenting on
  ShadowCluster.scale_tier after the fact, not by normalizing beforehand.
- Predictions target the shadow run only, never the user's production database.
  Production prediction is ungradeable and out of scope.
- Rollback risk is a three value enum: low, medium, high.
- Confidence is hybrid. The model proposes a raw value, then deterministic code
  clamps it based on four measurable signals: weak retrieval, size mismatch,
  uncommon migration type, unusual risk flags.
- Prediction and recommendation are two separate Bedrock calls with
  independently versioned prompt templates.

Recommendation engine
- Output is described steps plus illustrative SQL snippets. NEVER fully
  generated executable migration SQL.
- The shadow cluster only ever executes the user's own original migration_sql.
  AI generated SQL is never executed. This is a hard safety line.

Identity and auth
- CORRECTED 2026-07-28 (was stale): Clerk auth is real and live
  (`SessionAuthMiddleware`, `app/api/middleware_auth.py` — Bearer token
  required on non-public routes whenever `AUTH_ENABLED` or Clerk keys are
  configured; frontend wires `@clerk/nextjs`). owner_identity is still a plain
  string end to end (set from the verified Clerk JWT, or passed through
  directly when auth is off), matching the approver_identity pattern.
- Retrieval scopes to the requesting owner plus the reserved corpus identity
  __migration_oracle_corpus__. That constant must exist in exactly one place in
  the codebase and be imported everywhere else.

Human in the loop
- Approval is POST /runs/{id}/approve with a persisted decision record.
- Three options: proceed, accept_recommended, cancel. There is no "reject".
- Status transitions: proceed leads to running, accept_recommended leads to
  completed with no shadow run, cancel leads to failed.
- Step Functions does not pause for approval. Approval gates at the DB and API
  layer, and the workflow only starts after a human has approved. A
  waitForTaskToken pause is deliberately deferred.

Infrastructure
- Provisioning is a ZIP Lambda calling the CockroachDB Cloud REST API
  (SHADOW_PROVIDER=ccloud_api). NOT a container image, NOT the ccloud CLI. The
  CLI is interactive browser auth only and cannot authenticate in Lambda.
- Grading and memory writing hook into the persist results path so the loop
  closes automatically, plus a manual POST /runs/{id}/grade for testing.
- Prediction is API side, not a Step Functions state. The ASL is:
  discover, provision, load, execute, collect, persist, cleanup.
- Region is us-east-1 for all AWS services.

## Frontend and backend vocabulary mismatch

RESOLVED for the Next app via an explicit mapping module:
`frontend/oracle/apps/web/lib/api/map-run.ts`.

Backend remains the source of truth. The UI no longer invents statuses.

### Final mapping decisions

| UI concern | Backend source | Mapping |
|---|---|---|
| Status badge | `MigrationRun.status` | Show backend enum + human label (`pending` → Pending, …). Never invent EXECUTING / REJECTED / APPROVED. |
| Workflow line | `workflow_status` | Shown beside status (`not_started` … `aborted`). |
| Process strip | derived from status (+ workflow) | create → predict → approve → shadow → grade → remember via `mapProcessStages`. |
| Assessment | `explainability.prediction`, `explainability.confidence`, top-level `recommendation`, `policy_decision`, `risk_flags`, `compatibility_risk` | `mapAssessment`. No fabricated benefits / four-way riskBreakdown. |
| Confidence reduction | `explainability.confidence.adjustments[]` | Show each `reason_code` + `reason` + `amount` when `wasReduced`. |
| Retrieval | `explainability.memory` | Ranked memories, similarity, attribution signals, `empty_vs_never_attempted` / `weak_retrieval`. Plain-text DVI callout. |
| Actions | ApprovalDecision | Proceed / Accept recommended plan / Cancel. Optional override rationale; required when `policy_decision=block` and decision is proceed (UI also asks for accept_recommended). `start_workflow: false` on approve; separate Start shadow button. |
| Shadow path | `/health.integrations.sfn_ready` | If true: `start-workflow` + poll `sync-workflow`. Else (or on config failure): `verify-local`. |
| Outcome | grade + execution-result + shadow-cluster + memory | `mapComparisons` for predicted vs actual; no invented deltas. |
| Dual DB chrome | none | Removed. Model is SQL + connection secret ARN + shadow CRDB. |
| Identity | `owner_identity` | Sidebar + Settings localStorage field. Approver uses the same string. |
| Polling | no streaming | `usePolling`: 2.5s, backoff after 60s to 8s, 30m ceiling, pause when tab hidden, stop on terminal. |

### Historical mismatch table (for context)

| Old mock frontend expected | Backend actually has |
|---|---|
| EXECUTING, VERIFIED, APPROVED, REJECTED | pending, predicting, awaiting_approval, running, completed, failed, plus workflow_status |
| assessment, riskBreakdown, benefits, concerns | prediction, recommendation, explainability, policy_decision, risk_flags |
| Approve / Reject buttons | proceed / accept_recommended / cancel |
| A phase machine: provisioning, cloning, executing | SFN status + pipeline-progress + shadow-cluster + execution-result |
| Live streaming updates | No streaming. Polling only. |
| Clerk style OAuth login | Soft owner_identity plus optional X-API-Key |
| Postgres to Cockroach source/target selection | SQL plus connection plus shadow CRDB |

## Known endpoints

Verify against the live OpenAPI spec rather than trusting this list.
Committed snapshot: `frontend/oracle/apps/web/lib/api/openapi.json`.
Regenerate types: from `apps/web`, `npm run gen:api` (after refreshing openapi.json
from a running API or `app.openapi()`).

GET /health
POST /runs
GET /runs
GET /runs/{id}
PATCH /runs/{id}
POST /runs/debug/fake-migration
POST /runs/{id}/discover
POST /runs/{id}/predict
POST /runs/{id}/approve
POST /runs/{id}/start-workflow
POST /runs/{id}/sync-workflow
POST /runs/{id}/verify-local
POST /runs/{id}/closed-loop
GET /runs/{id}/pipeline-progress
GET /runs/{id}/model-traces
GET /runs/{id}/grade
GET /runs/{id}/memory
GET /runs/{id}/execution-result
GET /runs/{id}/shadow-cluster
GET /runs/{id}/shadow-cluster/stream (SSE; ?token= for EventSource auth)
GET /runs/metrics/accuracy (?owner_identity=)
GET /memories
GET /memories/health

Note: GET /runs/{id} does **not** embed a top-level `prediction` object.
Prediction numbers live under `explainability.prediction` and confidence under
`explainability.confidence`. The ORM prediction row is not serialized on the run.

## The corpus

Source list lives in githubs.md. It is a list of repos and documented
incidents, not data. The ingestion pattern already exists and works:

1. Pick one migration plus a documented outcome (GitHub issue or blog post).
2. Store it as JSON under backend/data/open_source_corpus/.
3. ensure_open_source_corpus() seeds it into memory with a Titan embedding on
   API startup.
4. scripts/seed_open_source_corpus.py --verify-retrieval confirms it is
   retrievable.

Currently seeded: multiple open-source corpus JSON entries under
backend/data/open_source_corpus/ (Temporal, Airflow, Superset, PG patterns,
etc.), integrity-labeled and excluded from accuracy metrics.

IMPORTANT INTEGRITY RULE: corpus entries are real documented incidents but they
are NOT graded runs. Nobody predicted them and measured the error. They must be
clearly distinguishable from genuine graded outcomes, excluded from accuracy
metrics, and labeled as such in the UI. Do not let them inflate any number that
implies the system has verified history it does not have.

Memory list/detail API now surfaces `not_a_graded_run`, `source_url`,
`ui_label`, `integrity_kind` from `grade_summary.integrity` so the UI can badge
corpus rows without guessing from owner alone.

## The demo beat that must work

Retrieval must be able to surface a memory that shares a MECHANISM with the
current migration despite sharing almost no SQL vocabulary. Example pair:

  ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
  CREATE INDEX idx_orders_region ON orders (region)

Different statement type, different table, near zero lexical overlap, but both
trigger a full row backfill and both scale with row count the same way.

This only works if the embedded text is composed from the migration summary,
the risk narrative, the lessons learned, and the surprise note, with raw DDL as
a minority component at most. If embedding text is DDL dominant, retrieval
matches on vocabulary instead of meaning and this beat falls flat.

## Known defects to verify and fix

- Possible owner_identity mismatch. An older seeding path may have written rows
  as 'demo-corpus' instead of the reserved constant, making them invisible to
  retrieval. Check for both values. (Seeding path now rekeys legacy demo-corpus.)
- Table naming: real table is `migration_memories`.
- Rows may exist without embeddings, or without scale_tier and migration_type,
  which degrades hybrid retrieval to pure vector similarity. Memory health UI
  surfaces these loudly.
- Graded runs now exist for `judge-demo` after the 2026-07-25 PATH1 loop;
  accuracy overview must still stay honest for owners with zero grades.
- `GET /runs/{id}/pipeline-progress` clears once the run leaves `predicting`
  (no stale predict progress during shadow).
- Missing-table SQL emits deterministic risk flag `missing_referenced_table`
  with policy `block` when a schema snapshot exists.

## Working rules for every task

- Read this file before starting. Update it before finishing.
- Never fabricate data. No placeholder memories, no synthetic similarity
  scores, no invented history. Empty states must read as genuinely empty.
- Everything must behave correctly with zero memories and zero graded runs, and
  degrade visibly rather than silently.
- Read the actual code before assuming a path, a shape, or a convention.
- If earlier phase code needs changing, do it, and flag the change and the
  reason in the Change Log below.
- Prefer fixing the root cause over adding a workaround.

## Change Log

### 2026-08-08 — GitHub OAuth identity built, closing the last frontend/backend gap

Systematic audit of every function in `lib/api/endpoints.ts` against the
live `/openapi.json` found exactly one real gap:
`/api/github/{status,install,disconnect}` — "who is this GitHub identity,"
for workspace-invite matching (e.g. showing a confirmed account instead of
a typed handle). **Distinct from the GitHub App used for PR-integration
webhooks** — a different credential entirely (OAuth client_id/secret vs.
an App's JWT-signing private key), never used to act on any repo, scoped
`read:user` only.

Also found: the same samrita commit that pulled in the new analytics
charts (2026-08-07f) had **also** stripped the working Connect/Disconnect
UI out of `dashboard/settings/page.tsx` and replaced it with a static
"COMING SOON" badge, for the same reason as the workspace-invites
regression caught in that entry — their branch predates this feature
existing on either side. This one wasn't caught during that merge because
the file wasn't in conflict (settings/page.tsx wasn't independently
modified on this branch at the time), so it slipped through as a clean
merge. Rebuilt from scratch using the working Slack panel directly above
it in the same file as the template — same state shape, same banner/error
conventions, same handler structure.

**What changed** (backend): `GithubIdentity` table + migration
`x7s5p2k6m042`. `GithubIdentityOAuthService` mirrors `SlackOAuthService`
structurally exactly (HMAC-signed TTL-bounded state, Fernet token
encryption with the same dev-fallback-derives-from-DATABASE_URL posture,
upsert-by-owner) — the only real differences are GitHub's OAuth endpoints
(`github.com/login/oauth/{authorize,access_token}` +
`api.github.com/user` for the identity lookup) and field names. New
routes `GET/POST /api/github/{status,install,oauth/callback,disconnect}`;
the callback added to `SessionAuthMiddleware._PUBLIC_PREFIXES` (public,
same posture as `/api/slack/oauth/callback` — GitHub's redirect carries no
Bearer token, and the signed `state` param is the actual verification).
32 new unit tests (16 in `test_github_identity_oauth_service.py`, mirroring
`test_slack_oauth_service.py`'s exact structure). Full suite 219 → 235.

**What changed** (frontend): rebuilt the GitHub Integrations row in
`dashboard/settings/page.tsx` for real — connect/disconnect buttons, a
banner reflecting `?github=connected|error`, action-error text, all
wired to real endpoints. Swapped `endpoints.ts`'s hand-written GitHub
identity types for `components["schemas"][...]` generated from the live
spec, same as the workspace invite/member types in 2026-08-07e.
`npx tsc --noEmit` clean.

**Not live-verified end to end** — same honest gap as the PR-integration
App before real credentials arrived: no `GITHUB_OAUTH_CLIENT_ID`/
`_CLIENT_SECRET` configured in this environment, so the real
`github.com` token exchange has never actually run. What *is* verified
live: `GET /api/github/status` correctly reports `configured: false`
before any credentials exist; `GET /api/github/install` fails clean
(`400`, not `500`) with an actionable message; unauthenticated requests
get `401`. The exchange/upsert/encryption logic itself is covered by 16
unit tests with the network layer mocked, mirroring the Slack OAuth test
suite's coverage exactly. To finish verifying for real: add the same
GitHub App's Client ID + Client Secret (from the App's settings page,
same place as the private key) as `GITHUB_OAUTH_CLIENT_ID` /
`GITHUB_OAUTH_CLIENT_SECRET`, plus `GITHUB_OAUTH_STATE_SECRET` (any
random string), then click Connect on the real settings page.

### 2026-08-07f — Pulled samrita's second frontend round; hand-merged the two real conflicts

`origin/samrita` gained one new commit (`ec0b4a6`) since the last merge.
Mostly pure-additive and taken wholesale: `analytics-charts.tsx` (new —
scatter/donut/bar charts) backed by real new fields in
`fetch_accuracy_metrics` (`runtime_scatter`, `migration_type_distribution`,
`risk_level_distribution` — purely additive, no existing keys changed),
plus dashboard/settings page rewrites, landing copy, and `ui-kit.tsx`/
`globals.css` styling. Deliberately **not** pulled: `backend/uv.lock`
(1504 lines) — no accompanying `pyproject.toml` change, this project is
pip + `requirements.txt` by convention, looks like a stray local artifact
from running `uv` once, not a real package-manager migration.

**Two real conflicts, both from the same root cause:** samrita's branch
diverged from a point before this session's GitHub PR integration and
workspace-invites backend existed, so their new commit rebuilt
`workspace-settings-panel.tsx` and `workspace-members-panel.tsx` from a
version of the world where those backends were still fiction — disabling
the invite button ("coming soon") and adding a "COMING SOON" badge to the
members panel. Blindly taking their files would have **regressed both
features back to fake placeholders** minutes after live-verifying them for
real. Hand-merged instead:
- `workspace-settings-panel.tsx`: kept the GitHub repo-linking block (not
  present in samrita's version at all — it predates that feature on their
  side) and the working, enabled invite button; took their real UX
  improvement (collapsible "New workspace" form behind a toggle button,
  which was a genuine simplification).
- `workspace-members-panel.tsx`: took their real improvement (a load
  failure silently falls back to empty state instead of surfacing raw
  backend text; only *remove* actions surface an error) but kept the
  copy accurate to reality instead of "not available yet."

Verified after merging: backend imports clean, 219/219 unit tests,
`GET /runs/metrics/accuracy` live-returns the three new fields (6 real
graded runs in the scatter), `npx tsc --noEmit` clean, landing page
renders correctly in a real browser with the new styling.

### 2026-08-07e — Workspace invites + members built, live-verified against the real database

Closes the last loose end from the 2026-08-07d merge: samrita's invite
dialog, members panel, and `/invite/[token]` page had zero backend behind
them. Built to that exact contract (endpoints.ts's hand-written types were
the spec) rather than redesigning the UI.

**Scope decision, made explicit before writing code, not assumed:** roster
only. A `workspace_members` row grants visibility of the workspace
(`GET /workspaces`, `GET /workspaces/{id}` now check owner-OR-member, not
owner-only) so accepting an invite isn't a dead end — but it grants
**nothing** at the run level. `MigrationRun` tenancy is completely
untouched; the existing `owner_identity`-only filter in
`MigrationRunService.list_migration_runs` does that enforcement for free,
verified live: created a run under the shared workspace as the owner,
confirmed a newly-accepted member querying by their own identity sees
**zero** runs. Widening that is a separate, larger decision, not a side
effect of shipping invites.

**What changed** (backend):
- `workspace_members` (workspace_id, user_identity, role) and
  `workspace_invites` (method email/github/link, token, status, expiry)
  tables. Migration `w6r4o1j5l931` backfills every existing workspace's
  owner as an implicit 'owner' member — 22/22 backfilled clean on this DB.
- Invite tokens are stored as plain text by design, not hashed — the
  "link" tab needs to read an existing pending invite's token back to
  reuse it, which a one-way hash can't support. Same shape as any
  capability-URL share link (Slack/Notion/Linear); protected by TLS,
  DB access controls, 14-day expiry, and revocability, not secrecy of a
  hash. "Expired" is never a stored status — computed at read time from
  `expires_at` (`_effective_status`), so no cron job is needed to flip it.
- `WorkspaceService` gained `list_accessible_workspaces` /
  `get_accessible_workspace` (owner-or-member) alongside the existing
  owner-only `get_owned_workspace` (still used for PATCH/DELETE — settings
  mutation stays owner-only), plus `add_member` (idempotent — accepting a
  token twice must not duplicate a row or raise) and `remove_member`
  (owner-only; the 'owner' role row can never be removed this way — the
  only way to lose it is deleting the whole workspace, which cascades).
- New `WorkspaceInviteService`: create/list/revoke (owner-only, same
  access check as workspace settings), public `get_preview` (token is the
  credential, no ownership check — 404 only for a genuinely unknown
  token, never for revoked/expired/accepted, which return 200 with that
  status so the UI can explain it), and `accept_invite` (rejects non-
  pending with `ConflictError`, otherwise idempotently adds the member and
  marks the invite accepted).
- Email sending is real (SES via `AwsClientFactory.ses()`), best-effort —
  mirrors `SlackNotificationService`/`GithubNotificationService`'s posture
  exactly: a delivery failure (SES sandbox mode requires the *recipient*
  verified too, a real and common dev-environment failure mode) never
  undoes or blocks the invite record that already exists. Verified live
  with `SES_SENDER_EMAIL` unset: `method=email` invite creation still
  returns 201, logs `"Skipping invite email — SES_SENDER_EMAIL not
  configured"` rather than failing.
- New public routes `GET /invites/{token}` / `POST /invites/{token}/accept`
  — `/invites` added to `SessionAuthMiddleware._PUBLIC_PREFIXES` for the
  GET; the POST still requires a real session (the middleware validates
  any Bearer token present regardless of the public allowlist, and
  `resolve_owner_identity` enforces `auth_enforced()` the same as every
  other authenticated route — confirmed live: `GET /invites/{token}` with
  no header → 200; `GET /workspaces/{id}/invites` with no header → 401).
- 34 new unit tests (`test_workspace_membership.py`,
  `test_workspace_invite_service.py`). Full suite 185 → 219.

**What changed** (frontend): swapped samrita's hand-written placeholder
types (`WorkspaceInvite`, `WorkspaceMember`, `InvitePreview`, ...) for
`components["schemas"][...]` generated from the live OpenAPI spec, per
their own comment's stated intent. Tightened the backend's `method`/
`status`/`role` fields to `Literal` types (were plain `str`) specifically
so `openapi-typescript` generates real unions instead of `string` —
`WorkspaceInviteMethod` failed to typecheck against a bare `string` field
before this. No component logic changed; the UI was already built to this
exact contract. `npx tsc --noEmit` clean.

**Live-verified end to end against the real database** (14 real-HTTP +
10 real-DB-direct checks, one throwaway workspace, cleaned up after):
create workspace → owner auto-added as `role=owner` member → create a
`link` invite → public preview with no auth header → preview 404s
correctly for a garbage token → a **distinct** identity accepts the real
token → that identity's `list_accessible_workspaces` now includes it →
roster shows both members → re-accepting the same (now-accepted) token is
rejected with no duplicate member row → removing the owner's member row
is rejected (401) → removing the regular member succeeds (204) → revoke
sets status to `revoked` → an unauthenticated caller cannot list invites
(401) → **the run-access boundary itself**, confirmed by direct query,
not inferred.

### 2026-08-07d — Merged `samrita`'s frontend into `Samved` (frontend-only, selective)

`samrita` was confirmed **frontend-only** (16 files, zero backend changes).
Merged file-by-file rather than `git merge`, because this branch had a large
uncommitted backend+frontend change set in the working tree.

**Taken wholesale** (no overlap with in-flight work): landing page
(`hero-section`, `site-data`, `text-reveal`), `login-form`, `signup-form`,
`clerk-appearance`, `globals.css`, `workspace-switcher`, `middleware.ts`
(adds `/invite(.*)` public route), `client.ts` (adds `skipAuth` for
token-keyed public endpoints), and the whole invite/members surface
(`invite-members-dialog`, `workspace-members-panel`, `app/invite/[token]`),
plus `app/dashboard/settings/page.tsx`.

**Hand-merged** (both branches edited these):
- `lib/api/endpoints.ts` — took samrita's as the base (it is a superset),
  then re-applied this branch's three additions: `github_repo_full_name` /
  `github_migration_glob` on create/update workspace, and the PR-integration
  status call.
- `components/workspace-settings-panel.tsx` — took samrita's (invite button
  + members panel) as the base, re-applied the GitHub repo-linking form.

**Naming collision resolved deliberately.** Both branches defined
`getGithubStatus`, but they are *different features*: samrita's is a GitHub
**identity** connection (OAuth connect/disconnect, for matching invited
teammates — their own comment says so) hitting `/api/github/*`; this
branch's is the **PR integration** hitting `/webhooks/github/status`. Kept
both; renamed this branch's to `getGithubIntegrationStatus` to match its
`GithubIntegrationStatus` type.

**Known-unbuilt backend, deliberately kept (human decision).** The invite /
members / GitHub-identity UI calls seven routes that do not exist:
`/api/github/{status,install,disconnect}`,
`/workspaces/{id}/{invites,members}`, `/invites/{token}{,/accept}`. The
human explicitly chose to keep this frontend and build the backend later.
All of it error-handles (try/catch → message, never a crash), so nothing
takes down a page. Note for whoever builds it: `/invites/*` currently
returns **401**, not 404 — `SessionAuthMiddleware._PUBLIC_PREFIXES` will
need `/invites` added for the unauthenticated preview to work.

Verified: `next build` succeeds (17 routes incl. `/invite/[token]`),
`npx tsc --noEmit` clean, backend suite 185/185, landing page renders in a
real browser, backend healthy on **:8003** (not 8000 — the frontend's
`.env.local` and the Slack redirect both point at 8003; `scripts/dev.py`
defaults to 8000, which is wrong for this project — use
`python run_server.py 8003`).

### 2026-08-07c — GitHub webhook: 10s delivery timeout + redelivery duplication, both found by inspecting GitHub's own delivery log

Post-verification bug hunt on the live integration. Checking
`GET /app/hook/deliveries` (GitHub's own record of what it saw, not ours)
showed the first real PR delivery as **failed**, despite the run being
created correctly:

```
pull_request opened → giving up after 1 attempt(s):
context deadline exceeded (Client.Timeout exceeded while awaiting headers)
code=500 dur=10s
```

**Bug 1 — GitHub's webhook timeout is 10s; this pipeline is much slower.**
The handler ran discovery (real database round trip) plus two Bedrock calls
inline before responding. GitHub gave up at 10s and recorded a failure,
which risks it disabling the webhook after repeated failures, and makes
every redelivery a fresh duplicate run. Fixed: `POST /webhooks/github` now
verifies the signature (cheap, and the actual security boundary), hands the
payload to a `BackgroundTasks` job, and returns **202** immediately. The
background job opens its **own** database session —
`build_github_webhook_service_for_session` in `app/dependencies.py`, which
reuses the existing dependency factories rather than duplicating their
wiring — because the request-scoped session is closed the moment the
response is sent. Verified against a real redelivery: `code=202 dur=0.87s`,
where the same delivery previously logged `code=500 dur=10s`.

**Bug 2 — redelivery would have created duplicate runs.** No idempotency
anywhere: GitHub redelivers both manually (deliveries UI) and automatically
after a failed delivery, always with the same head sha. Each one would have
meant a second `MigrationRun` — a duplicate shadow cluster's real cost and a
duplicate PR comment. Fixed with
`GithubPullRequestLinkRepository.get_by_pr_head_sha`, checked before any
GitHub API call so a redelivery storm can't burn installation-token
requests either. Verified live: after redelivering the failed delivery,
still exactly 1 PR link and 1 `github_pr` run.

Note the failure shape common to both this entry and 2026-08-07b: the
feature looked correct from inside (right run, right prediction, right
gate) while being broken from the outside. Neither was visible without
checking the *counterparty's* view — GitHub's delivery log and the actual
posted comment — which is worth doing for any outbound integration, not
just this one.

Tests: `test_redelivered_webhook_for_same_head_sha_creates_no_duplicate_run`.
Suite 184 → 185. Route status changed 200 → 202, `openapi.json`/`schema.ts`
regenerated, `npx tsc --noEmit` clean.

### 2026-08-07b — GitHub PR integration LIVE-VERIFIED end to end, plus a real ordering bug found by doing it

**First real PR, first real webhook, first real posted comment.**
`samvedmamillapalli/test_repo` PR #2, a `migrations/*.sql` file containing
`ALTER TABLE demo_items ADD COLUMN discount_pct INT NOT NULL DEFAULT 0;`,
against the real `customer_demo` read-only database. Confirmed: webhook
fired → workspace resolved → SQL extracted → `MigrationRun` created with
`run_kind=github_pr` under the correct workspace → **real** schema discovery
succeeded → **real** Bedrock prediction (6.8s / 0.0MB / rollback_risk=high /
confidence 0.62) → `policy_decision=allow_with_warning` with two genuine
deterministic risk flags → held at `awaiting_approval` exactly like every
other run → PR comment + check run posted by `migration-oracle[bot]` with
those real numbers and a working deep link. Check-run conclusion `neutral`,
never `failure` — advisory only, as the plan's resolved Open Question #4
requires.

**The bug that first real PR exposed:** the run came out correct but
`check_run_id` and `initial_comment_id` were both NULL and **nothing was
posted to GitHub**. Cause: `GithubWebhookService` created the
`github_pull_request_links` row *after* calling `run_prediction_pipeline`,
but `PredictionPipelineService` fires its prediction-ready hook *inside*
that call, and `GithubNotificationService.send_prediction_ready` resolves
where to post by looking that row up by run id. The lookup returned None,
so the whole notification silently no-op'd — a best-effort path failing
invisibly, precisely the failure shape this codebase's `except → warn →
return None` convention is prone to. Fixed by creating **and committing**
the link row immediately after run creation, before discover/predict.
Regression test `test_pr_link_is_committed_before_prediction_runs` asserts
the actual call ordering, not just the end state, since the end state
(a link row exists) looks identical either way. Suite 183 → 184.

Note for hosting: the PR comment's deep link comes from `FRONTEND_URL`,
which is `http://localhost:3000` in dev — fine locally, but it must be the
real public frontend origin before anyone outside this machine clicks it.

### 2026-08-07 — GitHub PR integration: closed the two silent-failure gaps in the link flow

Found while walking a real user (the human) through setup: the repo-linking
flow had two failure modes that produced **no error anywhere the user could
see**, which is exactly the "degrade visibly rather than silently" rule in
the Working Rules above.

1. **Linking a repo the App isn't installed on saved cleanly and then never
   fired a webhook.** GitHub only sends `pull_request` events for repos where
   the App has an installation, and nothing in this app checked that. A user
   would type a repo, see success, open a PR, and get silence with no
   diagnostic. Now `POST/PATCH /workspaces` calls
   `app/services/github_setup.py::assert_repo_installed`, which resolves
   `GET /repos/{owner}/{repo}/installation` via the App JWT and rejects with
   a 422 naming the repo and linking the App's public install page. A
   transient GitHub outage deliberately does **not** block the save (the
   webhook path re-resolves the installation per event anyway) — only a
   definitive 404 does.
2. **No way for the UI to know whether GitHub integration was configured at
   all.** New public `GET /webhooks/github/status` returns
   `configured` / `webhook_secret_set` / `app_slug` / `install_url`. Exposes
   no credentials — only whether they're present, plus the App's
   already-public slug.

Frontend: the workspace settings panel's repo form now leads with the
two-step flow (install the App on GitHub → then name the repo here),
renders the real install link from that endpoint, degrades to "no App
configured" guidance when the server has none, and explains the glob field
in terms of both supported conventions instead of just Alembic's.

11 new tests (`tests/unit/test_github_setup.py`); suite 172 → 183.
`npx tsc --noEmit` clean. Note the product-level point this surfaced: the
install step is done by the *user* from the App's public install URL, not
by an operator adding repos — it's a GitHub security boundary (an App
cannot read a repo or post PR comments without an explicit installation),
identical to how Vercel/Dependabot/CodeRabbit work.

### 2026-08-05d — GitHub PR integration built (Feature 3 from docs/FUTURE_GITHUB_INTEGRATION_PLAN.md) — code complete, not yet live-verified

Follow-up to the 2026-08-05 workspaces entry below, which this feature is
explicitly downstream of. Built per the plan's own recommendation: approval
model (a) only (auto-predict, hold at the existing approval gate, report
to the PR, human approves via the exact `POST /runs/{id}/approve` flow) —
**no auto-approval was built**, matching the plan's explicit instruction not
to build option (b) without a separate human decision (none was given).
The plan's four Open Questions were already answered in the plan doc itself
(no auto-approval; one repo → one workspace; tag the PR author; warning
comment only, never block the merge) — followed as written, not relitigated.

**What changed** (backend):
- `Workspace.github_repo_full_name` (partial-unique — one repo maps to at
  most one workspace) + `Workspace.github_migration_glob` (per-repo
  detection heuristic, defaults to this project's own
  `backend/alembic/versions/*.py`). New `github_pull_request_links` table
  (one row per PR-triggered `MigrationRun`, `ON DELETE CASCADE`, same
  pattern as `approvals`). Migration `v5q3n0i4k820`.
- `app/services/github_app_client.py` — GitHub App JWT (RS256) + per-
  installation access tokens, list PR files, fetch file content, post PR
  comment, create/update check run. `app/services/github_webhook_service.py`
  — HMAC-SHA256 signature verification, migration-file glob matching, a
  deliberately bounded SQL-extraction heuristic (`.sql` files as-is;
  `.py`/Alembic files scanned for `op.execute(...)` string literals only —
  schema-builder-only migrations are explicitly unsupported, not half-
  solved), workspace resolution, and the create → discover → predict
  pipeline reusing the exact same services the UI-driven flow uses.
- New public route `POST /webhooks/github` on the existing FastAPI app
  (not a new Lambda/API Gateway — the app already gets a public URL once
  hosted per `docs/HOSTING.md`, which the original plan flagged as the
  fallback when a stable URL exists). Allowlisted in
  `app/api/middleware_auth.py`'s public-path list since GitHub authenticates
  via signature, not a Bearer token.
- `app/services/github_notification_service.py` — mirrors
  `SlackNotificationService`'s best-effort, fire-and-forget posture exactly.
  Hooked into `PredictionPipelineService._notify_prediction_ready` (initial
  prediction comment + check run) and `WorkflowOrchestrationService.
  _notify_terminal` / `abort_for_run` (terminal predicted-vs-measured
  follow-up), the same two points Slack's lifecycle notifications already
  hook. Check-run conclusions are **never** `failure`/`action_required` —
  only `success`/`neutral` — enforcing "advisory only, never blocks the
  merge" at the code level, not just in a comment's wording.
- `run_kind` gained a fourth value, `github_pr` (alongside `standard` /
  `chaos` / `debug`) — reachable only via the webhook path, not the
  `POST /runs` UI schema, so a user can't hand-create a run claiming to be
  PR-triggered.
- 26 new unit tests (`test_github_webhook_helpers.py` — signature/glob/SQL-
  extraction pure functions; `test_github_webhook_service.py` — orchestration
  with the GitHub API and connection loading mocked; 5 new cases in
  `test_workspace_service.py` for repo-link uniqueness). Full suite:
  172/172.

**What changed** (frontend):
- `workspace-settings-panel.tsx` gained a per-workspace "Link repo" /
  "Edit repo" inline form (repo full name + migration glob), using
  `updateWorkspace`'s new `github_repo_full_name` / `clear_github_repo` /
  `github_migration_glob` fields. `openapi.json` + generated `schema.ts`
  refreshed from the live `app.openapi()` output. `npx tsc --noEmit`: clean.

**Verification status — deliberately not claimed as done.** Unlike every
other entry in this log, this feature's own plan doc requires "a real test
repository and a real PR" to call it verified, and **no GitHub App has been
registered yet** — that is a manual, human, browser-based step this session
cannot perform (see `docs/GITHUB_APP_SETUP.md`, written for the human to
follow). `scripts/prove_github_integration.py` proves everything reachable
without one: real HTTP workspace-repo linking + the one-repo-one-workspace
409 + webhook signature rejection against the running dev API, and an
in-process real-DB pipeline run (real workspace resolution, real SQL
extraction, real `MigrationRun` creation, real schema discovery, real
prediction) with only the `api.github.com` calls mocked. That is not the
same as the plan's own bar — do not report this feature as fully verified
until a human has completed `docs/GITHUB_APP_SETUP.md` and a real PR has
been observed end to end.

### 2026-08-05c — Concurrent shadow executions: Active Runs list + (explicitly requested) per-owner cap

Executed `docs/FUTURE_CONCURRENT_SHADOW_PLAN.md`'s Prompt. Re-checked its
core finding by re-reading `try_admit`/`count_active` directly (still
true, unchanged) rather than trusting it blindly. Two independent pieces:

**1. Active Runs list** (the plan's recommended piece — confirmed still
missing, the earlier backendfix.md entry was the same planning note, not
a build record):
- Backend: `status_in=` query param on `GET /runs` (comma-separated,
  e.g. `pending,predicting,awaiting_approval,running`), threaded through
  `MigrationRunRepository._apply_filters/list/count`,
  `MigrationRunService.list_migration_runs/count_migration_runs`, and the
  route — additive, existing `status=` single-value filter untouched.
- Frontend: new `components/active-runs-panel.tsx`, mounted at the top of
  the Current Migration page (`current-migration-workspace.tsx`) — the
  exact page the plan identifies as assuming one run in focus. Queries
  the owner's non-terminal runs (excluding chaos/debug, scoped to the
  active workspace, same conventions as every other list on this page),
  renders nothing when there's nothing extra to show (0 runs, or exactly
  1 that's already the pinned "current" run) so it never adds empty-state
  noise to a page that already has one.

**2. Per-owner concurrency cap** — the plan explicitly recommends
**against** building this before Aug 18 ("nobody asked for it, no
contention to solve"). A human explicitly overrode that recommendation
this session ("just build it ignore where it says dont build before
august 18. do as i say") — the exact condition the plan's own Prompt
gates this work behind. Additive on top of the global cap, per the plan's
design:
- `ShadowClusterRepository.count_active_for_owner(owner_identity)` — same
  `ACTIVE_SHADOW_STATUSES` predicate as `count_active`, joined to
  `migration_runs` (the only owner column reachable, since
  `shadow_clusters` itself carries none).
- `settings.shadow_max_concurrent_per_owner: int | None`, default `None`
  — unset means no per-owner limit, identical to today's behavior.
  `shadow_max_concurrent` (the global cap) is untouched, same meaning,
  same default.
- `ShadowClusterService.try_admit` takes optional `owner_identity` /
  `max_concurrent_per_owner`; when both are given, checks the owner's own
  count in the same serializable transaction as the existing global
  count — a second read, not a second transaction, so no new race window.
  `app/shadow/concurrency.py::acquire_slot` and
  `app/lambdas/handlers/provision_shadow.py` (the real
  `ProvisionShadowCluster` Lambda) now pass `run.owner_identity` and
  `settings.shadow_max_concurrent_per_owner` through — **this Lambda
  needs a SAM redeploy before the cap takes effect in the real demo
  path**; noted in `docs/DEPLOYMENT.md`.
- 6 new unit tests (`tests/unit/test_shadow_cluster_admission.py`):
  global-cap-only unaffected when no per-owner cap is passed, owner
  rejected at its own cap even with global capacity free, a different
  owner unaffected by the first owner's cap, existing-shadow reuse skips
  every check. Full suite 146/146.

**Live verification, real CockroachDB Cloud, zero shadow-cluster cost**
(per the plan's own note: `try_admit` only inserts a control-plane row —
the actual CockroachDB Cloud cluster gets created later, by the Lambda's
`provider.create()` call, which this verification never reaches):
created 4 real `migration_runs` rows (2 under a synthetic owner A, 1 under
owner B, 1 more under A) and called the real, unmodified
`ShadowClusterService.try_admit` against the real database with a global
cap of 5 and a per-owner cap of 1 — owner A's first run admitted, owner
A's second run rejected *while the global count was nowhere near its
cap*, owner B's run admitted independently, and a final call with no
owner/cap args (the default path) still admitted normally, proving the
opt-in cap doesn't change existing behavior when unset. All rows deleted
afterward; re-ran the cleanup check to confirm zero residue.

Active Runs panel: live-verified in the browser — created two real
pending runs, confirmed the panel rendered both (SQL snippet, status
pill, the pinned one labeled "current"), confirmed it disappears when
there's nothing non-terminal to show.

**Environment note, same MissingGreenlet class as noted for the workspace
work above, new manifestation**: a bare `asyncio.run()` proof script
crashes on the *second* ORM `session.refresh()`-triggering operation in
one session (create → commit → touch a previously-loaded object's
attribute) — happens identically whether pre_ping is on/off, pooled or
`NullPool`, policy- or `loop_factory`-selected event loop. Root cause
isolated to `session.refresh()`/expired-attribute lazy-loads specifically
(plain `text()` queries never hit it, proven earlier). The real running
app never hits this (its request-per-session lifecycle doesn't chain
multiple commits through one session the way a proof script does) —
confirmed by driving the same admission logic through
`starlette.testclient.TestClient` (which properly bridges the async
context) via a temporary, fully-removed diagnostic route instead. Also
found and fixed a second, unrelated bug this surfaced: `MigrationRun.id`
(`default=uuid.uuid4`) is **not** set until `flush()` — reading `.id`
right after `MigrationRun(...)` construction, before `create()`, silently
returns `None`.

Also found and cleaned up ~23 orphaned `migration_runs`/1 `shadow_clusters`
row(s) left behind by earlier crashed attempts at this same live
verification (owner_identity `concurrency-test-owner-a`/`-b`) — the
in-route cleanup only runs on a successful pass, so a crash before it
leaves garbage; swept up with a second temporary route before the final
clean run.

Full backend suite 146/146, frontend typecheck clean, both pieces
live-verified against the real database/app.

### 2026-08-05b — Overview and Past Migrations are now workspace-scoped

Follow-up to the entry directly below. Human feedback after using the
switcher built there: *"the overview should be different for each
workspace, like it should show a different set of analytics, migrations,
and whatnot."* This also reverses the previous entry's deliberate
non-decision on the history page — the new instruction explicitly named
"migrations," so Past Migrations is now scoped too.

**What changed** (backend) — all four additive/optional, no existing
caller broke:
- `app/memory/metrics.py::fetch_accuracy_metrics` gained an optional
  `workspace_id` param, applied to every grade/approval query except the
  `retrieval`/`memory_corpus` sub-query, which stays owner-wide on purpose
  — same locked reasoning as the memory-retrieval decision above: memory
  retrieval and analytics/history are different scoping axes.
- `app/services/activity_feed.py::fetch_run_volume` /
  `fetch_activity_feed` — same `workspace_id` param, same
  `CAST(:workspace_id AS UUID) IS NULL OR mr.workspace_id = CAST(...)`
  passthrough pattern already used elsewhere in this file.
- `MigrationRunRepository.distinct_approvers` /
  `MigrationRunService.list_approvers` — same param.
- `GET /runs/metrics/accuracy`, `/runs/approvers`, `/runs/volume`,
  `/runs/activity` all accept an optional `workspace_id` query param now.
- Full suite: 140/140 unchanged.

**What changed** (frontend):
- `lib/api/endpoints.ts`: `getAccuracyMetrics` / `getActivityFeed` /
  `getRunVolume` / `listApprovers` all forward an optional `workspace_id`.
- `app/dashboard/page.tsx` (Overview) and
  `app/dashboard/migrations/history/page.tsx` (Past Migrations) both read
  `getActiveWorkspaceId()` and pass it into every scoped call — reversing
  the previous entry's deliberate deferral on the history page.
- `npx tsc --noEmit`: clean.

**Live verification, real CockroachDB Cloud + real Clerk auth, via the
actual running app in a browser** (Playwright, signed in as the real
Clerk test account): created a second, empty workspace under the same
owner; Overview and Past Migrations both went to zero (Current Migration,
Decision Queue, Recent Activity, Latest Migration, Graded, Migration
Success Rate, Approval Decisions) while the untouched Memory-corpus count
stayed at its owner-wide value (38 ready), exactly matching the locked
retrieval-stays-owner-wide decision. Switched back to "Default" and every
number returned to its non-empty value (6 graded, 2 proceeded, 2
migrations listed, etc.). Deleted the test workspace afterward.

**Environment note, expanding the port-8000 note two entries below**: hit
the same class of issue again mid-verification, this time on 8003 (the
frontend's actual configured port) and again on a fresh 8010 — a
`netstat`/`Get-NetTCPConnection`-visible LISTENING entry whose PID
`Get-Process`/`Stop-Process`/`taskkill` all report as not existing. This
time it was reproducible enough to pin down: it's not one immortal ghost,
it's leftover reload-worker processes from earlier `dev.py restart`
invocations in the same session not fully exiting when the parent
reloader is killed, and Windows briefly (or, if the parent is also
already gone, indefinitely) keeps their LISTENING socket entry visible
after the process itself is gone. Two consequences worth knowing:
1. With two live listeners on the same port, the OS silently splits
   traffic between the stale one (old code) and the fresh one (new code)
   — requests to the *same URL* nondeterministically get different
   answers. This is what made the first two live-browser checks in this
   session look like a real scoping bug when the code was actually
   correct — confirmed independently via a direct DB-level function call
   *and* a full in-process ASGI `TestClient` call against the real route
   (auth bypassed via monkeypatch for that one diagnostic run only, not
   shipped), both giving the right answer before the port was ever fixed.
2. The fix: `Get-Process python*` (not `-Id <phantom>`) to find every
   real python.exe still alive, `Stop-Process -Force` all of them, then
   restart once. Killing by the phantom PID directly never works; killing
   every *real* python process does, because it's their still-attached
   listening sockets that were confusing `netstat`'s PID attribution, not
   a genuine orphaned/unkillable process.

Full backend suite (140/140) and frontend typecheck both clean; live
browser verification passed after the port was cleared as above.

### 2026-08-05 — Workspaces built (Feature 1 from docs/FUTURE_WORKSPACES_PLAN.md)

Follow-up to the 2026-08-04 planning-only entry below: the human explicitly
authorized building it now (edited the plan doc directly — removed "Do not
build this before August 18" from the summary, and answered the retrieval-
scoping open question in the doc itself: *"every single migration ran
should be in the memory, and every migration that does run will use that
same memory database and all of the migrations taken into account before
proceeding with the user's current one."*). That is an explicit **owner-
wide** decision — `app/memory/retrieval.py` was **not touched**, per the
plan's own recommendation, and this is now live-verified (below), not just
asserted.

**Decisions resolved** (the plan's Open Questions, using judgment per the
human's "do the recommended action" instruction):
- Retrieval scoping: owner-wide, unchanged. Explicit human decision, not a
  default.
- Connection validation at workspace-creation time: yes, a real lightweight
  connectivity check (`SELECT version()` via `SchemaAnalysisConnection.ping()`,
  not a full schema discovery) — fails fast on a broken connection rather
  than silently storing a bad pointer. `app/services/connection_secrets.py::verify_connection_ping`.
- Workspace deletion: `ON DELETE SET NULL` as the plan proposed — deleting a
  workspace orphans its runs back to "no workspace," never deletes run
  history. No application-level cascade code; the FK does it.
- Secret naming: same store, `migration-oracle/connections/workspace/{workspace_id}`
  vs. the existing `migration-oracle/connections/{run_id}` — distinguishable
  in the AWS console, no collision risk either way (different UUID spaces).

**What changed** (backend):
- New `workspaces` table (`app/database/models/workspace.py`,
  migration `t3o1l8g2i608`) — `owner_identity` (plain string, matching the
  existing convention; **not** a relationship to `app_users`, confirmed
  still dead code, see below), `name`, `connection_secret_arn`
  (pointer-only, same convention as `MigrationRun.connection_secret_arn`),
  `connection_label` (display-only), `is_default`.
- `migration_runs.workspace_id` — nullable FK, `ON DELETE SET NULL`. Same
  migration backfills an implicit "Default" workspace per existing
  `owner_identity` and points every pre-existing run at it — applied for
  real against the live dev database: 13 default workspaces created, all
  45 existing runs got a non-null `workspace_id` (0 left null).
- Extracted `app/services/connection_secrets.py` from three near-duplicated
  private helpers in `app/api/routes/runs.py` (`_store_connection_url` /
  `_load_connection` / `_parse_database_url`) so workspaces reuse the exact
  same store/load path instead of a second copy. `runs.py` now imports from
  it; the old private copies are gone.
- `POST /runs/{id}/discover` and `POST /runs/{id}/start-workflow`: when the
  caller provides neither `connection_secret_arn` nor `database_url`, and
  the run belongs to a workspace with a stored connection, that connection
  is used automatically. `DiscoverSchemaRequest`'s old hard
  "must provide one" Pydantic validator was removed (moved to the route,
  which now has workspace context to check first) — a request with truly
  nothing available (no payload, no workspace, or a workspace with no
  stored connection) still gets a clean 422.
- `WorkspaceRepository` / `WorkspaceService` / `app/schemas/workspace.py` /
  `app/api/routes/workspaces.py` (`POST/GET /workspaces`,
  `GET/PATCH/DELETE /workspaces/{id}`, all owner-scoped like every other
  route in this app) / DI wiring in `app/dependencies.py`.
- `POST /runs` accepts optional `workspace_id` (route verifies it belongs
  to the resolved owner before the service ever sees it — never trust a
  client-supplied workspace_id without an ownership check, same posture as
  `get_owned_run`). `GET /runs` accepts `workspace_id` as a list filter.
  `MigrationRunResponse` / `MigrationRunSummaryResponse` both expose
  `workspace_id`.
- Confirmed `app_users` is **still** dead code (only reference: the
  `auth_enabled`-gated legacy custom register/login flow in
  `app/api/routes/auth.py`) — re-verified before building on top of
  anything, per the plan's own explicit instruction not to assume.
- 13 new unit tests, `tests/unit/test_workspace_service.py` — full suite
  now 140/140.

**What changed** (frontend):
- Deleted `components/team-switcher.tsx` and `components/nav-projects.tsx`
  — confirmed dead shadcn template scaffolding (zero mount points in
  `app-sidebar.tsx`, hardcoded fake data, no real wiring) per the plan's own
  finding; not resurrected, replaced outright.
- New `components/workspace-switcher.tsx` (real data via `listWorkspaces`,
  mounted in the sidebar header) and `components/workspace-settings-panel.tsx`
  (create/list/delete, mounted on the Settings page, linked from the
  switcher's "Manage workspaces"). `lib/api/owner.ts` gained
  `getActiveWorkspaceId`/`setActiveWorkspaceId` (same localStorage
  convention as owner identity / current run). Run-creation call sites
  (`current-migration-workspace.tsx`, `migrations/new/page.tsx`,
  `new-migration-dialog.tsx`) now pass the active workspace.
- Deliberately **not** wired: a workspace filter on the Past Migrations
  history list. Adding a silent always-on filter there would have changed
  existing visible behavior (fewer runs shown) with no toggle to see
  "all workspaces" — flagged as a deferred nice-to-have rather than shipped
  as a confusing surprise.
- `npx tsc --noEmit`: clean throughout.

**Live verification** (real CockroachDB Cloud, real Clerk auth, real
Bedrock — not mocked), two scripts, both re-run to a clean PASS after fixing
real issues found along the way:
- `scripts/prove_workspaces.py` (real HTTP, real Clerk test-account token
  per call since tokens are ~60s-lived): two workspaces under one owner,
  each with an independently stored connection secret; `POST /discover`
  with an **empty payload** succeeded for both, each correctly resolving
  its own workspace's stored connection (no cross-contamination — verified
  the two runs resolved to different secret ARNs); a run with no workspace
  and no connection still 422s cleanly. One real finding along the way:
  using the app's own control-plane `DATABASE_URL` (write-capable) as a
  workspace connection got correctly rejected with 403 by the existing
  read-only enforcement — not a bug, the safety net working as designed;
  fixed the *proof script* to use the real judge-facing read-only
  credential instead.
- `scripts/prove_workspace_memory_scope.py` (direct service calls): a full
  graded run (predict → approve → local-verify → grade → remember) under
  workspace A, then a second run under workspace B (same owner, different
  workspace) — confirmed the workspace-A memory is reachable via the exact
  `owner_identity IN (...)` scoped vector-candidate query
  `HybridMemoryRetrieval` itself issues, while predicting under workspace
  B. (A secondary, informational check — whether that memory lands in the
  *final top-5 ranked* results shown in `explainability.memory` — came back
  negative in this run; traced that to real embedding-similarity ranking
  against the ~20-entry open-source corpus, not a scoping bug: an
  owner-only-scoped query with no corpus competing found the memory
  immediately. Rewrote the script's pass/fail signal to check reachability
  directly rather than top-K ranking luck, which is what "owner-wide, not
  workspace-scoped" actually means at the query level.)

Environment note for whoever runs these scripts next: this session hit a
Windows port-8000 listener (PID reported by `netstat`/`Get-NetTCPConnection`
but invisible to `Get-Process`/`Stop-Process`/`taskkill` — never resolved,
possibly a WSL2/namespace artifact) that `scripts/dev.py restart` couldn't
reclaim. Worked around by running the dev server on port 8010
(`python scripts/dev.py restart --port 8010`) rather than fighting it
further. If port 8000 is mysteriously unresponsive-but-occupied again, try
a different port before assuming the app itself is broken.

Full backend suite (140/140) and frontend typecheck both clean after all of
the above.

### 2026-08-04 — Future features plan (workspaces, concurrent shadow, GitHub PR integration): planning only, nothing implemented

Task was explicitly planning-and-feasibility only, no code changes. Read this
file (note: task instructions said "backendfix.md at the repo root" — it is
actually at `docs/backendfix.md`, not repo root; flagging in case that's a
stale assumption elsewhere) plus `migration_runs`, `app_users`,
`shadow_clusters`, `app/shadow/concurrency.py`,
`app/services/shadow_cluster_service.py`, the Step Functions ASL, and
searched for any existing GitHub-related code or workspace/project concept
before writing anything.

Three separate planning documents (not one combined doc — the task's final
instruction asked for three, superseding its own earlier "one file" draft
structure), each self-contained with its own prompt at the bottom for a
future session to execute:

- `docs/FUTURE_WORKSPACES_PLAN.md` — new `workspaces` table (owner_identity +
  name + stored `connection_secret_arn`), nullable `migration_runs.workspace_id`,
  backfill migration for existing runs. Explicitly flags that the memory-
  retrieval scoping tradeoff (owner-wide vs workspace-scoped) touches this
  file's own locked "retrieval scopes to owner + `__migration_oracle_corpus__`"
  decision and needs a human decision, not a default — recommends staying
  owner-wide (no change to `app/memory/retrieval.py`) as the safe default.
  Confirmed `app_users` is still dead code (only referenced by the legacy
  `auth_enabled`-gated custom register/login flow in `app/api/routes/auth.py`,
  nothing else joins to it) — do not build workspace ownership on top of it.
  Confirmed `components/team-switcher.tsx` / `components/nav-projects.tsx`
  (frontend) are dead, unwired shadcn template scaffolding, not a decided or
  partially-built workspace switcher — not mounted anywhere in
  `app-sidebar.tsx`. Recommendation: do not build before August 18.
- `docs/FUTURE_CONCURRENT_SHADOW_PLAN.md` — **the actual finding worth
  knowing**: traced `ShadowClusterService.try_admit` and
  `ShadowClusterRepository.count_active` exactly, and the global
  `SHADOW_MAX_CONCURRENT` cap has zero owner-awareness anywhere in the
  admission path — a single owner can already occupy multiple concurrent
  shadow-cluster slots today, no code change needed. The only real gap is a
  small frontend "your active runs" list (Current Migration page currently
  assumes one run in focus, a UI limitation not a backend one) — cheap,
  additive, worth actually building if there's spare time before the
  deadline. The richer "per-user cap M < N layered on the global cap N" is
  real new work with a real infra-cost tradeoff (more concurrent CockroachDB
  Cloud clusters), documented but not recommended now since nobody asked for
  it and there's no contention to solve yet.
- `docs/FUTURE_GITHUB_INTEGRATION_PLAN.md` — GitHub App + webhook
  (recommended over polling), file-path detection heuristic scoped
  explicitly to this project's own `alembic/versions/` convention
  (explicitly does not generalize to arbitrary customer migration tooling —
  scoped out on purpose, not solved), approval model recommendation (a):
  auto-predict then hold at the existing `POST /runs/{id}/approve` gate,
  report to the PR via comment + check run, human approves through a link
  into the app — zero change to the locked approval model. Flags
  auto-approval (option (b)) as a real, separate change to a locked safety
  decision that needs an explicit human sign-off, never a default. States
  the dependency plainly: this feature needs a stored, reusable
  per-repository database connection, which does not exist without
  workspaces (`connection_secret_arn` is created fresh per-run today,
  `f"migration-oracle/connections/{run_id}"` — confirmed via
  `_store_connection_url` in `app/api/routes/runs.py`), so it is downstream
  of Feature 1 and cannot be built first regardless of demo appeal.

Zero code changes in this task. Nothing in "Decisions already locked" above
was touched; two of the three documents explicitly flag where their own
proposals *would* touch a locked decision if built carelessly (retrieval
scoping in workspaces; the approval model in GitHub integration) rather than
silently deciding either one.

### 2026-07-29c — Not a code bug: pasting SQL 404'd because the dev frontend was pointed at the wrong Clerk instance

User reported that pasting a migration SQL and submitting produced Next.js's
own 404 page plus a Clerk "You've created your first user!" banner. Root
cause was environmental, not a code defect — recorded here so it isn't
mis-investigated as a routing/auth bug again.

There are two live Clerk applications in play for this repo:
- `improved-panda-78.clerk.accounts.dev` — real keys, live in the repo-root
  `.env` (`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` / `CLERK_SECRET_KEY`).
  Next.js only auto-loads `.env*` from the app's own directory
  (`frontend/oracle/apps/web/`), never the repo root, so these vars are
  invisible to `next dev` unless copied in.
- `engaging-akita-5.clerk.accounts.dev` — Clerk's zero-config **keyless**
  mode, auto-provisioned and persisted at
  `frontend/oracle/apps/web/.clerk/.tmp/keyless.json` whenever no publishable
  key is present. This is the **correct, intentional** instance for local
  dev — the `docs/TEST_ACCOUNT.md` test user was created inside it.

`apps/web/.env.local` only ever had `NEXT_PUBLIC_API_BASE_URL` — never Clerk
keys — so local dev has always run on the keyless `engaging-akita-5`
instance. When re-verifying this session, I mistakenly copied the
`improved-panda-78` keys from root `.env` into `apps/web/.env.local` to "fix"
what looked like a broken auth state, restarted the dev server, and made it
worse: sign-in then failed outright ("Couldn't find your account.") because
the documented test user doesn't exist in that instance. Reverted
`.env.local` back to API-base-URL-only and restarted again.

With the correct keyless instance restored, live-verified via Playwright
(signed in as the `docs/TEST_ACCOUNT.md` user, pasted
`ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'active'`, clicked
Run Migration Analysis): navigates cleanly to
`/dashboard/migrations/current`, run created (`status=pending`), no 404, no
console errors beyond an expected transient `GET /runs/{id}/approval` 404
(no approval decision exists yet for a pending run — polled and handled
silently by the UI, not user-visible).

What the next session needs to know: never add Clerk keys to
`apps/web/.env.local` for local dev — the keyless `engaging-akita-5` instance
plus `docs/TEST_ACCOUNT.md` is the working setup. The `improved-panda-78`
keys in root `.env` are presumably meant for a deployed frontend origin, not
local dev; if that assumption is wrong, whoever knows the real deployment
plan should say so explicitly before those keys get wired into local dev
again.

### 2026-07-29b — Real end-to-end UI click-through (Playwright MCP): found and fixed 4 real backend bugs, implemented predict-stop, fixed Set-as-current

User asked me to actually click through the live UI (not just audit code) and
verify abort-shadow, stop-predicting, and set-as-current genuinely work. No
browser tool was available at first; user installed the Playwright MCP server
(`.mcp.json`, `@playwright/mcp`) so this could be done for real against the
running dev stack. Created a throwaway Clerk test account
(`docs/TEST_ACCOUNT.md`) using Clerk's built-in `+clerk_test@` email
convention (fixed OTP `424242`, no real inbox needed) so future sessions can
sign in non-interactively.

Getting the stack running at all surfaced the first real bug — everything
below was found by literally clicking buttons and reading the actual
resulting network/console/backend-log state, not by reading code.

**Bug 1 — the Windows uvicorn event-loop fix in `_run_api.py` never worked.**
`uvicorn>=0.36`'s `Server.run()` calls `asyncio.run(coro, loop_factory=...)`
with an explicit factory from `uvicorn.loops.asyncio.asyncio_loop_factory`,
which unconditionally returns `asyncio.ProactorEventLoop` on `win32`. An
explicit `loop_factory` passed to `asyncio.run()` overrides any event loop
*policy* set beforehand, so `_run_api.py`'s
`asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())` before
`import uvicorn` has been dead code under this uvicorn version — psycopg's
async driver was still getting a ProactorEventLoop and `/health` genuinely
reported `"database": "unhealthy"` on every local boot. Fixed by bypassing
`Server.run()` entirely: build `uvicorn.Config`/`uvicorn.Server` manually and
call `asyncio.run(server.serve(), loop_factory=lambda: asyncio.SelectorEventLoop())`
ourselves. Verified: `/health` now reports `"database": "healthy"` with a
real CockroachDB version string, no more corpus-seed-skipped warning at
startup. `_run_api_reload.py` (dev reload mode) was left alone — reload uses
multiprocessing subprocess spawning on Windows, which genuinely needs
Proactor, so it's a different tradeoff not addressed here.

**Bug 2 — `GET /runs` and `GET /runs/metrics/accuracy` 500'd on every call.**
`app/api/routes/runs.py`: both `list_runs` and `get_accuracy_metrics` had
`scoped = session_owner(request) if request else None` followed by a
redundant local `from app.auth.tenancy import auth_enforced, session_owner`
a line or two later. In `list_runs` the local import came *after* the first
use of `session_owner`, so Python treated `session_owner` as a local variable
for the whole function scope and raised `UnboundLocalError` on every single
call — meaning the Overview and History pages were completely broken (500)
the whole time, not something a code read would have caught since the import
statement itself is syntactically valid. Fixed by adding `auth_enforced` to
the existing top-level `from app.auth.tenancy import (...)` and deleting both
redundant local re-imports.

**Bug 3 — `GET /runs/metrics/accuracy` still 500'd after fixing bug 2.**
`app/memory/metrics.py`: the shared `_GRADE_OK` predicate and the approval
breakdown query both used `(:owner_identity IS NULL OR mr.owner_identity = :owner_identity)`.
CockroachDB couldn't infer the SQL type of the `:owner_identity` placeholder
from that shape (`psycopg.errors.IndeterminateDatatype: could not determine
data type of placeholder $1`), regardless of whether the value passed was
`None` or a real string. Fixed with explicit `CAST(:owner_identity AS STRING)`
on both occurrences (first attempted `::STRING` inline-cast syntax, but
SQLAlchemy's `text()` bind-parameter parser doesn't play well with `::`
immediately following a `:param` — `CAST(...)` avoids the ambiguity).
Verified with real curl calls both with and without `owner_identity`.

**Bug 4 — the live shadow SSE stream was completely broken; `sse-starlette`
was never actually a declared dependency.** `GET /runs/{id}/shadow-cluster/stream`
raised `ModuleNotFoundError: No module named 'sse_starlette'` on every call —
confirmed via backend log, not guessed. Because CORSMiddleware never got to
add headers to an unhandled-exception response, the browser reported this as
a CORS failure ("No 'Access-Control-Allow-Origin' header"), not a 500 — the
same masked-exception pattern as bug 2/3, worth remembering next time
something *looks* like a CORS bug. `sse-starlette` was added to this project
in an earlier session but never added to `backend/pyproject.toml`'s
`dependencies`, so it was only ever present in whatever venv it was
originally `pip install`'d into by hand. Fixed: added
`"sse-starlette>=2.1.0"` to `pyproject.toml` and installed it into
`backend/.venv`. This means the live shadow visualization (the floating
panel / full shadow page's real-time updates) has likely been silently
broken since it was built, in any fresh clone or venv — worth calling out
prominently since it's a core demo feature.

**Abort (shadow execution) — confirmed already fully implemented and
working correctly**, once bug 4 was fixed. `handleAbortShadow` (frontend) /
`WorkflowOrchestrationService.abort_for_run` (backend, Step Functions
`StopExecution` + explicit cleanup handler invocation since `StopExecution`
skips the ASL Cleanup state) both already existed and work end-to-end:
clicked Abort on a real running shadow, backend correctly transitioned the
run to `status=failed`/`workflow_status=aborted`, tore down the shadow
cluster, and the UI (after the SSE fix) correctly showed "Cluster destroyed
— no longer exists" with a real event log
(`destroying → destroyed → destroyed·teardown_ms=1692`). The button is
correctly gated behind `hasRealSfnArn(run)` (Abort only makes sense for a
real Step Functions execution — there's nothing to `StopExecution` for the
local/mock verify path). No code changes needed here beyond the SSE fix.

**Stop predicting — genuinely did not exist before; implemented.**
Clicking "Run prediction" gave no way to cancel — the button just went
`disabled` for the full duration with no escape hatch, confirmed by direct
observation. Implemented client-side cancellation via `AbortController`:
`predictRun(runId, { signal })` in `lib/api/endpoints.ts` now threads an
optional `AbortSignal` through to `fetch` (the shared `api()` client in
`client.ts` already passed `signal` through via its `...rest` spread — no
change needed there). `current-migration-workspace.tsx` holds the active
controller in a ref (`predictAbortRef`), a new "Stop" button (visible only
while `predicting`) calls `.abort()`, and `handlePredict`'s catch block
checks `controller.signal.aborted` to show a clean "Prediction stopped."
message instead of a raw fetch error. No backend endpoint needed — the
Bedrock call it aborts is a plain synchronous request/response with no
persisted side effect until the pipeline fully completes, so worst case the
backend keeps computing for a few more seconds after the user gives up
watching and the result is just never read; nothing is left inconsistent.
Verified live: clicked Stop mid-prediction, button state fully recovered to
a clickable "Run prediction" with no reload needed, and the backend log
confirmed the client disconnect didn't raise or crash anything.

**Separately observed, not fully root-caused: prediction can silently freeze
in the UI even without clicking Stop.** Once, after clicking "Run
prediction" normally (no cancel), the button stayed disabled indefinitely —
network log showed the `POST /predict` request completing with `200`, but
the app never visibly proceeded past it, and a direct curl to the backend
confirmed the run had actually reached `awaiting_approval` with a full
prediction *minutes* earlier. A page reload immediately showed the correct,
complete state (assessment, recommendation, approval buttons). Root cause
unconfirmed — a plausible theory is the browser's per-origin HTTP/1.1
connection cap combined with a long-lived SSE connection from an earlier
navigation, but this was not proven. The new Stop button and a manual reload
both work as a recovery path; flagging this as a known intermittent issue
for a future session to actually instrument and root-cause rather than
claiming it's fixed.

**Set as current — was silently inert on the Overview page.**
`app/dashboard/page.tsx`'s "Set as current" was a plain `<button
onClick={() => setCurrentRunId(latest.id)}>` — it wrote to localStorage and
did nothing else, no navigation, no visual feedback, so clicking it looked
like it did nothing. (The equivalent button on the run-detail page,
`migrations/[id]/page.tsx`, was already a correct `<Link
href="/dashboard/migrations/current" onClick={...}>` — only the Overview
one was broken.) Fixed by converting it to the same `<Link>` pattern.
Verified live: click now navigates to `/dashboard/migrations/current` and
the correct run loads there.

Also fixed as a drive-by while getting the dev servers running for this
testing session (Windows-only, unrelated to the bugs above): added
`frontend/oracle/scripts/free-port.js`, wired into
`apps/web/package.json`'s `dev` script (`node ../../scripts/free-port.js
3000 && next dev`) so `npm run dev` always force-kills whatever's already on
port 3000 instead of falling back to 3001 or refusing to start — a detached
`node.exe` surviving a stopped terminal was a recurring annoyance across
sessions on this machine.

What to verify at the start of a future session, since none of this was
covered by unit tests: re-run `python -m pytest tests/unit` (untouched by
this session, should still be 33/33 but wasn't re-run this session — all
verification here was live HTTP/browser, not pytest) and re-run
`npm run typecheck` (confirmed clean after these changes) before assuming
anything above still holds.

### 2026-07-29 — Prediction/recommendation summaries still too long + a Turbopack/OneDrive gotcha

Follow-up to the 2026-07-28 "plain language" prompt change: a user-provided
screenshot showed the model still writing a multi-paragraph, markdown-formatted
essay into `risk_explanation`/`rationale` despite the v2 prompt asking for
1-2 short sentences — models don't reliably obey length instructions alone.

What changed
- Prompts bumped to v3 (`prediction_v3.txt`, `recommendation_v3.txt`): much
  more explicit — exactly 3-4 sentences (not "1-2", per direct user
  instruction), plain text only with markdown explicitly forbidden
  (`**bold**`, headings, numbered/bulleted lists all called out by name), and
  an explicit instruction to put any extra reasoning into `key_assumptions`/
  `uncertainty_notes`/`rollout_steps`/`monitoring_checklist` instead, since
  those already render under "Show details."
- **Added a frontend safety net that doesn't depend on the model complying**:
  `clampProse()` + `stripMarkdownDecoration()` in `map-run.ts` — strips stray
  markdown decoration and hard-caps `risk_explanation`/`rationale` to 4
  sentences for the always-visible summary, moving anything past that into
  the existing "Show details" section instead of ever rendering an unbounded
  essay inline. This means the display is now correct by construction even
  if a future prompt version or model swap doesn't fully comply again.

Environment finding (unrelated to source code, worth knowing)
- This project's frontend lives inside a live OneDrive-synced folder. Next.js
  16 (Turbopack) dev mode writes `.next/dev/types/routes.d.ts` frequently as
  routes are visited, and this collided with OneDrive's sync layer, twice
  producing a **corrupted file** (correctly-closed content followed by a
  stray duplicate tail fragment) that broke `npm run typecheck` with
  confusing syntax errors unrelated to any real source change. Separately,
  Turbopack's dev-mode typed-routes manifest only registers a page **after
  it's been visited at least once** — `npm run typecheck` will report a
  route literal like `/dashboard/migrations/current/shadow` as invalid until
  something actually requests that URL once against the running dev server.
  If `npm run typecheck` ever fails with errors inside `.next/dev/types/*`
  that don't correspond to anything in `app/`/`components/`/`lib/`: it's
  this, not real source breakage. Fix: `rm -rf .next`, restart `npm run dev`,
  curl/visit every route once, then re-run typecheck. Also found (and
  cleaned up) two orphaned `node.exe` dev-server processes left listening on
  ports 3000/3001 from earlier stop attempts in this session — Windows
  doesn't always kill detached child processes when the wrapping shell task
  is stopped; check `netstat -ano | grep :3000` and `taskkill //F //PID` if
  a "port already in use" surprise shows up.

What was verified
- `npm run typecheck`: 0 errors (after clearing the corrupted cache and
  visiting all routes once).
- `npm run lint`: 0 errors, 19 pre-existing-pattern warnings.
- `python -m pytest tests/unit`: 33/33 pass. `python -c "import app.main"`: clean.
- One dev server left running cleanly on port 3000 (the orphaned duplicates
  were killed).

### 2026-07-29 — Real before/after row samples on the Shadow Execution page

Task: capture a small real row sample from the shadow cluster before and
after the migration runs, and show it in a new panel above the lifecycle
timeline on the full Shadow Execution page.

Investigation findings (see docs/ai_audit.md task write-up for the full
report)
- A before/after capture point already existed — `capture_shadow_schema_snapshot()`
  in `app/shadow/schema_snapshot.py`, called from `migration_runner.py`
  around the migration statement. This task extends that exact point rather
  than adding a new one.
- That function opened its own connection separate from the one running the
  DDL. Reworked it to open one connection and do structure introspection +
  row sampling together (`SchemaAnalyzer.analyze_open_connection`), so this
  task adds zero new connections to the pipeline.
- Table names come from parsing `migration_sql` with `sqlglot` (Postgres
  dialect, `find_all(exp.Table)`), mirroring the exact convention already
  used in `app.policy.engine` rather than inventing a second one.
- Deliberately **not** attached to `ExecutionResult`: that model is scalar-only
  (no JSONB) and is written by `PersistResults`, a *different* Lambda later
  in the pipeline with no shadow-cluster connection — getting row data there
  would mean threading potentially-large JSON through Step Functions state,
  risking the 256KB per-transition payload limit. Attached to `ShadowCluster`
  instead, same place as `schema_snapshot_before/after`, same Lambda, no new
  endpoint (served by the existing `GET /shadow-cluster` + SSE stream).
- Confirmed the real (`ccloud_api`) production seed step
  (`load_schema.py` → `ShadowSeeder().seed_rows_only()`) does insert
  synthetic rows by scale tier, so "before" samples have real data there.
  The local/dev orchestrator fallback path only recreates structure
  (`ShadowSchemaLoader`, no rows) — wired the same capture into that path
  too for consistency, but it will honestly show 0 rows; not fixed, since
  changing that path's seed behavior is a separate, bigger decision.

What changed
- `app/shadow/schema_snapshot.py`: added `extract_referenced_tables()`,
  `capture_shadow_snapshot()` (structure + optional row sample, one
  connection — `capture_shadow_schema_snapshot()` kept as a thin
  structure-only wrapper for back-compat), `build_row_ids_for_matching()`.
  Row fetch is by primary key: "before" takes an ordered `LIMIT 20`; "after"
  re-fetches those exact primary-key values (`WHERE pk IN (...)`, composite
  PK via tuple `IN`) so the same conceptual rows are compared, not an
  arbitrary new sample — falls back to a fresh ordered sample (flagged
  `matched_by_pk=false` with a note) if the before sample had no usable PK
  values. Per-table capture failure is recorded on that table's `error`
  field and never raises — capture is enrichment, never blocks the run.
- `shadow_clusters` gained `row_sample_before` / `row_sample_after` (JSONB) —
  migration `l7g3d0e6f485`.
- `migration_runner.py` (real Lambda path) and `orchestrator.py._migrate()`
  (local path) both call the new capture function with `sample_tables` from
  `extract_referenced_tables(migration_sql)`, threading the before sample's
  PK values into the after call.
- `ShadowClusterService.set_schema_snapshot()` takes two new optional
  params (`row_sample_before`/`row_sample_after`); `execute_migration.py`
  passes them through.
- `ShadowClusterResponse` (`app/schemas/observability.py`) exposes both
  fields — automatically available on the existing GET + SSE stream routes,
  no new endpoint.
- Frontend: `mapRowSamplePanel()` in `map-run.ts` (waiting / unavailable /
  ready states; reuses `mapSchemaDiff()`'s per-table column classification
  for color-coding rather than a second diff pass) + new
  `components/shadow-row-samples-panel.tsx`, mounted on
  `shadow/page.tsx` directly above the `<Section title="Live">` block —
  compact-card `ShadowLiveView` (used elsewhere) is untouched. Integrity
  label ("Sample rows from the disposable shadow cluster. Synthetic data at
  the [tier] scale tier, not your production data.") is a visible
  medium-weight line at the panel top, not a footnote.

What was verified
- `python -m pytest tests/unit`: 33/33 pass.
- `python -c "import app.main"`: clean import.
- `npm run typecheck` / `npm run lint`: 0 errors (1 pre-existing unrelated
  warning).
- **Live-tested the actual row-sampling SQL against the real dev CockroachDB
  database** (not a mock): captured a real 3-row sample from `migration_runs`
  (real PK detection, real total-row-count via `SELECT count(*)`), then
  re-fetched the same rows by primary key for the "after" pass
  (`matched_by_pk=True`, 0 rows lost since nothing changed between calls),
  then confirmed the full payload round-trips through `json.dumps`/`json.loads`
  cleanly (UUIDs, timestamps, nested JSONB columns all coerce correctly via
  `_json_safe`). This is real proof the query generation, quoting, and
  PK-matching logic are correct against genuine CockroachDB — not proof of
  the full shadow-cluster-provisioning pipeline end to end (still blocked by
  the local Windows/Python 3.13 boot issue logged below).
- New `shadow_clusters` columns confirmed present via `information_schema`
  after the migration ran.

Known issue carried forward (not new, not fixed here)
- Local backend HTTP boot is still broken on this Windows Python 3.13
  install (ProactorEventLoop vs psycopg async — see the 2026-07-28 entry
  below for the full description). Everything in this task was verified via
  direct script execution with the correct event loop
  (`loop_factory=asyncio.SelectorEventLoop`), not via a running API server.
  A real shadow run through the deployed Lambda/SFN pipeline is still the
  one thing that needs a working environment to confirm end to end.

What the next task needs to know
- The row-sample panel only appears on the full Shadow Execution page by
  design (task requirement) — it is intentionally not part of the compact
  `ShadowLiveView` used in the floating window, the current-migration inline
  card, or the run-detail page.
- `capture_shadow_schema_snapshot()` (structure-only) still exists for any
  caller that doesn't want row sampling; prefer `capture_shadow_snapshot()`
  for anything new.

### 2026-07-28 — UI audit fixes (Parts A/B) + shadow live view rebuild (Part C)

Full scope: `docs/ai_audit.md` Parts A–C, combined with the earlier
`docs/SHADOW_LIVE_REPRESENTATION_PLAN.md` research pass. Decisions taken
per user answers: SSE transport (not polling), floating panel auto-hides on
the dedicated shadow page, chaos runs get a real `run_kind` field, accuracy
"Succeeded" redefined to % of graded runs that passed, storage-unverifiable
floor = 1 MB, demo database generalized (not judge-specific cluster — that's
still a followup task), "measure" stays a frontend-only pseudo-stage (no new
backend enum value).

What changed — blockers (A1)
- Floating shadow window (`components/shadow-execution-window.tsx`)
  auto-suppresses via `usePathname()` while on
  `/dashboard/migrations/current/shadow`, so the dedicated page's own live
  view is never duplicated on screen.
- Sidebar identity (`components/owner-identity-field.tsx`) now shows the
  Clerk display name/email, raw `user_...` id moved to the `title` tooltip.
- Clerk dev-mode banner: not a code fix — flagged as an ops task (needs a
  Clerk Production instance + verified custom domain before demo day).
- `migration_runs.run_kind` (`standard`/`chaos`/`debug`) added end to end
  (model, migration, service, repository filter, API `exclude_kinds` param);
  Overview "Recent" list and `judge_chaos_checks.py` runs now use it so
  deliberate failure tests stop appearing on the first screen a judge sees.

What changed — correctness (A2)
- `backend/app/memory/metrics.py`: rewrote the accuracy endpoint. `GRADED`
  was already correctly scoped; `ACCEPTED`/`SUCCEEDED` were querying a
  completely different, unrelated population (all runs any owner, via
  `recommendation_outcome.linked_evidence`, near-permanently 0/0). Replaced
  with `migration_success_rate` (% of the same graded population that
  actually passed) and an honest `approval_breakdown` (proceed / accept
  recommended / cancel / awaiting decision — real counts, not a rate). Also
  scoped every query to `owner_identity` when known, matching the Recent
  list's scoping. Found and fixed an unrelated latent bug in the same file:
  the high-risk-flag precision/recall query filtered on
  `outcome_class IN ('failure','partial','timeout')`, but those values never
  existed (`app.grading.engine.classify_outcome` only ever returns
  `clean_ok`/`warned_ok`/`bad`/`timeout`) — only `timeout` was ever matching,
  silently undercounting every non-timeout bad outcome.
- Confidence: raw was already not the headline in current code (that finding
  didn't reproduce — likely a stale screenshot). Added `rawPercentLabel`
  shown alongside the adjusted headline, and moved the four-signal
  adjustment list out of the collapsed "Show details" toggle to sit directly
  under the confidence number.
- Storage grading: added a real `storage_unverifiable` floor (1 MB) to
  `app/grading/engine.py` + `grading.yaml`, mirroring how `duration_unverifiable`
  already handles timeouts — below the floor, storage is graded unverifiable
  instead of a trivial "within band" pass. New `grades.storage_unverifiable`
  column (`storage_within_band` now nullable) via migration `k6f2c9d5e374`.
- Redundant lifecycle steps (Tear down / Torn down): fixed by the Part C
  rebuild below (5-stage rail, not fixed twice).

What changed — database attach flow (Part B)
- `current-migration-workspace.tsx` reordered: connect database first, SQL
  second, prediction third (previously SQL-first). New shared
  `ConnectDatabaseFields` component: single primary read-only-URL input with
  visibly-styled placeholder, ARN moved behind a secondary toggle, copyable
  GRANT/REVOKE help block sourced from `prepare_judge_demo_db.py`'s existing
  role pattern.
- Staged discover progress: extended the same `pipeline_progress` mechanism
  already used for predict — `app/schema_analysis/discovery.py` now takes an
  `on_stage` callback (connecting → authenticating → reading schema → done),
  wired through `SchemaDiscoveryService.discover_and_persist`;
  `/pipeline-progress` route relaxed to also serve progress while
  `status == pending` (previously predict-only).
- Client-side missing-table warning next to the SQL editor
  (`findUnknownTableReferences`, heuristic regex — not a real parser, the
  backend's `missing_referenced_table` policy flag is still authoritative).
- Demo database: un-gated the "Try the demo database" button from
  `NEXT_PUBLIC_ENABLE_DEBUG_TOOLS` — it's now a first-class, always-visible
  affordance on the connect step, clearly labeled "not your data." Backend
  endpoint (`/runs/debug/demo-with-db`) unchanged and was never itself
  debug-gated — it already reads `DEMO_READONLY_DATABASE_URL` /
  `.judge_ro_database_url`, so this works with whatever demo DB is configured.
  **Provisioning an actual standing judge-facing cluster is still open** —
  user said they'll configure that separately.

What changed — shadow live view (Part C), backend
- `app/shadow/job_progress.py` (new): captures the CockroachDB background
  job id via a psycopg3 notice handler on the connection running the DDL
  (fires before the blocking statement returns), then polls `SHOW JOB <id>`
  (never bare `SHOW JOBS`) on a second connection running concurrently.
  Never raises — reports failure via `JobProgressResult.succeeded`/`.error`
  so partial observations survive a migration failure. **Not live-validated
  against a real shadow cluster in this session** (would need a real SFN run)
  — degrades honestly to the existing post-hoc `job_watch` snapshot if the
  notice never arrives, per the "never fabricate progress" rule.
- `app/shadow/schema_snapshot.py` (new): before/after structural snapshots
  of the shadow cluster (write-capable connection, so read-only enforcement
  is intentionally skipped — that check protects the customer's DB, not this
  disposable one) + `build_schema_diff()` (added/removed/changed/unchanged
  per table/column/index/constraint, color-neutral — never implies quality).
- `shadow_clusters` gained `event_log` (JSONB array, appended on every status
  transition and timing merge — real replay history, not last-write-wins),
  `schema_snapshot_before`, `schema_snapshot_after` (migration `k6f2c9d5e374`).
- Wired into both execution paths: `migration_runner.py` (the real
  Step-Functions/Lambda path via `execute_migration.py`) and
  `orchestrator.py._migrate()` (the local/dev fallback path), so both
  capture job progress and schema snapshots the same way.
- `GET /runs/{id}/shadow-cluster/stream` (new, `sse-starlette`): SSE
  endpoint replacing polling for the shadow-cluster row specifically — emits
  on change plus a heartbeat, stops on terminal status or 30-minute ceiling.
  `sync-workflow` (SFN status) is intentionally NOT folded into this stream
  since it's a side-effecting AWS call, not a passive read; frontend keeps a
  separate slower poll for that. `SessionAuthMiddleware` now accepts the
  bearer token via a `?token=` query param on this one route only, since
  browser `EventSource` can't set custom headers.

What changed — shadow live view (Part C), frontend
- New `components/shadow-live-view.tsx` replaces the retired
  `shadow-live-panel.tsx` everywhere (dedicated shadow page, floating window,
  run-detail page, current-migration-workspace inline panel — 4 call sites).
  Three bands: 5-stage lifecycle rail (provision/seed/execute/measure/
  teardown — "measure" is a frontend-only pseudo-stage, current once
  `migrate_ms` is recorded but the cluster hasn't started tearing down),
  stage-dependent center panel (job id/description/`running_status`/
  `fraction_completed` bar when live observations exist, honest "no live
  progress observed" text when they don't — never a fabricated bar), and an
  append-only event log rendered from `shadow_clusters.event_log`.
- New `lib/api/shadow-stream.ts` (`useShadowStream`): SSE client via native
  `EventSource`, auto-reconnects (browser built-in), resolves the Clerk/
  legacy token for the `?token=` param.
- Same component doubles as the replay view for finished runs (`isLive=false`
  falls back to the persisted `shadow` + full event log instead of a live
  connection) — a judge clicking into a past run now sees the same rich view,
  not just static final numbers.
- `mapShadowLiveStages`/`ShadowLiveStage` (6-step mapper) removed, replaced
  by `mapShadowLifecycleRail` (5-step) + `mapExecutePanel` + `mapSchemaDiff`
  + `mapCostStrip` + `mapShadowEventLog` in `lib/api/map-run.ts`.

What was verified
- `npm run typecheck` (tsc --noEmit): 0 errors, both after Workstreams 1-3 and
  again after the full Part C rebuild.
- `npm run lint`: 0 errors; 20 warnings, all matching pre-existing
  `react-hooks/set-state-in-effect` / `react-hooks/purity` patterns already
  present throughout this codebase (not new rigor gaps).
- `python -m pytest tests/unit`: 33/33 pass (one test updated for the new
  `run_kind`/`exclude_kinds` service params).
- `python -c "import app.main"`: clean import with every change applied.
- Migration `k6f2c9d5e374` applied for real against the live dev CockroachDB
  Cloud database (see "known issue" below for how long that took and why).
  Confirmed via direct `information_schema` queries: `migration_runs.run_kind`
  + index, `shadow_clusters.event_log`/`schema_snapshot_before`/
  `schema_snapshot_after`, `grades.storage_unverifiable` +
  `storage_within_band` now nullable — all present. `alembic current` shows
  `k6f2c9d5e374 (head)`.
- Confirmed against the user's own already-running Next dev server (port
  3000, hot-reloaded): landing page 200, `/dashboard` 307 (expected auth
  redirect), no client errors from the reload.

Known issues discovered (not caused by this change, flagged for awareness)
- **CockroachDB schema-change DDL is genuinely slow on this cluster tier** —
  each `ADD COLUMN`/`ALTER COLUMN`/`CREATE INDEX` ran as its own background
  job taking 20–90s. A 6-statement migration took ~4 minutes wall clock.
  `alembic upgrade head` looked "stuck" from the CLI (no per-statement
  progress output) but was actually working — worth keeping in mind for any
  future multi-statement migration; consider a progress-logging wrapper or
  splitting large migrations.
- **Local backend boot is broken on this Windows Python 3.13 install**:
  `psycopg` async mode requires a `SelectorEventLoop`, but neither plain
  `uvicorn app.main:app` nor the project's own documented fix
  (`backend/_run_api.py`'s `asyncio.set_event_loop_policy
  (asyncio.WindowsSelectorEventLoopPolicy())`) actually prevents uvicorn from
  using `ProactorEventLoop` on this specific interpreter — `/health` reports
  `"database":"unhealthy"` with a `ProactorEventLoop` `InterfaceError` even
  through the documented launcher. Direct `psycopg` calls work fine when the
  event loop is set correctly by hand
  (`asyncio.run(..., loop_factory=asyncio.SelectorEventLoop)`), and `alembic`
  (sync driver) is unaffected — this is specifically a Python 3.13 + uvicorn +
  async-psycopg interaction, pre-existing and unrelated to this change. Not
  fixed here (out of scope); next session on this machine should investigate
  whether `_run_api.py`/`_run_api_reload.py` need a `loop="asyncio"` +
  explicit `loop_factory` passed into `uvicorn.run()` rather than relying on
  `set_event_loop_policy` alone, since that mechanism appears insufficient on
  this Python version. Because of this, the SSE endpoint and the full
  Part C job-progress/schema-diff pipeline could **not** be live-exercised
  end to end in this session — verified by code review, type/lint/unit-test
  checks, and direct DB introspection only.

What the next task needs to know
- Provisioning a real standing demo CockroachDB cluster (Part B's remaining
  item) and getting a live shadow run through the new job-progress/schema-diff
  pipeline are the two biggest open verification gaps — both need a working
  local boot (see known issue above) or a deployed environment.
- `docs/ai_audit.md` has the full verification trace (REAL/ALREADY
  FIXED/PARTIALLY RIGHT/WRONG per finding) this change log summarizes.

### 2026-07-25 — Live shadow box + no mock verify in UI

What changed
- New `ShadowLivePanel`: live cluster lifecycle from `shadow.status` +
  `stage_timings` (provision → ready → seed → migrate → teardown), cluster
  facts, and prediction-vs-measured comparison while the workflow runs.
- Current Migration, Shadow Execution page, and run detail poll
  `sync-workflow` + `shadow-cluster` + `execution-result` mid-flight.
- Removed silent fallback to `verify-local` mock shadow; Start shadow requires
  real Step Functions. Fake-migration UI gated behind
  `NEXT_PUBLIC_ENABLE_DEBUG_TOOLS=true`.
- Landing ProductPreview metrics labeled as illustration-only sample.

What was verified
- Typecheck passes. Live completed run `d0bd7fd8-…` has real provider
  `cockroachdb_cloud_api`, stage timings in ms, execution actuals, and grade
  bands — UI maps these (no invented numbers).

### 2026-07-25 — Remaining demo gaps (sweeper, policy, abort, /ui)

What changed
- SAM redeploy: stack `UPDATE_COMPLETE`; sweeper physical name
  `migration-oracle-shadow-sweeper`; EventBridge schedule live; empty-event
  invoke succeeds (no `event.run_id is required`).
- Policy: `missing_referenced_table` rule (`block`) when SQL references tables
  absent from the schema snapshot.
- Pipeline progress: cleared unless run status is `predicting`; also cleared on
  approve / start-workflow.
- Abort: `POST /runs/{id}/abort-workflow` + Next Abort control; StopExecution
  plus explicit cleanup handler teardown.
- Legacy `/ui` StaticFiles mount removed; docs/README/`scripts/dev.py` point at
  Next.js. Windows: prefer `backend/_run_api_reload.py` / `scripts/dev.py`.
- Ops notes: `docs/DEMO_OPS.md`. Chaos script fail-fast predict ceilings +
  `JUDGE_SKIP_DUAL`.

What was verified live
- missing_table → policy `block` + flag `missing_referenced_table`.
- Abort mid-shadow → run `failed` / workflow `aborted`; Cloud cluster torn down.
- Bedrock traces: `attempts` + `repair_retried` on fake-migration predict.
- Dual shadows: both start-workflow admitted (`SHADOW_MAX_CONCURRENT=2`); abort
  both; Cloud list can lag ~15–30s after destroy — poll then confirm zero
  `labels.app=migration-oracle` leftovers.
- Sweeper Lambda invoke OK.

### 2026-07-25 — Judge walkthrough (real shadow + fixes)

What was driven (not claimed from unit tests)
- Full PATH1 on real `ccloud_api` + SFN: discover RO `customer_demo.customers`
  (5000 rows) → predict → proceed → start-workflow → Cloud cluster
  `mo-d0bd7fd8bc124520` with `labels.app=migration-oracle` → teardown → grade +
  memory → second similar migration retrieved first graded memory (closed loop).
- PATH2: concurrency cap DB probe `[True,True,False]` + slot timeout; local
  sweeper clean; tag confirmed on live cluster. No deliberate orphan / mid-flight
  kill / three live shadows.
- PATH3: bad ARN 422, unreachable DB 408, accept_recommended completed with no
  shadow, cancel → failed, DROP TABLE block + override rationale on
  `GET /runs/{id}/approval`. Invalid SQL now `policy_decision=block`.
- PATH4/5 Playwright: pages render; corpus badged; no fake auth chrome.

Real stage timings (PATH1 run `d0bd7fd8-…`)
- create 2.2s · discover 19.5s · predict 59.7s · approve 11.6s · shadow wall
  ~107s · second predict 56.9s
- Shadow stage_timings ms: provision 3857 · ready 8093 · seed 7633 · migrate
  8061 · teardown 2933 · cluster lifetime ~58s

Per-run shadow cost
- Not determined in USD (BASIC plan / serverless RU billing). Lifetime ~58s.

What changed (fixes)
- `RetrievedMemory.memory_id` + UI graded/corpus labels on retrieval cards.
- `parse_failure` policy decision `allow_with_warning` → `block`; PolicyEngine
  re-reads YAML each analyze (`get_policy_file_fresh`) because uvicorn reload
  does not watch `.yaml`.
- Next UI: `getApproval` + recorded decision / override rationale panel.
- Windows helpers: `backend/_run_api.py`, `backend/_run_api_reload.py`.
- Judge drivers: `judge_path1_live.py`, `judge_path3_failures.py`, artifacts.

What remains open (see Open Questions + WALKTHROUGH.md)
- SAM redeploy for sweeper; missing-table risk flag; stale pipeline-progress
  during shadow; mid-flight kill / dual shadow / Bedrock repair UI not fully
  browser-proven.

### 2026-07-24 — Wire Next.js frontend end-to-end

What changed
- New API layer under `frontend/oracle/apps/web/lib/api/`:
  client (`NEXT_PUBLIC_API_BASE_URL`, default `http://127.0.0.1:8000`),
  OpenAPI snapshot + generated `schema.ts` (`npm run gen:api`),
  typed `endpoints.ts`, `map-run.ts` mapping module, owner/localStorage helpers,
  `usePolling`.
- Current Migration workspace: create (SQL / fake-migration), discover,
  predict + pipeline-progress, assessment, retrieval transparency (DVI note +
  DDL side-by-side), three real approvals, shadow start (SFN or verify-local),
  outcome (grade / memory / shadow / execution).
- Overview, history, run detail (`/dashboard/migrations/[id]` with lifecycle +
  model traces), memory browser + health, settings (owner + ARN + API base).
- Shell honesty: removed Clerk-style auth routes (redirect to dashboard), fake
  sidebar user, broken `/docs` links, coming-soon repo/compare methods, dual
  Postgres→Cockroach chrome, mock CURRENT_MIGRATION data.

Backend schema touched (and why)
- `MemoryResponse` / `MemoryListItem`: added `not_a_graded_run`, `source_url`,
  `ui_label`, `integrity_kind` via shared `integrity_fields()` so the memory
  browser can distinguish corpus rows without inventing client-side heuristics.
- CORS was already env-configurable (`CORS_ORIGINS`); documented deployed-origin
  placeholder in `.env.example`. No wildcards.

Frontend features removed (and why)
- Sign-in / sign-up / OAuth / get-started decorative auth — backend has no auth.
- Fake `operator@migrationoracle.dev` sidebar user.
- `/docs` nav (no route).
- Coming soon: Connect Repository, Compare Schema.
- Mock assessment fields (benefits, fabricated riskBreakdown).
- Dual database source/target selector.
- Hardcoded dashboard command-center / CURRENT_MIGRATION / live shadow mocks.

What was verified
- `npm run typecheck` in apps/web passes.
- OpenAPI export from FastAPI + `openapi-typescript` generation succeeds.
- Mapping and endpoint modules align with live schemas.

What was NOT fully verified (testing task needs to know)
- Full real Bedrock predict → approve → SFN shadow → grade → memory on the
  Next UI against a live API (needs `scripts/dev.py restart` + AWS/Bedrock).
- Discover against a real customer DB / Secrets Manager ARN (error mapping is
  coded from backend status codes; not live-exercised here).
- Deployed frontend origin not added to CORS — local defaults only; set
  `CORS_ORIGINS` when a public URL exists.
- Orphaned unused auth form components (`login-form.tsx`, `signup-form.tsx`)
  remain on disk but routes redirect away.
- Legacy `/ui` intentionally untouched and still the proven fallback.

Next task should
- Run a full closed loop through the Next console (fake-migration path first,
  then real SFN if configured).
- Confirm memory health + corpus badges with seeded corpus.
- Confirm accuracy overview with zero graded runs stays honest.
- Only after a successful end-to-end Next run: decide whether to retire `/ui`.

## Open Questions

Anything you hit that needs a human decision. Do not guess and move on.

- Deployed frontend URL for CORS (when known).
- Whether to delete orphaned login/signup form components after judges never
  need them (harmless today).
- Exact per-run USD from Cockroach Cloud invoice / BASIC RU pricing for the
  demo script voiceover.
