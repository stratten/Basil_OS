"""Agent tool for querying the unified event stream across all subsystems."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile

logger = logging.getLogger(__name__)

_SOURCE_KINDS = (
    "agent_task", "transcription", "assistant_output", "scheduled_run",
    "conversation", "screen_block", "meeting",
)

_DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")


class UnifiedHistoryInput(BaseModel):
    """Input schema for the unified history query tool."""
    start_time: Optional[str] = Field(
        default=None,
        description=(
            "Start of range. ISO timestamp, or a relative token: 'today', "
            "'yesterday', 'this_week', 'last_week', 'this_month', 'last_month'. "
            "Defaults to 24 hours ago."
        ),
    )
    end_time: Optional[str] = Field(
        default=None,
        description="End of range. ISO timestamp or 'now'. Defaults to now.",
    )
    source_kinds: Optional[List[str]] = Field(
        default=None,
        description=(
            "Restrict to these kinds of activity: agent_task, transcription, "
            "assistant_output, scheduled_run, conversation, screen_block, "
            "meeting. Omit for everything."
        ),
    )
    outcome: Optional[Literal["succeeded", "failed", "canceled", "skipped"]] = Field(
        default=None, description="Only events with this outcome."
    )
    group_by: Optional[Literal["source_kind", "day", "outcome"]] = Field(
        default=None,
        description=(
            "Return counts grouped by this dimension alongside the events. "
            "Use for 'what did I do yesterday' style aggregation."
        ),
    )
    limit: int = Field(
        default=200,
        description="Maximum events per page (max 500); the page is trimmed further to fit the tool output budget.",
    )
    cursor: Optional[str] = Field(
        default=None,
        description="next_cursor from the previous page. Keep every other filter unchanged.",
    )
    view: Literal["compact", "full"] = Field(
        default="compact",
        description="compact (default) returns title, one bounded summary, outcome, and back-reference; full adds narrative, raw_summary, and payload.",
    )


def _relative(token: str) -> Optional[datetime]:
    """Resolve a relative token against the user's local day.

    Local, not UTC, to match activity_query_tool._parse_relative_time. A UTC
    day boundary would shift "yesterday" by the offset, so west of Greenwich
    the window would start in the previous evening.
    """
    now = datetime.now().astimezone()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    table = {
        "now": now,
        "today": midnight,
        "yesterday": midnight - timedelta(days=1),
        "this_week": midnight - timedelta(days=now.weekday()),
        "last_week": midnight - timedelta(days=now.weekday() + 7),
        "this_month": midnight.replace(day=1),
        "last_month": (midnight.replace(day=1) - timedelta(days=1)).replace(day=1),
    }
    return table.get(token.lower())


def _parse_time(value: Optional[str], default: datetime) -> str:
    """Normalize to a UTC ISO string; stored occurred_at is compared as text.

    A date-only value names the user's local calendar day, so it resolves to local midnight like the relative tokens; a timestamp without an offset is still read as UTC.
    """
    if not value:
        return default.astimezone(timezone.utc).isoformat()
    relative = _relative(value)
    if relative is not None:
        return relative.astimezone(timezone.utc).isoformat()
    text = value.strip()
    try:
        if _DATE_ONLY.fullmatch(text):
            return datetime.fromisoformat(text).astimezone().astimezone(timezone.utc).isoformat()
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return default.isoformat()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


async def _query_unified_history_impl(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    source_kinds: Optional[List[str]] = None,
    outcome: Optional[str] = None,
    group_by: Optional[str] = None,
    limit: int = 200,
    cursor: Optional[str] = None,
    view: str = "compact",
    max_output_chars: Optional[int] = None,
) -> str:
    try:
        from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
            get_sync_connection,
        )
        from api.dependencies import get_sqlite_knowledge_service
        from api.services.retrieval.browse_paging import (
            build_page,
            clamp_page_limit,
            decode_cursor,
            resolve_output_budget,
        )
        from api.services.zettel import store

        now = datetime.now(timezone.utc)
        start = _parse_time(start_time, now - timedelta(days=1))
        end = _parse_time(end_time, now)
        kinds = [kind for kind in (source_kinds or []) if kind in _SOURCE_KINDS] or None
        page_limit = clamp_page_limit(limit)
        try:
            before = decode_cursor(cursor) if cursor else None
        except ValueError as exc:
            return json.dumps({"success": False, "error": str(exc), "events": []}, ensure_ascii=False)

        with get_sync_connection(get_sqlite_knowledge_service().db_path) as conn:
            fetched = store.query_entries(
                conn, start=start, end=end, source_kinds=kinds,
                outcome=outcome, limit=page_limit + 1, before=before,
            )
            total_in_range = sum(
                store.count_entries_by(
                    conn, dimension="source_kind", start=start, end=end,
                    source_kinds=kinds, outcome=outcome,
                ).values()
            )
            grouped = (
                store.count_entries_by(
                    conn, dimension=group_by, start=start, end=end,
                    source_kinds=kinds, outcome=outcome,
                )
                if group_by
                else None
            )

        page = build_page(
            fetched,
            page_limit=page_limit,
            max_output_chars=resolve_output_budget(max_output_chars),
            view="full" if view == "full" else "compact",
        )
        response: Dict[str, Any] = {
            "success": True,
            "count": len(page["events"]),
            "range": {"start": start, "end": end},
            "events": page["events"],
            "total_in_range": total_in_range,
            "next_cursor": page["next_cursor"],
            "truncated": page["next_cursor"] is not None,
        }
        if grouped is not None:
            # Counted in SQL over the whole range, so these stay accurate even
            # when the event list below was cut off by the limit.
            response["grouped_counts"] = grouped
            response["grouped_counts_cover"] = "entire range, not just returned events"
        return json.dumps(response, ensure_ascii=False, default=str)
    except Exception as exc:
        logger.error(f"Error querying unified history: {exc}", exc_info=True)
        return json.dumps({"success": False, "error": str(exc), "events": []}, ensure_ascii=False)


SLIM_DESCRIPTION = (
    "Query the unified record of everything the user did in Basil: agent task "
    "runs, transcriptions, assistant outputs, scheduled task runs, "
    "conversations, coalesced blocks of screen activity, and recorded "
    "meetings. This is the right tool for 'what did I do yesterday', 'what "
    "failed this week', and any question spanning more than one subsystem. "
    "Each event carries a title, a short summary, an outcome, and a "
    "back-reference (source_kind + source_id) for fetching full detail from "
    "the owning service (for meetings: the full transcript and every valid "
    "associated analysis). Use group_by='day' or 'source_kind' to aggregate. "
    "Results are newest-first pages; when next_cursor is not null, call again "
    "with the same filters and cursor=next_cursor, and compare count with "
    "total_in_range before claiming full coverage. Date-only values mean local "
    "midnight. For screen-only questions about OCR'd text, prefer query_activities."
)

_FULL_DESCRIPTION = """Query the unified event stream spanning every Basil subsystem.

**WHEN TO USE:**
This is the cross-cutting history tool. Use it whenever the question spans more
than one kind of activity, or when you do not know in advance which subsystem
holds the answer.

- USE: "What did I do yesterday?" -> everything, in one chronological list.
- USE: "What failed this week?" -> filter outcome='failed' across all sources.
- USE: "How did I spend Tuesday?" -> group_by='source_kind' over that day.
- USE: "What meetings did I have this week?" -> source_kinds=['meeting']; each
  event's summary is a quick note, and the owning service (retrieve_basil_history
  action='detail', source_kind='meeting') returns the full transcript and every
  valid associated analysis when you need more than the quick note.
- PREFER query_activities: "What was the exact text on screen in Chrome?" ->
  the stream stores a bounded block summary, not full OCR text.

**WHAT EACH EVENT CONTAINS:**
- `source_kind` and `source_id`: back-reference to the owning record.
- `event_type`, `occurred_at`, `ended_at`: what and when.
- `title` (<=200 chars): bounded display text.
- `summary`: the synthesized narrative when one exists, else the raw card text.
- `narrative` and `narrative_state`: the model-written narrative and whether it
  is 'final', still 'pending', or 'failed'. `raw_summary` keeps the card text.
- `is_open` / `open_note`: the model judged the record still unfinished.
- `outcome`: succeeded, failed, canceled, skipped, or null.
- `payload`: bounded per-kind detail (durations, counts, model names).

Bodies are deliberately not stored. When an event matters, use its
source_kind/source_id to fetch full detail from the owning service.

**AGGREGATION:**
group_by='day' | 'source_kind' | 'outcome' returns `grouped_counts` alongside
the events, so you can answer summary questions without post-processing. Those
counts are computed over the entire requested range, so they remain correct
even when `truncated` is true and the event list itself was cut off by `limit`.

**PAGING:**
Events arrive newest-first, at most 500 per page and fewer when the page would exceed the tool output budget. `total_in_range` counts every matching event. When `next_cursor` is not null, call again with the same filters and `cursor=next_cursor` for the next older page. For a multi-day review, aggregate with group_by='day' first, then page through one day at a time. `view='compact'` (default) omits narrative, raw_summary, and payload; request `view='full'` only for the few events you need in depth.

Relative tokens resolve against the user's local day, so 'yesterday' is their
yesterday rather than a UTC calendar day. Date-only values such as '2026-07-27'
also mean local midnight at the start of that day.
"""


def create_unified_history_tool(profile=None, max_output_chars: Optional[int] = None) -> StructuredTool:
    """Factory for the ``query_unified_history`` tool."""
    tool_description = select_description_for_profile(
        profile, _FULL_DESCRIPTION, SLIM_DESCRIPTION
    )

    async def _invoke(**kwargs) -> str:
        return await _query_unified_history_impl(**kwargs, max_output_chars=max_output_chars)

    return StructuredTool.from_function(
        func=_invoke,
        name="query_unified_history",
        description=tool_description,
        args_schema=UnifiedHistoryInput,
        coroutine=_invoke,
    )
