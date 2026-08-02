# Slack Notifications Lifecycle Wiring — Task Checklist

## Plan
Wire the existing `SlackNotificationService` into 4 lifecycle integration points.

### Confirmed Decisions
1. **Channel sourcing**: `SLACK_DEFAULT_CHANNEL` config (env var, default `"general"`), passed at each call site. No DB schema change, no SlackNotificationService modification.
2. **/api/slack/install**: Keep current JSON response (`authorize_url`). Frontend handles navigation.
3. **shadow_failed scope**: Only for real shadow workflow failures — `sync_status` non-success terminal + `abort_for_run` operator abort. **Do NOT** fire for prediction pipeline failures in `_fail_run`.

## Steps
- [ ] 1. `backend/app/config.py` — add `slack_default_channel` setting (env `SLACK_DEFAULT_CHANNEL`, default `"general"`)
- [ ] 2. `backend/app/services/slack_helpers.py` — new helper `derive_migration_name(sql)` (first non-empty line, truncated ~80 chars)
- [ ] 3. `backend/app/services/prediction_pipeline_service.py`
    - [ ] Add optional `slack_notifications: SlackNotificationService | None = None` constructor param
    - [ ] **Integration #1 (prediction_ready)**: after `_persist_success` commits, before `_prog("done")` — best-effort `send_prediction_ready`
- [ ] 4. `backend/app/services/workflow_orchestration_service.py`
    - [ ] Add optional `slack_notifications: SlackNotificationService | None = None` constructor param
    - [ ] **Integration #2 (shadow_started)**: in `start_for_run` after commit (NOT on idempotent path)
    - [ ] **Integration #3 (shadow_completed)**: in `sync_status` after commit when `just_became_terminal` + `SUCCEEDED`
    - [ ] **Integration #4 (shadow_failed)**: in `sync_status` after commit when `just_became_terminal` + non-success terminal
    - [ ] **Integration #4 (shadow_failed)**: in `abort_for_run` after commit when status became FAILED
- [ ] 5. `backend/app/dependencies.py` — pass `SlackNotificationSvc` to 4 factories:
    - [ ] `get_prediction_pipeline_service`
    - [ ] `get_workflow_orchestration_service`
    - [ ] `get_approval_service` (inline WorkflowOrchestrationService)
    - [ ] `get_closed_loop_service` (inline WorkflowOrchestrationService)
- [ ] 6. `backend/app/api/errors.py` — register `SlackOAuthError` + `SlackStateError` in `_STATUS_BY_ERROR`

## Follow-up
- [ ] Run `python -m pytest tests/unit -x -q` from `backend/`
- [ ] Verify `ast.parse` compile check on all modified files
- [ ] Verify all 4 integration points fire exactly once with correct data
