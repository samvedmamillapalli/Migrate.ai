# Slack Notification Service — Implementation Steps

## Approved Plan
Inject `SlackOAuthService` via DI (not instantiated inside), explicit keyword args (no dataclass), centralized `_build_message_blocks()`, use `config.frontend_url` with graceful empty handling, completely best-effort (log + return False), no lifecycle wiring.

## Steps
- [x] 1. Add `frontend_url` setting to `backend/app/config.py`
- [x] 2. Create `backend/app/services/slack_notification_service.py`
- [x] 3. Register `SlackNotificationSvc` DI provider in `backend/app/dependencies.py`
- [x] 4. Verify all backend Python files compile (`ast.parse`)
- [x] 5. Run existing unit tests
