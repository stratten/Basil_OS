"""Timestamp, text, and payload normalization for the zettel stream.

Every adapter funnels through here so the stream has exactly one definition
of "when did this happen" and one enforcement point for bounded text.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

TITLE_MAX_CHARS = 200
SUMMARY_MAX_CHARS = 500
PAYLOAD_MAX_CHARS = 4000

_SQLITE_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def to_utc_iso(value: Any) -> Optional[str]:
    """Normalize any SQLite timestamp value to a UTC ISO-8601 string.

    Naive inputs are treated as UTC: every naive timestamp in this database
    originates from SQLite CURRENT_TIMESTAMP, which is UTC. Comparing a naive
    local string against a UTC one is the single most likely source of silent
    ordering corruption in this subsystem, so it is resolved once, here.
    """
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for date_format in _SQLITE_FORMATS:
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue
    return None


def utc_now_iso() -> str:
    """Current time as a UTC ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def truncate(text: Optional[str], limit: int) -> Optional[str]:
    """Collapse whitespace and cap length, returning None for empty input."""
    if text is None:
        return None
    collapsed = " ".join(str(text).split())
    if not collapsed:
        return None
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: max(limit - 1, 1)].rstrip() + "\u2026"


def bounded_payload(payload: Optional[Dict[str, Any]]) -> str:
    """Serialize a payload, replacing it with a stub if it exceeds the cap."""
    if not payload:
        return "{}"
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    if len(encoded) <= PAYLOAD_MAX_CHARS:
        return encoded
    return json.dumps(
        {"_truncated": True, "keys": sorted(str(key) for key in payload)[:20]},
        ensure_ascii=False,
        sort_keys=True,
    )


def content_digest(*parts: Any) -> str:
    """Stable digest of the projected fields, for revision-only-on-change."""
    joined = "\u0000".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]
