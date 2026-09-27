"""
Tests for meeting list grouping of resumed parts.

A resumed meeting records new audio under fresh meeting ids but reuses the
original logical session_id. The listing endpoint must therefore present all
parts (mic, system, and resume continuations) as one history entry with members
ordered by recording part index and start time.
"""
import asyncio
import json
from pathlib import Path

import pytest

from api.routes.meetings.lifecycle_routes import list_meetings


def _write_metadata(meetings_dir: Path, payload: dict) -> None:
    # Fill the fields real metadata always carries so MeetingResponse validates.
    full = {
        "purpose": None,
        "end_time": None,
        "duration_seconds": None,
        "audio_path": None,
        "transcript_path": None,
    }
    full.update(payload)
    meeting_dir = meetings_dir / full["id"]
    meeting_dir.mkdir(parents=True, exist_ok=True)
    (meeting_dir / "metadata.json").write_text(json.dumps(full))


@pytest.fixture
def isolated_meetings(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path / ".basil" / "meetings"


def test_resumed_parts_group_into_single_entry_ordered_by_part(isolated_meetings):
    session_id = "session-logical-1"

    # Original mic + system parts (part index 0).
    _write_metadata(isolated_meetings, {
        "id": "mic-part-0",
        "name": "Standup - Microphone",
        "participants": [],
        "start_time": "2026-06-10T10:00:00Z",
        "is_post_processed": False,
        "session_id": session_id,
        "audio_source": "Microphone",
        "duration_seconds": 600.0,
        "timeline_offset_seconds": 0.0,
        "recording_part_index": 0,
    })
    _write_metadata(isolated_meetings, {
        "id": "sys-part-0",
        "name": "Standup - Zoom",
        "participants": [],
        "start_time": "2026-06-10T10:00:01Z",
        "is_post_processed": False,
        "session_id": session_id,
        "audio_source": "Zoom",
        "duration_seconds": 600.0,
        "timeline_offset_seconds": 0.0,
        "recording_part_index": 0,
    })
    # Resumed mic part (part index 1, offset onto the timeline).
    _write_metadata(isolated_meetings, {
        "id": "mic-part-1",
        "name": "Standup - Microphone",
        "participants": [],
        "start_time": "2026-06-10T10:30:00Z",
        "is_post_processed": False,
        "session_id": session_id,
        "audio_source": "Microphone",
        "duration_seconds": 120.0,
        "timeline_offset_seconds": 600.0,
        "recording_part_index": 1,
        "resumed_from_meeting_id": "mic-part-0",
    })
    # An unrelated legacy standalone meeting.
    _write_metadata(isolated_meetings, {
        "id": "legacy-standalone",
        "name": "Legacy Chat",
        "participants": [],
        "start_time": "2026-06-09T09:00:00Z",
        "is_post_processed": False,
    })

    meetings = asyncio.run(list_meetings())

    # One grouped entry for the session + one standalone legacy entry.
    assert len(meetings) == 2

    grouped = next(m for m in meetings if m.session_id == session_id)
    assert grouped.members is not None
    assert len(grouped.members) == 3

    # Representative shows the clean (de-suffixed) name.
    assert grouped.name == "Standup"

    # Members ordered by recording_part_index, then start_time:
    # both part-0 members before the part-1 resume continuation.
    indices = [member["recording_part_index"] for member in grouped.members]
    assert indices == [0, 0, 1]
    assert grouped.members[-1]["id"] == "mic-part-1"
    assert grouped.members[-1]["timeline_offset_seconds"] == 600.0

    # The standalone legacy meeting is not grouped.
    standalone = next(m for m in meetings if m.id == "legacy-standalone")
    assert standalone.members is None
