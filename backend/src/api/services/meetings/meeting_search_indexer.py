"""Keeps the meeting transcript FTS index in sync with on-disk meetings.

One indexed document per meeting directory id (metadata name/purpose/participants
plus all transcript segment text). Search returns matched member ids; the search
route maps each to its session-grouped representative, so indexing per-member is
sufficient for recall while grouping stays a route concern.

All entry points are best-effort: failures are logged and swallowed so a search
index hiccup never breaks recording stop, post-processing, deletion, or startup.
"""

import logging
from typing import Optional

from api.services.meetings.meeting_recorder import MeetingRecorder
from api.routes.meetings.meeting_grouping import clean_meeting_name, meetings_directory
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.meetings.transcript_search_repository import (
    MeetingSearchDocument,
)

logger = logging.getLogger(__name__)


def _repository():
    # Imported lazily to avoid import cycles at module load (dependencies pulls
    # in many services). The knowledge service is an lru_cache singleton.
    from api.dependencies import get_sqlite_knowledge_service
    return get_sqlite_knowledge_service().meeting_transcript_search_repository


def build_document(meeting_id: str) -> Optional[MeetingSearchDocument]:
    """Structured searchable content for one meeting, or None if unindexable."""
    metadata = MeetingRecorder.load_metadata(meeting_id)
    transcript = MeetingRecorder.load_transcript(meeting_id)

    name = ""
    purpose = ""
    participants = ""
    if metadata is not None:
        name = clean_meeting_name(metadata.to_dict())
        purpose = metadata.purpose or ""
        participants = " ".join(participant for participant in (metadata.participants or []) if participant)

    transcript_parts = []
    if transcript:
        for segment in transcript.get("segments", []):
            text = (segment.get("text") or "").strip()
            if text:
                transcript_parts.append(text)

    document = MeetingSearchDocument(
        name=name,
        purpose=purpose,
        participants=participants,
        transcript="\n".join(transcript_parts),
    )
    if document.is_empty:
        return None
    return document


def reindex(meeting_id: str) -> None:
    """Rebuild (or drop) the indexed document for one meeting id."""
    try:
        document = build_document(meeting_id)
        repository = _repository()
        if document:
            repository.reindex_meeting(meeting_id, document)
        else:
            # Nothing indexable (e.g. empty/missing transcript) -> ensure no stale row.
            repository.remove_meeting(meeting_id)
    except Exception as e:
        logger.warning(f"Failed to reindex meeting {meeting_id} for search: {e}")


def remove(meeting_id: str) -> None:
    """Drop a meeting id from the search index (used on delete)."""
    try:
        _repository().remove_meeting(meeting_id)
    except Exception as e:
        logger.warning(f"Failed to remove meeting {meeting_id} from search index: {e}")


def backfill_all() -> None:
    """Rebuild the whole index from disk (one-time startup reconciliation)."""
    try:
        repository = _repository()
        repository.clear_all()
        meetings_dir = meetings_directory()
        if not meetings_dir.exists():
            return
        count = 0
        for meeting_dir in meetings_dir.iterdir():
            if not meeting_dir.is_dir():
                continue
            document = build_document(meeting_dir.name)
            if document:
                repository.reindex_meeting(meeting_dir.name, document)
                count += 1
        logger.info(f"Backfilled meeting transcript search index: {count} meetings")
    except Exception as e:
        logger.warning(f"Failed to backfill meeting transcript search index: {e}")
