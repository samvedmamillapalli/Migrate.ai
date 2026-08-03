# TODO

Scratch space — each feature overwrites this file. The durable record lives
in `docs/`.

## Slack notifications — done, superseded

The build checklists that lived here and in
`backend/TODO-slack-notifications.md` are complete and have been removed.
Two of their stated decisions were later reversed, so don't resurrect them
from git history as a spec:

- Channel sourcing is **not** a global `SLACK_DEFAULT_CHANNEL` passed at
  each call site. Notifications DM the user who completed the OAuth install
  (`slack_installations.authed_user_id`); the env var is a last-resort
  fallback only. The original approach would have failed silently with
  `not_in_channel` under `chat:write`-only scope.
- Lifecycle wiring is **done** — all four integration points, not deferred.

Current state, live evidence, known limitations, and the local→deployed
checklist: **[`docs/SLACK_INTEGRATION.md`](docs/SLACK_INTEGRATION.md)**.

Work that only takes effect after a `sam build` + `sam deploy`:
**[`docs/DEFERRED_LAMBDA_WORK.md`](docs/DEFERRED_LAMBDA_WORK.md)**.
