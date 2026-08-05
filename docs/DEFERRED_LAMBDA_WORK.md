# Deferred Lambda-side work

Started 2026-08-03. This is a running list of fixes that only take effect
after a `sam build` + `sam deploy` of `infra/sam/` — as opposed to backend
control-plane changes, which only need a local `uvicorn` restart. Per the
project's standing rule against reflexive builds (~25 min per cycle,
real AWS resources), items collect here and get bundled into one deploy
rather than each spending its own cycle. See `docs/cockroach_hookup.md`'s
"Notes for whoever runs this" for the deploy procedure and the
Bash-not-PowerShell requirement.

Add to this list; don't fix items here individually. Clear items only when
they're actually deployed and verified live, not when the code is written.

## Open items

### 1. Changefeed `CANCEL JOB` loses a serialization race

**Where:** `backend/app/shadow/changefeed_watch.py`, `cancel_changefeed()`
(called from `stop_changefeed_safely`, itself called from
`migration_runner.run_migration()` ~2 seconds after the migration
completes).

**What happens:** `CANCEL JOB <id>` can lose a race with CockroachDB's own
internal job-progress writer, which is mid-write to the same job record.
When it does, the exception is caught and logged as
`"Changefeed stop failed (non-fatal; migration already measured)"` — never
fatal, the migration's own measured result is already final by this point,
and any events already flushed via the `1s` resolved-interval checkpoint
are still captured. The shadow cluster gets torn down immediately after
regardless, which reaps the job as a side effect even when the explicit
cancel failed.

**Fix:** a single bounded retry (1-2 attempts, short backoff) around the
`CANCEL JOB` statement before giving up and logging. Cosmetic — doesn't
change what's captured — but removes a log line an operator might
otherwise chase.

**Effort:** ~15 min code change. Verify with one real changefeed-bearing
run (an `ADD COLUMN ... DEFAULT` against the demo table, same setup as
`docs/cockroach_hookup.md` §7's verification) and confirm the warning no
longer appears in CloudWatch.

### 2. Slack terminal notifications only fire on poll, not push

**Where:** `backend/app/services/workflow_orchestration_service.py`,
`_notify_terminal()` — called from `sync_status()`, which only runs when
something calls `POST /runs/{id}/sync-workflow`.

**What happens:** `shadow_completed` / `shadow_failed` Slack DMs only send
while a client is actively polling a run (e.g. someone has the run's page
open in the browser). If nobody is watching, the run still completes and
grades normally — Step Functions doesn't need polling to make progress —
but the terminal Slack notification never fires, since nothing ever calls
`sync_status` to observe the transition. `prediction_ready` and
`shadow_started` are unaffected — both fire from code paths a human
request already triggers directly (`predict`, `start-workflow`), not from
polling.

**Fix:** fire the terminal notification from
`backend/app/lambdas/handlers/persist_results.py` instead (or in addition
— same idempotency guard needed either way), since that Lambda runs as
part of the Step Functions workflow itself and doesn't depend on anyone
polling. Requires:
- DB access from `PersistResultsFunction` to read the `slack_installations`
  row for the run's owner (it currently has no need for this table).
- Fernet key access to decrypt the bot token — `SLACK_TOKEN_ENCRYPTION_KEY`
  would need to reach this Lambda's environment, same pattern as the
  Bedrock model IDs already injected via `Globals.Environment` in
  `infra/sam/template.yaml`.
- The existing best-effort/never-raise posture carries over unchanged —
  this is enrichment, same as everything else this Lambda already does
  (grading prose, Titan embeddings).

**Status:** deliberately deferred, not started. Documented here per an
explicit decision on 2026-08-03: keep poll-driven delivery for now, revisit
when the changefeed work above is already forcing a deploy cycle — bundle
rather than spend a separate one. See `docs/SLACK_INTEGRATION.md`'s "Known
limitations" section for the user-facing description of this gap.

**Effort:** ~1-2 hours (Lambda code, IAM policy addition, template changes)
plus one real end-to-end run to confirm a DM arrives with nobody polling.

### 3. Cross-customer automatic promotion hook — code complete, not deployed

**Where:** `backend/app/lambdas/handlers/persist_results.py`,
`_build_grading_pipeline()`.

**What happens:** code now constructs a `CrossCustomerPromotionService` and
passes it into `MemoryWriteService(cross_customer_promotion=...)`, matching
`app/dependencies.py`'s `get_memory_write_service` on the control-plane
side (docs/cross_customer.md §5). Runs graded through the API
(`POST /runs/{id}/grade` or similar control-plane paths) already benefit —
that only needed a `uvicorn` restart. Runs graded through the real Step
Functions workflow (the `PersistResultsFunction` Lambda, i.e. every actual
shadow-verified migration in a deployed environment) will keep silently
skipping automatic promotion (`cross_customer_promotion=None` behavior,
same as before this change) until this Lambda is redeployed — best-effort
by design, so this is a missed opportunity, not a broken run.

**Fix:** already written; needs `sam build` + `sam deploy` to take effect.

**Status:** deliberately not deployed yet, per the project's standing rule
against reflexive build/deploy cycles. Bundle with items #1/#2 above the
next time a deploy is already happening for another reason, or deploy on
request.

**Effort:** no additional code. One `sam build`/`sam deploy` cycle (~25
min), then verify with a real end-to-end run: an owner with
`memory_sharing_preferences.cross_customer_sharing_enabled = true` running
a real shadow-verified migration through the full Step Functions workflow,
confirming a `cross_customer_memories` row appears afterward without the
manual script being invoked.
