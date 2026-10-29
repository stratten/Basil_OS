"""Shape a meeting's retrieval detail so analyses are reachable without the whole transcript."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .contracts import RetrievalDetailRequest

DETAIL_SECTIONS = ("metadata", "analyses", "transcript")
DEFAULT_TRANSCRIPT_LIMIT = 20000
MAX_TRANSCRIPT_LIMIT = 100000
_MEETING_ONLY_KEYS = ("transcript", "analyses", "latest_analysis", "analysis_count")


def is_meeting_context(detail: Optional[Dict[str, Any]]) -> bool:
    context = (detail or {}).get("context")
    return isinstance(context, dict) and "transcript" in context and "analyses" in context


def shape_detail(detail: Optional[Dict[str, Any]], request: RetrievalDetailRequest) -> Optional[Dict[str, Any]]:
    """Return a bounded detail payload; non-meeting details are returned unchanged."""
    if not is_meeting_context(detail):
        return detail
    context = detail["context"]
    sections = tuple(request.sections) if request.sections else DETAIL_SECTIONS
    transcript = str(context.get("transcript") or "")
    analyses = list(context.get("analyses") or [])

    shaped: Dict[str, Any] = {
        key: value for key, value in context.items() if key not in _MEETING_ONLY_KEYS
    }
    shaped["analysis_count"] = len(analyses)
    shaped["transcript_total_chars"] = len(transcript)
    shaped["analysis_catalog"] = [
        {
            "index": index,
            "timestamp": record.get("timestamp"),
            "modes": record.get("modes") or [],
            "model_used": record.get("model_used"),
            "meeting_id": record.get("meeting_id"),
            "filename": record.get("filename"),
            "content_chars": len(json.dumps(record.get("content"), ensure_ascii=False, default=str)),
        }
        for index, record in enumerate(analyses)
    ]
    shaped["sections_returned"] = [name for name in DETAIL_SECTIONS if name in sections]

    if "analyses" in sections:
        _add_analysis(shaped, analyses, request.analysis_index)
    if "transcript" in sections:
        _add_transcript_page(shaped, transcript, request.transcript_offset, request.transcript_limit)
    if "metadata" not in sections:
        for key in (
            "meeting_name", "purpose", "participants", "start_time", "end_time",
            "duration_seconds", "member_count", "is_post_processed",
        ):
            shaped.pop(key, None)
    return {**detail, "context": shaped}


def _add_analysis(shaped: Dict[str, Any], analyses: list, index: int) -> None:
    if not analyses:
        shaped["analyses"] = []
        return
    resolved = index if index >= 0 else len(analyses) + index
    if resolved < 0 or resolved >= len(analyses):
        shaped["analyses"] = []
        shaped["analysis_error"] = (
            f"analysis_index {index} is out of range; this meeting has {len(analyses)} analyses "
            f"(valid indexes 0 to {len(analyses) - 1}, or -1 for the latest). See analysis_catalog."
        )
        return
    shaped["analyses"] = [{"index": resolved, **analyses[resolved]}]


def _add_transcript_page(shaped: Dict[str, Any], transcript: str, offset: int, limit: int) -> None:
    total = len(transcript)
    start = max(0, min(offset, total))
    bounded_limit = max(1, min(limit, MAX_TRANSCRIPT_LIMIT))
    end = min(start + bounded_limit, total)
    if end < total:
        newline = transcript.rfind("\n", start, end)
        if newline > start:
            end = newline + 1
    shaped["transcript"] = transcript[start:end]
    truncated = end < total
    shaped["transcript_range"] = {
        "offset": start,
        "returned_chars": end - start,
        "total_chars": total,
        "truncated": truncated,
        "next_offset": end if truncated else None,
    }
    if truncated:
        shaped["transcript_hint"] = (
            f"Transcript continues. Call detail again with sections=['transcript'] and "
            f"transcript_offset={end} for the next page."
        )
