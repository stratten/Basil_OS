"""Projects recorded meetings on disk into narrative-worthy zettel cards.

Meetings live under ~/.basil/meetings/<id>/ rather than in a SQL table, so
there is no zettel_id back-reference column to stamp. Idempotency instead
rests entirely on the (source_kind, source_id) UNIQUE constraint on
zettel_entries: a logical meeting is un-carded exactly when no row for
('meeting', representative_id) exists yet, so stamp() is a deliberate no-op
and _existing_ids() is the sole "already carded" gate.

Grouping mirrors the meeting sidebar exactly (group_meetings) so a mic +
system-audio recording of one call, or a resumed multi-part recording,
becomes one card keyed by the representative meeting id, not one per member.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional, Sequence

from api.routes.meetings.analysis_summary import ANALYSIS_FILENAME_RE
from api.routes.meetings.meeting_grouping import (
    clean_meeting_name,
    group_meetings,
    load_all_raw_meetings,
)
from api.routes.meetings.models import MeetingResponse
from api.services.meetings.meeting_recorder import MeetingRecorder
from api.services.whisper_live_core.post_processing.transcript_merger import (
    merge_session_transcripts,
)
from api.services.zettel.normalization import to_utc_iso, truncate
from api.services.zettel.sources.base import ZettelDraft

logger = logging.getLogger(__name__)


def _is_closed(meeting: MeetingResponse) -> bool:
    """True once every member's recording has stopped.

    duration_seconds is only ever set by MeetingRecorder.stop_recording()
    alongside end_time, so its presence on every member is a disk-observable
    "not currently recording" signal that needs no in-memory recorder state.
    """
    if meeting.members:
        return all(member.get("duration_seconds") is not None for member in meeting.members)
    return meeting.duration_seconds is not None


class MeetingZettelSource:
    """Projects grouped, closed meetings into thin cards."""

    source_kind = "meeting"

    def find_uncarded(
        self,
        conn: sqlite3.Connection,
        *,
        since_iso: Optional[str],
        limit: int,
    ) -> List[ZettelDraft]:
        existing = self._existing_ids(conn)
        drafts: List[ZettelDraft] = []
        for meeting in self._closed_meetings():
            if meeting.id in existing:
                continue
            draft = self._draft(meeting)
            if draft is None:
                continue
            if since_iso and draft.occurred_at < since_iso:
                continue
            drafts.append(draft)
        drafts.sort(key=lambda draft: draft.occurred_at)
        return drafts[:limit]

    def count_uncarded(
        self,
        conn: sqlite3.Connection,
        *,
        since_iso: Optional[str],
    ) -> int:
        # Meeting counts are small (hundreds, not millions); reusing
        # find_uncarded with an effectively unbounded limit keeps the
        # eligibility rules in exactly one place rather than risking drift
        # between a count-only and a build-only implementation.
        return len(self.find_uncarded(conn, since_iso=since_iso, limit=1_000_000))

    def stamp(
        self,
        conn: sqlite3.Connection,
        draft: ZettelDraft,
        zettel_id: str,
    ) -> None:
        """No-op: meetings have no source-table column to back-reference.

        The (source_kind, source_id) UNIQUE constraint on zettel_entries,
        checked directly by _existing_ids, is the sole idempotency guard.
        """
        return

    def gather_context(
        self,
        conn: sqlite3.Connection,
        source_ids: Sequence[str],
    ) -> Dict[str, Dict[str, Any]]:
        wanted = {str(value) for value in source_ids}
        context: Dict[str, Dict[str, Any]] = {}
        for meeting in self._all_meetings():
            if meeting.id in wanted:
                context[meeting.id] = self._build_context(meeting)
        return context

    # ------------------------------------------------------------------

    def _existing_ids(self, conn: sqlite3.Connection) -> set:
        rows = conn.execute(
            "SELECT source_id FROM zettel_entries WHERE source_kind = 'meeting'"
        ).fetchall()
        return {row["source_id"] for row in rows}

    def _all_meetings(self) -> List[MeetingResponse]:
        try:
            return group_meetings(load_all_raw_meetings())
        except Exception:
            logger.exception("Failed to load meetings for zettel carding")
            return []

    def _closed_meetings(self) -> List[MeetingResponse]:
        return [meeting for meeting in self._all_meetings() if _is_closed(meeting)]

    def _draft(self, meeting: MeetingResponse) -> Optional[ZettelDraft]:
        occurred_at = to_utc_iso(meeting.start_time)
        if occurred_at is None:
            logger.debug("Skipping meeting %s: no parseable start_time", meeting.id)
            return None
        member_ids = (
            [member["id"] for member in meeting.members if member.get("id")]
            if meeting.members
            else [meeting.id]
        )
        name = clean_meeting_name(meeting.model_dump()) or "Meeting"
        analyses = self._analysis_records(meeting)
        return ZettelDraft(
            source_kind=self.source_kind,
            source_id=meeting.id,
            event_type="meeting",
            occurred_at=occurred_at,
            ended_at=to_utc_iso(meeting.end_time) if meeting.end_time else None,
            title=name,
            summary=self._card_summary(analyses, meeting.purpose),
            outcome=None,
            source_status=None,
            payload={
                "meeting_id": meeting.id,
                "member_count": len(member_ids),
                "participant_count": len(meeting.participants or []),
                "duration_seconds": meeting.duration_seconds,
                "is_post_processed": meeting.is_post_processed,
                "has_analysis": bool(analyses),
            },
            member_source_ids=member_ids,
        )

    def _card_summary(
        self, analyses: Sequence[Dict[str, Any]], purpose: Optional[str]
    ) -> Optional[str]:
        for analysis in reversed(analyses):
            markdown = analysis["content"].get("summary")
            if markdown:
                return truncate(str(markdown), 500)
        if purpose:
            return truncate(purpose, 500)
        return None

    def _build_context(self, meeting: MeetingResponse) -> Dict[str, Any]:
        analyses = self._analysis_records(meeting)
        return {
            "meeting_name": clean_meeting_name(meeting.model_dump()),
            "purpose": meeting.purpose,
            "participants": meeting.participants or [],
            "start_time": meeting.start_time,
            "end_time": meeting.end_time,
            "duration_seconds": meeting.duration_seconds,
            "member_count": len(meeting.members) if meeting.members else 1,
            "is_post_processed": meeting.is_post_processed,
            "transcript": self._merged_transcript_text(meeting),
            "analysis_count": len(analyses),
            "analyses": analyses,
            "latest_analysis": analyses[-1]["content"] if analyses else None,
        }

    def _merged_transcript_text(self, meeting: MeetingResponse) -> str:
        members_payload = []
        for member_id, source_label, timeline_offset_seconds in self._member_references(meeting):
            if not member_id:
                continue
            transcript = MeetingRecorder.load_transcript(member_id)
            segments = (transcript or {}).get("segments") or []
            if segments:
                members_payload.append({
                    "source": source_label or "Unknown",
                    "segments": segments,
                    "start_offset_seconds": timeline_offset_seconds,
                })
        if not members_payload:
            return ""
        merged = merge_session_transcripts(members_payload)
        lines: List[str] = []
        for segment in merged.get("segments", []):
            text = (segment.get("text") or "").strip()
            if not text:
                continue
            start = segment.get("start")
            prefix = f"[{start:.1f}s] " if isinstance(start, (int, float)) else ""
            speaker = segment.get("speaker") or "Speaker"
            lines.append(f"{prefix}{speaker}: {text}")
        return "\n".join(lines)

    def _analysis_records(self, meeting: MeetingResponse) -> List[Dict[str, Any]]:
        """Load every valid analysis belonging to every member of a session."""
        records: List[Dict[str, Any]] = []
        for meeting_id, _source_label, _timeline_offset_seconds in self._member_references(meeting):
            metadata = MeetingRecorder.load_metadata(meeting_id)
            for analysis in (metadata.analyses if metadata and metadata.analyses else []):
                filename = str(analysis.get("filename") or "")
                content = self._load_analysis_file(meeting_id, filename)
                if content is None:
                    continue
                records.append(
                    {
                        "meeting_id": meeting_id,
                        "timestamp": analysis.get("timestamp"),
                        "filename": filename,
                        "modes": analysis.get("modes") or [],
                        "model_used": analysis.get("model_used"),
                        "content": content,
                    }
                )
        return sorted(
            records,
            key=lambda analysis: (str(analysis["timestamp"] or ""), analysis["filename"]),
        )

    def _member_references(
        self, meeting: MeetingResponse
    ) -> List[tuple[str, Optional[str], float]]:
        references = (
            [
                (
                    member.get("id"),
                    member.get("source"),
                    member.get("timeline_offset_seconds"),
                )
                for member in meeting.members
            ]
            if meeting.members
            else [(meeting.id, meeting.audio_source, 0.0)]
        )
        result: List[tuple[str, Optional[str], float]] = []
        for member_id, source_label, offset in references:
            if not member_id:
                continue
            try:
                timeline_offset_seconds = float(offset or 0.0)
            except (TypeError, ValueError):
                timeline_offset_seconds = 0.0
            result.append((str(member_id), source_label, timeline_offset_seconds))
        return result

    def _load_analysis_file(self, meeting_id: str, filename: str) -> Optional[Dict[str, Any]]:
        if not filename or not ANALYSIS_FILENAME_RE.match(filename):
            return None
        path = MeetingRecorder.get_meeting_directory(meeting_id) / filename
        try:
            with open(path, "r") as handle:
                data = json.load(handle)
        except Exception:
            logger.warning("Failed to read analysis file %s for meeting %s", filename, meeting_id)
            return None
        return data if isinstance(data, dict) else None
