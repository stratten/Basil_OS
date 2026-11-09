"""Keep a query_activities result inside the tool output budget.

Each activity carries its full OCR text, so a normal request (100 records) can be hundreds of thousands of characters. Records are kept in the order the caller asked for until the budget is used, the first record is always kept so one oversized record can still be reached, and the rest are named in a hint telling the agent which time window to ask for next.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_ACTIVITY_OUTPUT_CHARS = 60_000
MIN_ACTIVITY_OUTPUT_CHARS = 4_000
ENVELOPE_RESERVE_CHARS = 2_000
# The result is rendered with indent=2 and each record sits two levels deep, so every line of a record gains four spaces and each record is followed by a comma and a newline.
_RECORD_LINE_INDENT_CHARS = 4
_RECORD_SEPARATOR_CHARS = 2


def resolve_activity_budget(max_output_chars: Optional[int]) -> int:
    if max_output_chars is None:
        return DEFAULT_ACTIVITY_OUTPUT_CHARS
    return max(MIN_ACTIVITY_OUTPUT_CHARS, int(max_output_chars))


def _rendered_size(activity: Dict[str, Any]) -> int:
    text = json.dumps(activity, ensure_ascii=False, indent=2)
    return len(text) + _RECORD_LINE_INDENT_CHARS * (text.count("\n") + 1) + _RECORD_SEPARATOR_CHARS


def fit_activities_to_budget(
    activities: List[Dict[str, Any]],
    max_output_chars: Optional[int],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (kept, omitted); kept is the longest leading run that fits, and always has the first record."""
    budget = max(0, resolve_activity_budget(max_output_chars) - ENVELOPE_RESERVE_CHARS)
    kept: List[Dict[str, Any]] = []
    used = 0
    for index, activity in enumerate(activities):
        size = _rendered_size(activity)
        if kept and used + size > budget:
            return kept, activities[index:]
        kept.append(activity)
        used += size
    return kept, []


def _boundary_for_next_call(timestamp: Any, sort_order: str) -> Optional[str]:
    """A time the query's own parser reads back as the same moment.

    Stored timestamps have no offset and are local time, but the tool reads an offset-less value as UTC, so the local offset is attached here. The tool compares times as text against the stored values, so a start boundary is moved back one microsecond to keep the first omitted record inside it.
    """
    if not isinstance(timestamp, str) or not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    local = parsed.astimezone()
    if sort_order == "oldest":
        local = local - timedelta(microseconds=1)
    return local.isoformat()


def continuation_fields(
    omitted: List[Dict[str, Any]],
    sort_order: str,
    max_output_chars: Optional[int],
) -> Dict[str, Any]:
    """Fields that tell the agent what was left out and how to ask for it."""
    budget = resolve_activity_budget(max_output_chars)
    boundary_name = "start_time" if sort_order == "oldest" else "end_time"
    boundary = _boundary_for_next_call(omitted[0].get("timestamp") if omitted else None, sort_order)
    fields: Dict[str, Any] = {
        "budget_trimmed": True,
        "omitted_count": len(omitted),
    }
    if boundary:
        fields["next_window"] = {boundary_name: boundary}
        how = f"call query_activities again with the same filters and {boundary_name}='{boundary}', or narrow the time range"
    else:
        how = "narrow the time range or add app_name_filter or window_title_search"
    noun = "activity was" if len(omitted) == 1 else "activities were"
    fields["message"] = (
        f"{len(omitted)} more matching {noun} left out so the result stays within {budget:,} characters; "
        f"to see them, {how}."
    )
    return fields
