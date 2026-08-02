"""Shared helpers for Slack notifications — keep formatting rules in one place."""

from __future__ import annotations

_MIGRATION_NAME_MAX_CHARS = 80
_FALLBACK_NAME = "Untitled migration"


def derive_migration_name(migration_sql: str | None) -> str:
    """Return a short human-readable label for a migration run.

    The ``MigrationRun`` table stores raw SQL, not a display name.  Use the
    first non-empty line as the label so Slack notifications (and any future
    callers) can show something meaningful without schema changes.

    Returns ``"Untitled migration"`` when the SQL is empty/blank.
    """
    if not migration_sql:
        return _FALLBACK_NAME

    for raw_line in migration_sql.splitlines():
        line = raw_line.strip()
        if line:
            # Keep one long statement readable; anything past 80 chars is noise
            # in a notification header.
            if len(line) > _MIGRATION_NAME_MAX_CHARS:
                return line[:_MIGRATION_NAME_MAX_CHARS].rstrip() + "\u2026"
            return line

    return _FALLBACK_NAME


__all__ = ["derive_migration_name"]
