# GitHub App setup — PR integration

Companion to [`docs/FUTURE_GITHUB_INTEGRATION_PLAN.md`](FUTURE_GITHUB_INTEGRATION_PLAN.md).
The code side of this feature (webhook receiver, repo-to-workspace link,
migration-file detection, prediction + PR comment/check-run reporting) is
built and unit-tested. **The GitHub App registration itself is a manual
step on github.com that only a human with a GitHub account can do** — this
doc is the exact sequence. Nothing here has been run for real yet (no App
is registered), so treat each step as unverified until you've walked
through it once end to end.

## 0. Prerequisite: a public HTTPS URL for the backend

GitHub needs somewhere real to POST the webhook. Two options:

- **Deployed backend** — if the FastAPI control plane is already hosted per
  [`docs/HOSTING.md`](HOSTING.md) (Railway/Fly/ECS), the webhook URL is
  `https://<your-api-domain>/webhooks/github`.
- **Local testing** — run the backend locally (`uvicorn app.main:app`) and
  tunnel it: `ngrok http 8000` (or `cloudflared tunnel --url http://localhost:8000`).
  The webhook URL is `https://<tunnel-subdomain>/webhooks/github`. Free
  ngrok subdomains change every restart — update the webhook URL in the
  App's settings each time, or use a reserved/paid subdomain.

## 1. Register the GitHub App

Go to **github.com → Settings → Developer settings → GitHub Apps → New GitHub App**
(personal account) or the equivalent under an organization's settings if
this should live under an org.

| Field | Value |
| --- | --- |
| GitHub App name | Anything unique, e.g. "Migration Oracle (yourname)" |
| Homepage URL | Your frontend URL (or the repo URL if nothing is hosted yet) |
| Webhook → Active | ✅ checked |
| Webhook URL | `https://<your-domain>/webhooks/github` (from step 0) |
| Webhook secret | Generate a random string (e.g. `openssl rand -hex 32`) and **save it** — this becomes `GITHUB_WEBHOOK_SECRET` |

**Repository permissions** (left sidebar → Permissions & events):

| Permission | Access |
| --- | --- |
| Contents | Read-only — fetches the matched migration file's content |
| Issues | Read and write — PR comments are posted via the Issues API (a PR *is* an issue under the hood) |
| Pull requests | Read and write — lists changed files in the PR |
| Checks | Read and write — posts the check run |
| Metadata | Read-only (mandatory, pre-selected) |

**Subscribe to events:** check **Pull request** (nothing else is needed —
`GithubWebhookService` only acts on `pull_request` events; every other
subscribed event is acknowledged with `ignored` and does nothing).

**Where can this GitHub App be installed:** "Only on this account" is the
right default for a single pilot repo. Choose "Any account" only if this
is meant to become installable by other GitHub users/orgs later.

Click **Create GitHub App**.

## 2. Collect the three credentials

On the App's settings page (`github.com/settings/apps/<your-app>`):

1. **App ID** — shown near the top → `GITHUB_APP_ID`.
2. **Generate a private key** (button further down the page) → downloads a
   `.pem` file. The **entire file contents**, header/footer included, is
   `GITHUB_APP_PRIVATE_KEY`. Most hosts want this as a single env var value
   with literal `\n` for line breaks (check your host's docs — Railway/Fly
   both accept multi-line values pasted directly; some CI systems need the
   `\n`-escaped form).
3. **Webhook secret** — the value you generated in step 1 →
   `GITHUB_WEBHOOK_SECRET`.

Set all three in the backend's environment (`.env` locally, or your host's
env var UI — [`docs/HOSTING.md`](HOSTING.md)), then restart the API.

```env
GITHUB_APP_ID=123456
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
GITHUB_WEBHOOK_SECRET=<the random string from step 1>
```

## 3. Install the App on the target repo

From the App's public page (`github.com/apps/<your-app-slug>`) or the
**Install App** entry in the App's left sidebar: choose the account/org,
pick **Only select repositories**, and select the repo you want Migration
Oracle to watch. No installation ID needs to be recorded manually — GitHub
includes it in every webhook payload, and `GithubAppClient` exchanges it
for a fresh installation access token per webhook.

## 4. Link the repo to a Migration Oracle workspace

In the app: **Settings → Workspaces**, pick (or create) the workspace whose
stored database connection PR-triggered runs against this repo should use,
click **Link repo**, and enter:

- **GitHub repo**: `owner/repo`, exactly matching the repo on GitHub.
- **Migration file glob**: which changed-file paths in a PR count as "a
  migration." Defaults to this project's own convention,
  `backend/alembic/versions/*.py`. **Change this to match the target
  repo's actual migration tooling** — e.g. `db/migrate/*.sql` for a
  hand-written-SQL convention, or wherever the target repo keeps its
  migration files.

One repo can only be linked to one workspace at a time (enforced by the
API — linking a repo that's already linked elsewhere returns `409`).

### A real limitation, stated plainly

`extract_migration_sql` (`app/services/github_webhook_service.py`) can only
pull a single raw SQL statement out of the matched file:

- A `.sql` file's content is used as-is.
- A `.py` file (Alembic's shape) is scanned for `op.execute("...")` /
  `op.execute('''...''')` calls; the **first** one found is used.
- A migration expressed purely through schema-builder calls
  (`op.add_column`, `op.create_table`, ...) with no `op.execute(...)` at
  all has no extractable SQL — the webhook posts an explanatory PR comment
  instead of a prediction, rather than guessing.
- `MigrationRunService.create_migration_run` also requires the extracted
  text to be a **single** SQL statement (CockroachDB's per-statement-DDL-
  commit semantics — see `docs/backendfix.md`'s locked decisions). A
  migration file with multiple `op.execute(...)` calls only uses the first
  one; a file whose single `op.execute(...)` contains multiple `;`-
  separated statements fails cleanly with a validation error, surfaced the
  same way.

This is a real, intentional scope boundary, not a bug — building a general
multi-framework, multi-statement migration-SQL synthesizer is explicitly
out of scope for this plan (see the plan doc's "Proposed Detection
Heuristic" section). Point the glob at a repo/convention where the
migration file's raw SQL is directly extractable, at least for now.

## 5. Open a PR and watch it work

Open a PR in the linked repo that adds/changes a file matching the glob,
with a single `op.execute("...")`-wrapped SQL statement (or a plain `.sql`
file, if the glob targets those). Within a few seconds you should see:

- A **check run** named "Migration Oracle" on the PR (conclusion is always
  `success` or `neutral`, never `failure` — this integration is advisory
  only and never blocks a merge, per the plan's resolved Open Question).
- A **comment** with the prediction (duration, storage growth, rollback
  risk, confidence), the recommendation, the policy decision and any risk
  flags, and a link into the app.

Click that link, sign in, and approve through the **exact same**
`POST /runs/{id}/approve` flow every other run uses — proceed / accept
recommended / cancel, with the same mandatory override-rationale when
`policy_decision=block`. Nothing about the approval model changed for a
PR-triggered run (see the plan's "Proposed Approval Model" section).

Once the shadow run reaches a terminal state, a **follow-up comment**
posts the measured outcome against the original prediction.

## 6. Verifying before you have a real App

`python scripts/prove_github_integration.py` (from `backend/`, with the dev
API running) proves everything **except** the actual calls to
`api.github.com`, which are mocked — because verifying those for real
requires exactly the manual steps above. It covers:

- Real HTTP: linking a repo to a workspace, the one-repo-one-workspace
  `409`, and a webhook with a bad signature being rejected `401`.
- In-process (real DB, mocked GitHub client): a signed webhook payload
  correctly resolves the linked workspace, extracts SQL from a synthetic
  Alembic-shaped file, creates a real `MigrationRun`, runs real schema
  discovery against a real database, runs real prediction, and the PR
  comment that *would* have been posted contains the run's actual
  predicted numbers — not placeholder text.

It needs `GITHUB_APP_ID` / `GITHUB_APP_PRIVATE_KEY` set to **any non-empty
placeholder value** (the client that would use them for real is mocked)
and `GITHUB_WEBHOOK_SECRET` set to a real value (a real HMAC signature is
computed with it). The script prints exactly which env vars are missing if
you haven't set them yet.

**Passing that script is not the same as this plan's own end-to-end bar.**
The plan's verification section asks for a real test repository and a real
PR — that only happens once you've completed steps 1–5 above.
