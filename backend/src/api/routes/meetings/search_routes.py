"""Meeting transcript search route.

`GET /meetings/search` resolves the FTS index to matching meeting ids, then maps
those ids onto the same session-grouped representatives the sidebar list uses, so
a hit on any member (mic, system-audio, or a resumed part) surfaces the single
grouped meeting. Registered ahead of `/{meeting_id}` so it is not shadowed.
"""

import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_sqlite_knowledge_service
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.meetings.transcript_search_repository import (
    parse_search_terms,
)

from .meeting_grouping import group_meetings, load_all_raw_meetings
from .models import MeetingResponse, MeetingSearchFilters


logger = logging.getLogger(__name__)
router = APIRouter()


def _matches_source(group: MeetingResponse, raw_value: str, mode: str) -> bool:
    terms = parse_search_terms(raw_value)
    if not terms:
        return True
    sources = [group.audio_source or ""]
    sources.extend(member.get("source") or "" for member in group.members or [])
    matches = [
        any(term.value.casefold() in source.casefold() for source in sources)
        for term in terms
    ]
    return any(matches) if mode == "or" else all(matches)


def _matches_scalar_filters(group: MeetingResponse, filters: MeetingSearchFilters) -> bool:
    if filters.start_date or filters.end_date:
        try:
            meeting_date = datetime.fromisoformat(group.start_time.replace("Z", "+00:00")).date()
        except ValueError:
            return False
        if filters.start_date and meeting_date < filters.start_date:
            return False
        if filters.end_date and meeting_date > filters.end_date:
            return False
    if not _matches_source(group, filters.source, filters.source_mode):
        return False
    if filters.processing == "complete" and not group.is_post_processed:
        return False
    if filters.processing == "incomplete" and group.is_post_processed:
        return False
    has_analysis = bool(group.analysis_summary and group.analysis_summary.count > 0)
    if filters.analysis == "has_analysis" and not has_analysis:
        return False
    if filters.analysis == "no_analysis" and has_analysis:
        return False
    return True


@router.get("/search")
async def search_meetings(
    filters: MeetingSearchFilters = Depends(),
    limit: int = 50,
    offset: int = 0,
) -> List[MeetingResponse]:
    """Search grouped meetings with composable text and metadata constraints."""
    if filters.has_invalid_date_range:
        # Raised before the try/except below so it surfaces as the intended 422
        # rather than being re-wrapped as a 500 by the generic exception handler.
        raise HTTPException(status_code=422, detail="start_date must not be after end_date")

    try:
        groups = group_meetings(load_all_raw_meetings())
        if not filters.is_active:
            return groups[offset:offset + limit]

        matched_ids = None
        if filters.has_text_constraints:
            repository = get_sqlite_knowledge_service().meeting_transcript_search_repository
            matched_ids = set(repository.search_meeting_ids(
                query=filters.query,
                query_mode=filters.query_mode,
                name=filters.name,
                name_mode=filters.name_mode,
                purpose=filters.purpose,
                purpose_mode=filters.purpose_mode,
                participants=filters.participants,
                participants_mode=filters.participants_mode,
                transcript=filters.transcript,
                transcript_mode=filters.transcript_mode,
            ))
            if not matched_ids:
                return []

        filtered: List[MeetingResponse] = []
        for group in groups:
            candidate_ids = {group.id}
            if group.members:
                candidate_ids.update(m.get("id") for m in group.members if m.get("id"))
            if (matched_ids is None or candidate_ids & matched_ids) and _matches_scalar_filters(group, filters):
                filtered.append(group)

        return filtered[offset:offset + limit]

    except Exception as e:
        logger.error(f"Error searching meetings (filters={filters!r}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
