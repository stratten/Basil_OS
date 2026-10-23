"""Lightweight per-meeting analysis status for meeting list responses.

Read once per already-analyzed meeting when the list/search routes build
their response (group_meetings), never during the analyze/save path itself.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from api.services.meetings.meeting_recorder import MeetingRecorder

logger = logging.getLogger(__name__)

# Analysis filenames are generated as analysis_YYYYMMDD_HHMMSS.json (see
# MeetingAnalyzer._save_analysis). Shared with analysis_proposal_store so both
# constrain the path component to that exact shape.
ANALYSIS_FILENAME_RE = re.compile(r"^analysis_\d{8}_\d{6}\.json$")

# Statuses the client already treats as "handled" (MeetingActionProposalStore.
# isHandled). Anything else (including "proposed", "submitting", "failed", or
# an unrecognized value) counts as still-pending, mirroring that Swift
# default-active behavior exactly.
_HANDLED_EXECUTION_STATUSES = frozenset({"submitted", "completed", "dismissed"})


class MeetingAnalysisSummary(BaseModel):
    """Sidebar-facing summary of a meeting's analysis history."""

    count: int
    latest_filename: str
    latest_timestamp: str
    pending_action_count: Optional[int] = None


def _latest_entry(analyses: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Newest analyses[] entry that has both a filename and a timestamp."""
    candidates = [a for a in analyses if a.get("filename") and a.get("timestamp")]
    if not candidates:
        return None
    return max(candidates, key=lambda a: a["timestamp"])


def _count_pending_actions(meeting_id: str, filename: str) -> Optional[int]:
    """Read one analysis file and count not-yet-handled suggested actions.

    Returns None (unknown) if the filename is malformed or the file is
    missing/unreadable -- never raises, since this runs inline in the
    meeting list path.
    """
    if not ANALYSIS_FILENAME_RE.match(filename):
        logger.warning(
            f"Skipping malformed analysis filename {filename} for meeting {meeting_id}"
        )
        return None
    analysis_path = MeetingRecorder.get_meeting_directory(meeting_id) / filename
    try:
        with open(analysis_path, "r") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(
            f"Failed to read {analysis_path} for pending-action count: {e}"
        )
        return None
    proposals = data.get("suggested_actions") or []
    return sum(
        1
        for p in proposals
        if (p.get("execution_status") or "proposed")
        not in _HANDLED_EXECUTION_STATUSES
    )


def build_analysis_summary(
    meeting_id: str, raw_metadata: Dict[str, Any]
) -> Optional[MeetingAnalysisSummary]:
    """Build the sidebar analysis summary for one meeting, or None if it has
    never been analyzed. Performs at most one extra file read (the latest
    analysis file) -- never touches disk when `analyses` is empty/absent.
    """
    analyses = raw_metadata.get("analyses") or []
    if not analyses:
        return None
    latest = _latest_entry(analyses)
    if latest is None:
        return None
    pending = _count_pending_actions(meeting_id, latest["filename"])
    return MeetingAnalysisSummary(
        count=len(analyses),
        latest_filename=latest["filename"],
        latest_timestamp=latest["timestamp"],
        pending_action_count=pending,
    )
