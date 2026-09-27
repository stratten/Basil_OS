"""Tests for shared meeting session-grouping used by list and search routes."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from api.routes.meetings.meeting_grouping import clean_meeting_name, group_meetings
from api.services.meetings.meeting_recorder import MeetingRecorder


def raw(
    meeting_id: str,
    name: str,
    start_time: str,
    *,
    session_id: Optional[str] = None,
    audio_source: Optional[str] = None,
    duration_seconds: float = 0.0,
    timeline_offset_seconds: float = 0.0,
    recording_part_index: int = 0,
    is_post_processed: bool = False,
    analyses: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """A full on-disk metadata dict (every MeetingResponse field present)."""
    return {
        "id": meeting_id,
        "name": name,
        "purpose": None,
        "participants": [],
        "start_time": start_time,
        "end_time": None,
        "duration_seconds": duration_seconds,
        "audio_path": None,
        "transcript_path": None,
        "is_post_processed": is_post_processed,
        "session_id": session_id,
        "audio_source": audio_source,
        "timeline_offset_seconds": timeline_offset_seconds,
        "recording_part_index": recording_part_index,
        "analyses": analyses,
    }


def test_clean_meeting_name_strips_source_suffix():
    assert clean_meeting_name({"name": "Standup - Microphone", "audio_source": "Microphone"}) == "Standup"
    # No suffix / no source -> unchanged.
    assert clean_meeting_name({"name": "Standup", "audio_source": None}) == "Standup"


def test_session_collapses_to_microphone_representative():
    meetings = group_meetings([
        raw("sys1", "Standup - System Audio", "2026-01-01T10:00:00Z",
            session_id="S", audio_source="System Audio", duration_seconds=100),
        raw("mic1", "Standup - Microphone", "2026-01-01T10:00:01Z",
            session_id="S", audio_source="Microphone", duration_seconds=120),
    ])

    assert len(meetings) == 1
    rep = meetings[0]
    assert rep.id == "mic1", "microphone member is the representative"
    assert rep.name == "Standup", "representative name is cleaned of the source suffix"
    assert {m["id"] for m in rep.members} == {"mic1", "sys1"}


def test_grouped_session_requires_every_member_to_be_post_processed():
    meetings = group_meetings([
        raw("sys1", "Standup - System Audio", "2026-01-01T10:00:00Z",
            session_id="S", audio_source="System Audio", is_post_processed=False),
        raw("mic1", "Standup - Microphone", "2026-01-01T10:00:01Z",
            session_id="S", audio_source="Microphone", is_post_processed=True),
    ])

    assert meetings[0].is_post_processed is False

    completed = group_meetings([
        raw("sys1", "Standup - System Audio", "2026-01-01T10:00:00Z",
            session_id="S", audio_source="System Audio", is_post_processed=True),
        raw("mic1", "Standup - Microphone", "2026-01-01T10:00:01Z",
            session_id="S", audio_source="Microphone", is_post_processed=True),
    ])

    assert completed[0].is_post_processed is True


def test_duration_spans_whole_logical_meeting():
    # Part 1 is offset 120s and runs 90s -> logical span 210s, even though the
    # representative (part 0) is only 120s long.
    meetings = group_meetings([
        raw("mic0", "Sync - Microphone", "2026-01-01T10:00:00Z",
            session_id="S", audio_source="Microphone",
            duration_seconds=120, timeline_offset_seconds=0, recording_part_index=0),
        raw("mic1", "Sync - Microphone", "2026-01-01T10:02:00Z",
            session_id="S", audio_source="Microphone",
            duration_seconds=90, timeline_offset_seconds=120, recording_part_index=1),
    ])
    assert len(meetings) == 1
    assert meetings[0].duration_seconds == 210.0


def test_standalone_and_sorting_newest_first():
    meetings = group_meetings([
        raw("a", "Older", "2026-01-01T09:00:00Z"),
        raw("b", "Newer", "2026-01-02T09:00:00Z"),
    ])
    assert [m.id for m in meetings] == ["b", "a"], "sorted by start_time descending"
    # Standalone meetings carry no members.
    assert meetings[0].members is None


def test_standalone_without_analyses_has_no_analysis_summary():
    meetings = group_meetings([
        raw("a", "Older", "2026-01-01T09:00:00Z"),
    ])
    assert meetings[0].analysis_summary is None


def test_representative_analysis_summary_uses_its_own_metadata(tmp_path, monkeypatch):
    filename = "analysis_20240101_000000.json"
    monkeypatch.setattr(
        MeetingRecorder,
        "get_meeting_directory",
        staticmethod(lambda meeting_id: tmp_path),
    )
    with open(tmp_path / filename, "w") as f:
        json.dump(
            {
                "suggested_actions": [
                    {"execution_status": "proposed"},
                    {"execution_status": "submitted"},
                ]
            },
            f,
        )

    meetings = group_meetings([
        raw("sys1", "Standup - System Audio", "2026-01-01T10:00:00Z",
            session_id="S", audio_source="System Audio"),
        raw("mic1", "Standup - Microphone", "2026-01-01T10:00:01Z",
            session_id="S", audio_source="Microphone",
            analyses=[{
                "timestamp": "2026-01-01T11:00:00Z",
                "filename": filename,
            }]),
    ])

    assert len(meetings) == 1
    summary = meetings[0].analysis_summary
    assert summary is not None
    assert summary.count == 1
    assert summary.latest_filename == filename
    assert summary.pending_action_count == 1


def test_non_representative_member_analyses_not_surfaced(tmp_path, monkeypatch):
    filename = "analysis_20240101_000000.json"
    monkeypatch.setattr(
        MeetingRecorder,
        "get_meeting_directory",
        staticmethod(lambda meeting_id: tmp_path),
    )
    with open(tmp_path / filename, "w") as f:
        json.dump({"suggested_actions": [{"execution_status": "proposed"}]}, f)

    meetings = group_meetings([
        raw("sys1", "Standup - System Audio", "2026-01-01T10:00:00Z",
            session_id="S", audio_source="System Audio",
            analyses=[{
                "timestamp": "2026-01-01T11:00:00Z",
                "filename": filename,
            }]),
        raw("mic1", "Standup - Microphone", "2026-01-01T10:00:01Z",
            session_id="S", audio_source="Microphone"),
    ])

    assert len(meetings) == 1
    assert meetings[0].analysis_summary is None
