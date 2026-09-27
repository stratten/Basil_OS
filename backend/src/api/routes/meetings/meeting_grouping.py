"""Shared meeting-loading and session-grouping helpers.

Extracted from `list_meetings` so the list and search routes group identically:
recordings that share a `session_id` (the mic + system-audio + resumed parts of
one logical meeting) collapse into a single representative `MeetingResponse`
carrying `members[]`, while legacy session-less recordings stay standalone.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from .models import MeetingResponse
from .analysis_summary import build_analysis_summary


logger = logging.getLogger(__name__)


def meetings_directory() -> Path:
    return Path.home() / ".basil" / "meetings"


def clean_meeting_name(metadata: Dict[str, Any]) -> str:
    """Strip the trailing " - <audio_source>" suffix the client appends per
    source, so a grouped (multi-source) meeting shows a single clean name.
    """
    name = metadata.get("name") or ""
    audio_source = metadata.get("audio_source")
    if audio_source:
        suffix = f" - {audio_source}"
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def load_all_raw_meetings() -> List[Dict[str, Any]]:
    """Load the raw metadata dict for every meeting directory on disk."""
    meetings_dir = meetings_directory()
    if not meetings_dir.exists():
        return []

    raw_meetings: List[Dict[str, Any]] = []
    for meeting_dir in meetings_dir.iterdir():
        if not meeting_dir.is_dir():
            continue
        metadata_path = meeting_dir / "metadata.json"
        if not metadata_path.exists():
            continue
        try:
            with open(metadata_path, "r") as f:
                raw_meetings.append(json.load(f))
        except Exception as e:
            logger.warning(f"Failed to load metadata for {meeting_dir.name}: {e}")
    return raw_meetings


def group_meetings(raw_meetings: List[Dict[str, Any]]) -> List[MeetingResponse]:
    """Collapse session siblings into representatives, sorted newest-first.

    Identical grouping semantics to the original `list_meetings` body; callers
    apply their own filtering/pagination on the returned list.
    """
    sessions: Dict[str, List[Dict[str, Any]]] = {}
    standalone: List[Dict[str, Any]] = []
    for metadata in raw_meetings:
        session_id = metadata.get("session_id")
        if session_id:
            sessions.setdefault(session_id, []).append(metadata)
        else:
            standalone.append(metadata)

    meetings: List[MeetingResponse] = []

    # Standalone meetings: emit unchanged (single member, no grouping).
    for metadata in standalone:
        response = MeetingResponse(**metadata)
        response.analysis_summary = build_analysis_summary(response.id, metadata)
        meetings.append(response)

    # Grouped sessions: emit one representative entry carrying members[].
    for group in sessions.values():
        # Order by recording part first (resume continuations), then start time,
        # so resumed parts and their mic/system siblings stay in timeline order.
        ordered = sorted(
            group,
            key=lambda m: (int(m.get("recording_part_index") or 0), m.get("start_time") or ""),
        )
        # Prefer the Microphone member as representative; else the earliest.
        representative = next(
            (m for m in ordered if (m.get("audio_source") or "").lower() == "microphone"),
            ordered[0],
        )
        members = [
            {
                "id": m.get("id"),
                "source": m.get("audio_source"),
                "is_post_processed": bool(m.get("is_post_processed", False)),
                "start_time": m.get("start_time"),
                "duration_seconds": m.get("duration_seconds"),
                "timeline_offset_seconds": m.get("timeline_offset_seconds"),
                "recording_part_index": m.get("recording_part_index"),
            }
            for m in ordered
        ]
        representative_response = MeetingResponse(**representative)
        representative_response.name = clean_meeting_name(representative)
        representative_response.members = members
        # A grouped meeting is fully post-processed only when every recorded
        # member is complete. The representative is usually the microphone
        # track, so exposing its flag alone would falsely label the session
        # complete while a system-audio tail still failed or remains pending.
        representative_response.is_post_processed = all(
            member["is_post_processed"] for member in members
        )
        representative_response.analysis_summary = build_analysis_summary(
            representative_response.id, representative
        )

        # The sidebar duration must reflect the WHOLE logical meeting, not just
        # the representative (part 0) recording. Resumed parts sit at their
        # timeline_offset_seconds on the logical timeline, so the meeting spans to
        # the farthest part end = max(offset + duration) across all members.
        member_span = 0.0
        for m in ordered:
            offset = float(m.get("timeline_offset_seconds") or 0.0)
            dur = float(m.get("duration_seconds") or 0.0)
            member_span = max(member_span, offset + dur)
        if member_span > 0:
            representative_response.duration_seconds = member_span

        meetings.append(representative_response)

    # Sort by start time (newest first).
    meetings.sort(key=lambda m: m.start_time, reverse=True)
    return meetings
