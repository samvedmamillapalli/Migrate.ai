# Claude test account (UI testing only)

Created for automated/agent-driven UI testing via Playwright MCP against the
local dev stack. Not a real user — do not use for demo data you care about
keeping separate from test noise.

- Email: `claude-agent+clerk_test@migration-oracle.dev`
- Password: `ClaudeTestPass!2026x`
- Auth provider: Clerk (dev/keyless instance)

Note: the `+clerk_test@` email pattern is Clerk's built-in test-address
convention — sign-in/sign-up always accepts verification code `424242` for
any email containing `+clerk_test`, no real inbox needed. Works on this dev
instance for repeatable, non-interactive sign-in.

Sign in at `/login` with the email + password above.
