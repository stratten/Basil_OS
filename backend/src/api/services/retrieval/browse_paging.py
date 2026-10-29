"""Keyset paging, compact projection, and output budgeting for history browsing.

Browse results are ordered newest-first by (occurred_at, source_kind, source_id). A cursor encodes the key of the last event a page returned, so the next page asks for keys strictly below it and never repeats or skips an event that shares a timestamp with its neighbors.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Optional

BrowseView = Literal["compact", "full"]
EventKey = tuple[str, str, str]

MAX_BROWSE_PAGE_EVENTS = 500
DEFAULT_BROWSE_OUTPUT_CHARS = 80_000
MIN_BROWSE_OUTPUT_CHARS = 4_000
BROWSE_ENVELOPE_RESERVE_CHARS = 2_000
COMPACT_SUMMARY_CHARS = 400

_COMPACT_FIELDS = (
    "source_kind",
    "source_id",
    "event_type",
    "occurred_at",
    "title",
    "outcome",
    "is_open",
    "representation",
)
_LOCALIZED_TIME_FIELDS = ("occurred_at", "ended_at")
_INVALID_CURSOR_MESSAGE = (
    "cursor is not a next_cursor value returned by a previous page; "
    "omit cursor to start from the newest event"
)


def event_key(event: dict[str, Any]) -> EventKey:
    return (
        str(event.get("occurred_at") or ""),
        str(event.get("source_kind") or ""),
        str(event.get("source_id") or ""),
    )


def sort_newest_first(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(events, key=event_key, reverse=True)


def encode_cursor(event: dict[str, Any]) -> str:
    raw = json.dumps(list(event_key(event)), ensure_ascii=False, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> EventKey:
    text = (cursor or "").strip()
    if not text:
        raise ValueError(_INVALID_CURSOR_MESSAGE)
    padded = text + "=" * (-len(text) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except ValueError as exc:
        raise ValueError(_INVALID_CURSOR_MESSAGE) from exc
    if (
        not isinstance(decoded, list)
        or len(decoded) != 3
        or not all(isinstance(part, str) for part in decoded)
    ):
        raise ValueError(_INVALID_CURSOR_MESSAGE)
    return (decoded[0], decoded[1], decoded[2])


def clamp_page_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_BROWSE_PAGE_EVENTS))


def resolve_output_budget(max_output_chars: Optional[int]) -> int:
    if max_output_chars is None:
        return DEFAULT_BROWSE_OUTPUT_CHARS
    return max(MIN_BROWSE_OUTPUT_CHARS, int(max_output_chars))


def project_event(event: dict[str, Any], view: BrowseView) -> dict[str, Any]:
    if view == "full":
        return event
    projected = {name: event[name] for name in _COMPACT_FIELDS if name in event}
    summary = event.get("summary")
    if isinstance(summary, str) and summary:
        if len(summary) > COMPACT_SUMMARY_CHARS:
            summary = summary[:COMPACT_SUMMARY_CHARS].rstrip() + "…"
        projected["summary"] = summary
    return projected


def to_local_timestamp(value: Any) -> Any:
    """Render a stored timestamp in the local offset so its date prefix is the local calendar day; offset-less values are UTC."""
    if not isinstance(value, str) or not value:
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().isoformat()


def localize_event_times(event: dict[str, Any]) -> dict[str, Any]:
    localized = dict(event)
    for name in _LOCALIZED_TIME_FIELDS:
        if name in localized:
            localized[name] = to_local_timestamp(localized[name])
    return localized


def build_page(
    candidates: list[dict[str, Any]],
    *,
    page_limit: int,
    max_output_chars: int,
    view: BrowseView,
) -> dict[str, Any]:
    """Fit newest-first candidates into one page.

    ``candidates`` holds up to ``page_limit + 1`` events so the extra row proves another page exists. The first event is always kept so a single oversized event can still be reached. The cursor is encoded from the stored UTC key because keyset comparison is textual; only the returned events carry local-offset times.
    """
    budget = max(0, max_output_chars - BROWSE_ENVELOPE_RESERVE_CHARS)
    events: list[dict[str, Any]] = []
    last_kept: Optional[dict[str, Any]] = None
    used = 0
    budget_trimmed = False
    for event in candidates[:page_limit]:
        projected = localize_event_times(project_event(event, view))
        size = len(json.dumps(projected, ensure_ascii=False, default=str)) + 2
        if events and used + size > budget:
            budget_trimmed = True
            break
        events.append(projected)
        last_kept = event
        used += size
    has_more = budget_trimmed or len(candidates) > len(events)
    return {
        "events": events,
        "next_cursor": encode_cursor(last_kept) if has_more and last_kept is not None else None,
        "budget_trimmed": budget_trimmed,
    }
