# Slack notifications — what's built, what's verified, what's left

Written 2026-08-03. Slack is not one of the four CockroachDB hackathon tools
and not an AWS service — it earns nothing on the judging rubric directly. It
exists because lifecycle notifications (prediction ready, shadow started,
shadow completed/failed) are a genuinely useful thing for a control plane
whose runs take minutes, not because it was a checkbox to fill.

## What it does

Four lifecycle events send a Slack DM to whoever connected Slack, via
`chat.postMessage`:

| Event | Fires from | When |
| --- | --- | --- |
| `prediction_ready` | `PredictionPipelineService._notify_prediction_ready` | After a prediction commits, run enters `AWAITING_APPROVAL` |
| `shadow_started` | `WorkflowOrchestrationService._notify_shadow_started` | After a fresh Step Functions execution starts (not on idempotent re-entry) |
| `shadow_completed` | `WorkflowOrchestrationService._notify_terminal` | First time `sync_status` observes the run reach `COMPLETED` |
| `shadow_failed` | `WorkflowOrchestrationService._notify_terminal` / `abort_for_run` | First time `sync_status` observes a non-success terminal state, or an operator aborts |

Every notification path is best-effort: any lookup, decrypt, network, or
Slack API failure is logged and swallowed. **A Slack outage can never fail a
migration run** — same posture as MCP investigation, changefeeds, and every
other shadow-cluster enrichment in this app.

## Architecture

- `backend/app/services/slack_oauth_service.py` — OAuth v2 install/callback:
  signed TTL-bounded `state` (HMAC-SHA256, CSRF protection), `oauth.v2.access`
  code exchange, Fernet-encrypted token at rest, upsert one row per
  `owner_identity`.
- `backend/app/services/slack_notification_service.py` — resolves a channel,
  decrypts the token, posts Block Kit messages via `chat.postMessage`.
- `backend/app/database/models/slack_installation.py` — one
  `slack_installations` row per app user. Migrations `p1k7h4c8d598` (table)
  and `q2l8i5d9e6a7` (`authed_user_id` column).
- `backend/app/api/routes/slack.py` — `GET /api/slack/install`,
  `GET /api/slack/oauth/callback`, `GET /api/slack/status`,
  `POST /api/slack/disconnect`.
- Frontend: a "Slack notifications" panel in
  `frontend/oracle/apps/web/app/dashboard/settings/page.tsx` — connect
  status, Connect/Disconnect. No channel picker, no per-event opt-out (see
  Known limitations).

## Channel resolution — DM, not a named channel

`SlackNotificationService.send_message` resolves the destination in this
order:

1. An explicit `channel` argument (none of the four lifecycle call sites
   pass one).
2. `installation.authed_user_id` — the Slack user ID of whoever completed
   the OAuth install, captured from `oauth.v2.access`'s `authed_user.id` and
   persisted by migration `q2l8i5d9e6a7`. `chat.postMessage` with a user ID
   as `channel` opens (or reuses) a DM — this needs no scope beyond
   `chat:write`.
3. `SLACK_DEFAULT_CHANNEL` (default `"general"`) — last resort, only reached
   for installations that predate the `authed_user_id` column.

This was a deliberate fix, not the original design. The branch as merged
used a single hardcoded `SLACK_DEFAULT_CHANNEL` for every user with
`chat:write`-only scope. A bot with only `chat:write` cannot post to a
channel it hasn't been invited to — every notification would have failed
with `not_in_channel`, silently (the service catches it, logs a warning,
returns `False`), and every run would have looked fine while zero
notifications ever arrived. DMing the installer avoids that failure mode
entirely.

## Verified live, 2026-08-03

Against the real Slack app (`client_id=11723832273251.11726737575141`) and
the real local backend on `:8003`:

```
$ curl -H "Authorization: Bearer $JWT" http://127.0.0.1:8003/api/slack/status
{"configured":true,"connected":false,"team_id":null,"team_name":null,"scope":null}
```

`configured: true` confirms `SLACK_CLIENT_ID` / `SLACK_CLIENT_SECRET` /
`SLACK_REDIRECT_URI` are all present and non-empty server-side.
`connected: false` reflects the state *before* the real install below —
see "Verified live end-to-end" for the completed round-trip.

```
$ curl -H "Authorization: Bearer $JWT" http://127.0.0.1:8003/api/slack/install
{"authorize_url": "https://slack.com/oauth/v2/authorize?client_id=11723832273251.11726737575141
   &scope=chat%3Awrite
   &state=a1480265c264ab5cebadd532fb1ff185ee7eeab1c02db155d47fb8f8db0fec9e.eyJ2...
   &redirect_uri=http%3A%2F%2Flocalhost%3A8003%2Fapi%2Fslack%2Foauth%2Fcallback",
 "state": "a1480265c264ab...", "expires_in_seconds": 600}
```

A real, correctly-formed Slack OAuth v2 authorize URL — right `client_id`,
`chat:write` scope, and (this is the thing that was actually broken before
this session — see below) `redirect_uri` pointing at **:8003**, matching
where the backend actually runs.

Also confirmed this session:
- Unauthenticated `GET /api/slack/install` and `GET /api/slack/status` both
  return `401`, not a crash — auth middleware correctly gates them.
- `SlackOAuthError` → 503, `SlackStateError` → 400 now registered in
  `_STATUS_BY_ERROR` (previously both fell through to the generic 400
  default, mislabeling a server misconfiguration as a client error).
- `alembic upgrade head` applied both `p1k7h4c8d598` and `q2l8i5d9e6a7`
  cleanly against the live CockroachDB Cloud database.
- Backend restart, `ast.parse` on every touched file, and `tsc --noEmit` +
  `eslint` on the touched frontend files all clean.

## Verified live end-to-end, 2026-08-03

The full browser OAuth round-trip and real DM delivery were confirmed
against the real Slack workspace ("CockroachDB x AWS hackathon"), by hand:

1. `/dashboard/settings` → **Connect Slack** → approved on Slack's real
   consent screen → landed back on `?slack=connected` with the green
   banner rendering correctly.
2. `GET /api/slack/status` reported `connected: true` with a real
   `team_name`, confirming the `slack_installations` row persisted with a
   real encrypted token and a populated `authed_user_id`.
3. A real run (`ALTER TABLE demo_items ADD COLUMN discount_pct INT NOT NULL
   DEFAULT 0`, run `8022a982-…`) produced three real Slack DMs in order —
   *Prediction Ready* (`awaiting_approval`), *Shadow Migration Started*
   (`running`), *Shadow Migration Completed* (`completed`) — each with the
   real migration SQL, real run ID, real timestamp, and an "Open in
   Migration Oracle" button.
4. **`chat:write` alone was sufficient** — no `im:write` scope was needed
   for the DM to land. The hedge earlier in this doc about possibly needing
   `im:write` did not turn out to be necessary.

Slack's own UI note on the DM thread — *"Sending messages to this app has
been turned off"* — is expected and correct: it means the user can't reply
back to the bot (no Events API / interactivity configured, matching the
"Known limitations" note below about `SLACK_SIGNING_SECRET` being unused).
It has no effect on outbound notifications.

## Local setup

Five env vars had to be fixed before this worked at all — the branch as
merged shipped with a wrong port and no state secret:

```bash
SLACK_REDIRECT_URI=http://localhost:8003/api/slack/oauth/callback   # was :8000 — nothing listens there
SLACK_STATE_SECRET=<generate: python -c "import secrets; print(secrets.token_hex(32))">
SLACK_TOKEN_ENCRYPTION_KEY=<generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
SLACK_INSTALL_SUCCESS_REDIRECT=http://localhost:3000/dashboard/settings?slack=connected
SLACK_INSTALL_ERROR_REDIRECT=http://localhost:3000/dashboard/settings?slack=error
FRONTEND_URL=http://localhost:3000
```

Without `SLACK_STATE_SECRET`, `SlackOAuthService._state_secret()` raises and
`/api/slack/install` fails outright. Without the port fix, Slack calls back
to a dead port. Without absolute redirect URLs, a successful OAuth exchange
still 404s (a relative path resolves against the *backend's* origin, not
the frontend's).

`SLACK_TOKEN_ENCRYPTION_KEY` matters beyond local dev: unset, the service
derives an ephemeral key from `DATABASE_URL` (see `_get_fernet()` in
`slack_oauth_service.py`). Per `docs/COCKROACH_ACCOUNT_SWITCH.md`, that URL
has changed before on this project — every stored Slack token would become
undecryptable the instant it changes again. Set the key explicitly.

## Going public — deployment checklist

Slack's OAuth redirect must be a URL Slack's servers can actually reach —
`localhost` only exists on your own machine. A judge cannot complete the
install flow until the backend is hosted somewhere with a real HTTPS URL.
This is not Slack-specific busywork: the hackathon submission already
requires a functional public demo URL regardless of Slack (see the
README's "not yet published" note and `docs/HOSTING.md`), so this checklist
rides along with work that has to happen anyway.

Slack allows **multiple** registered redirect URLs on one app — register
the production one now, alongside localhost, so this flip is a pure
env-var change with zero Slack-app edits later:

- [ ] Backend deployed with a real HTTPS URL (prerequisite — see
      `docs/HOSTING.md`)
- [ ] Production redirect URL added to the Slack app's OAuth config,
      **in addition to** the localhost one (do this now, not at flip time —
      costs two minutes, removes a dependency later)
- [ ] `SLACK_REDIRECT_URI` → `https://<api-domain>/api/slack/oauth/callback`
- [ ] `SLACK_INSTALL_SUCCESS_REDIRECT` /
      `SLACK_INSTALL_ERROR_REDIRECT` → `https://<app-domain>/dashboard/settings?slack=...`
- [ ] `FRONTEND_URL` → `https://<app-domain>` (drives the "Open in
      Migration Oracle" Slack button)
- [ ] `ENVIRONMENT=production` — makes `_get_fernet()` hard-refuse the
      ephemeral-key fallback; this is the behavior you want in production
- [ ] `SLACK_TOKEN_ENCRYPTION_KEY` set to a real, stable Fernet key in the
      production secret store (not regenerated on every deploy — that would
      strand every previously-stored token)
- [ ] **Slack app Distribution enabled** — required for anyone outside your
      own workspace (a judge) to install the app into *their* workspace.
      **Hard-blocked on the HTTPS deploy above**: Slack's dashboard won't
      let you activate Public Distribution without a valid HTTPS OAuth
      redirect URL already registered on the app (confirmed by hand,
      2026-08-03 — attempting it against the `localhost` redirect fails).
      So this cannot be started early/in parallel the way the rest of this
      checklist can; it is strictly the last step, after the backend is
      live and the production redirect URL from two items up is already
      registered. Also has its own separate Slack checklist beyond the URL
      requirement (app icon, short description, etc.) — budget time for
      both once unblocked.
- [ ] One real end-to-end OAuth round trip from a browser that has never
      touched your machine, confirming the whole flow works from a cold
      start.

**Deadline anchor:** do this before recording the demo video, not before
the Aug 18 submission deadline. If Slack appears in the video, it should be
the deployed version — the video is what judges actually watch.

## Known limitations

- **No channel picker, no per-event opt-out.** Every user gets all four
  event types as a DM. A `slack_installations.channel` column plus a
  settings-page picker would be the natural next step; deliberately not
  built for this pass (see the "Backend + minimal UI" scope decision).
- **Poll-driven delivery, not push.** `shadow_completed` / `shadow_failed`
  fire inside `sync_status`, which only runs when something calls
  `POST /runs/{id}/sync-workflow` — i.e. only while a client is polling.
  If nobody has the run's page open, the terminal notification never
  fires. The fix is firing from the Lambda side (`PersistResultsFunction`)
  instead, which runs unattended — deliberately deferred; see
  `docs/DEFERRED_LAMBDA_WORK.md`.
- **`SLACK_SIGNING_SECRET` is configured but unused.** It verifies *inbound*
  Slack requests (slash commands, Events API, interactivity). This
  integration has none — the "Open in Migration Oracle" button is a plain
  URL button, which needs no interactivity endpoint. Either drop the var or
  treat it as forward-looking for a future slash command.
- **No replay protection on the OAuth state nonce.** A nonce is generated
  and HMAC-signed but never persisted or checked for reuse. Low severity
  given the HMAC signature and Slack's own single-use authorization codes,
  but worth knowing it's a stated, not enforced, control.
