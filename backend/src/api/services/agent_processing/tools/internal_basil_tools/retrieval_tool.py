"""Agent tool for all local historical retrieval operations."""

from __future__ import annotations

import json
from typing import Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, model_validator

from api.services.retrieval.contracts import (
    RetrievalAggregateRequest,
    RetrievalBrowseRequest,
    RetrievalDetailRequest,
    RetrievalSearchRequest,
)
from api.services.retrieval.detail_shaping import DEFAULT_TRANSCRIPT_LIMIT, MAX_TRANSCRIPT_LIMIT
from api.services.retrieval.factory import get_unified_retrieval_service

from .unified_history_tool import refresh_memory_stream

_DESCRIPTION = (
    "Discover and query Basil's local record types. Call action='catalog' when "
    "source selection depends on newly discovered input; then use browse, search, "
    "aggregate, or detail on the selected source kinds. browse returns newest-first "
    "pages of at most 500 events, trimmed further to fit the tool output budget. "
    "view='compact' (the default) returns each event's title, one bounded summary, "
    "outcome, and source_kind/source_id back-reference; view='full' adds the "
    "narrative, raw summary, and payload. When next_cursor is not null, call browse "
    "again with the same filters and cursor=next_cursor for the next older page; "
    "total_in_range counts every matching event. For reviews spanning several days, "
    "call aggregate with group_by='day' first, then browse one day at a time. "
    "Date-only start_time and end_time values such as '2026-07-27' mean local "
    "midnight at the start of that day, so one whole day is start_time='2026-07-27' "
    "with end_time='2026-07-28'. Day buckets are local calendar days. "
    "detail on a meeting returns metadata, an analysis_catalog of every analysis, one "
    "analysis (the latest unless analysis_index is set), and one page of the transcript. "
    "To read analyses without the transcript, pass sections=['analyses']. To read the "
    "transcript, pass sections=['transcript'] and follow transcript_range.next_offset "
    "with transcript_offset until next_offset is null. To read or file a whole call, use "
    "the transcript_markdown_path that detail on a meeting returns: it is a Markdown "
    "file of the full interleaved transcript in the same layout as the analysis "
    "window's Export (one [timestamp] Label header per turn, the lines indented under "
    "it), kept current with the recordings, and you can read it with the file tools or "
    "copy it as is instead of rebuilding the layout from pages. Its Microphone and "
    "System Audio labels name the recording track, not the person, and Basil does not "
    "identify individual voices. Records appear in search, browse, and aggregate a few "
    "minutes after they finish: when the user refers to a meeting, task, or dictation "
    "that just finished and it is missing, repeat the call with refresh_first=true "
    "instead of concluding it was not recorded. Recorded meetings are also stored one "
    "folder per recording under ~/.basil/meetings/ if the refresh still does not "
    "surface one."
)


class RetrievalToolInput(BaseModel):
    action: Literal["catalog", "search", "browse", "aggregate", "detail"] = "search"
    query: Optional[str] = None
    mode: Literal["exact", "semantic", "hybrid"] = "hybrid"
    source_kinds: Optional[list[str]] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    outcome: Optional[str] = None
    group_by: Optional[Literal["source_kind", "day", "outcome"]] = None
    source_kind: Optional[str] = None
    source_id: Optional[str] = None
    limit: int = Field(
        default=20,
        ge=1,
        le=1000,
        description="Maximum results. search returns at most 50; one browse page holds at most 500 events.",
    )
    cursor: Optional[str] = Field(
        default=None,
        description="next_cursor from the previous browse page. Keep every other filter unchanged.",
    )
    view: Literal["compact", "full"] = Field(
        default="compact",
        description="browse event detail: compact (default) or full.",
    )
    sections: Optional[list[Literal["metadata", "analyses", "transcript"]]] = Field(
        default=None,
        description=(
            "detail on a meeting only: which parts to return. Default is all three: metadata, "
            "one analysis, and the first page of the transcript."
        ),
    )
    transcript_offset: int = Field(
        default=0, ge=0,
        description="detail on a meeting: character offset into the transcript; use transcript_range.next_offset from the previous page.",
    )
    transcript_limit: int = Field(
        default=DEFAULT_TRANSCRIPT_LIMIT, ge=1, le=MAX_TRANSCRIPT_LIMIT,
        description="detail on a meeting: maximum transcript characters per page.",
    )
    analysis_index: int = Field(
        default=-1,
        description="detail on a meeting: which analysis to return, by index from analysis_catalog; -1 is the latest.",
    )
    refresh_first: bool = Field(
        default=False,
        description=(
            "search, browse, and aggregate only: collect any records that have not been indexed yet before running. Set true when the user refers to something that just finished (a meeting that ended, a task that completed) and it is missing from the results. Costs no model tokens, takes a few seconds, and is skipped if it already ran in the last 30 seconds. The response reports what happened under memory_refresh."
        ),
    )

    @model_validator(mode="after")
    def validate_action(self):
        if self.action == "search" and not (self.query or "").strip():
            raise ValueError("query is required for action='search'")
        if self.action == "aggregate" and self.group_by is None:
            raise ValueError("group_by is required for action='aggregate'")
        if self.action == "detail" and not (self.source_kind and self.source_id):
            raise ValueError("source_kind and source_id are required for action='detail'")
        if self.cursor and self.action != "browse":
            raise ValueError("cursor is only valid for action='browse'")
        return self


async def _retrieve_basil_history(max_output_chars: Optional[int] = None, **kwargs) -> str:
    args = RetrievalToolInput(**kwargs)
    memory_refresh = None
    if args.refresh_first and args.action in ("search", "browse", "aggregate"):
        memory_refresh = await refresh_memory_stream()
    service = get_unified_retrieval_service()
    if args.action == "catalog":
        result = service.catalog()
    elif args.action == "search":
        result = service.search(RetrievalSearchRequest(
            query=args.query or "", source_kinds=args.source_kinds, start=args.start_time,
            end=args.end_time, mode=args.mode, limit=args.limit,
        ))
    elif args.action == "browse":
        result = service.browse(RetrievalBrowseRequest(
            source_kinds=args.source_kinds, start=args.start_time, end=args.end_time,
            outcome=args.outcome, limit=args.limit, cursor=args.cursor,
            view=args.view, max_output_chars=max_output_chars,
        ))
    elif args.action == "aggregate":
        result = service.aggregate(RetrievalAggregateRequest(
            group_by=args.group_by, source_kinds=args.source_kinds, start=args.start_time,
            end=args.end_time, outcome=args.outcome,
        ))
    else:
        result = service.detail(RetrievalDetailRequest(
            source_kind=args.source_kind or "", source_id=args.source_id or "",
            sections=tuple(args.sections) if args.sections else None,
            transcript_offset=args.transcript_offset, transcript_limit=args.transcript_limit,
            analysis_index=args.analysis_index,
        ))
    if memory_refresh is not None and isinstance(result, dict):
        result["memory_refresh"] = memory_refresh
    return json.dumps(result, ensure_ascii=False, default=str)


def create_retrieval_tool(profile=None, max_output_chars: Optional[int] = None) -> StructuredTool:
    async def _invoke(**kwargs) -> str:
        return await _retrieve_basil_history(max_output_chars=max_output_chars, **kwargs)

    return StructuredTool.from_function(
        func=_invoke,
        coroutine=_invoke,
        name="retrieve_basil_history",
        description=_DESCRIPTION,
        args_schema=RetrievalToolInput,
    )
