"""Shared UTC clock helpers.

Persisted rows already contain each of these formats, and SQLite compares the stored strings lexicographically, so the helpers are deliberately separate and must keep returning exactly what the code they replaced returned. Do not merge them into one function.
"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def utc_now_naive() -> datetime:
    """UTC datetime without tzinfo, equal to the deprecated naive utcnow call and to SQLite CURRENT_TIMESTAMP values."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_now_iso() -> str:
    """Aware ISO 8601 string with microseconds and a +00:00 offset."""
    return datetime.now(timezone.utc).isoformat()


def utc_now_iso_seconds() -> str:
    """Aware ISO 8601 string truncated to whole seconds, with a +00:00 offset."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_now_naive_iso() -> str:
    """Naive ISO 8601 string with microseconds and no offset, equal to the old naive utcnow call followed by isoformat."""
    return utc_now_naive().isoformat()


def utc_now_naive_iso_z() -> str:
    """Naive ISO 8601 string with microseconds and a literal ``Z`` suffix, as sent to the Swift client."""
    return utc_now_naive().isoformat() + "Z"
