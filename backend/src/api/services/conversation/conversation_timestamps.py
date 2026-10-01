"""UTC normalization for conversation timestamps exposed to clients."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Union


def utc_now_naive() -> datetime:
    """Return the current UTC time without tzinfo, matching SQLite CURRENT_TIMESTAMP values."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_iso_timestamp(value: Union[str, datetime, None]) -> Optional[str]:
    """Serialize a stored conversation timestamp as an explicit UTC ISO 8601 string ending in Z.

    Naive values are UTC because SQLite CURRENT_TIMESTAMP writes UTC without an offset. Unparseable strings are returned unchanged so a malformed legacy value never fails a list request.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = value.strip()
        if not text:
            return value
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")
