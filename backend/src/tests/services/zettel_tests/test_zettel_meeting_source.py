"""MeetingZettelSource: closed-meeting carding, grouping, and detail context."""

import json
from pathlib import Path

import pytest

from .conftest import NonClosingConnection
from api.services.meetings.meeting_recorder import MeetingRecorder
from api.services.retrieval.registry import build_default_retrieval_registry
from api.services.retrieval.sources.zettel_source import ZettelBackedRetrievalSource
from api.services.zettel.materializer import ZettelMaterializer
from api.services.zettel.sources.meeting_source import MeetingZettelSource


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Redirect Path.home() so meeting directories live under a temp path."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def _materializer(conn):
    materializer = ZettelMaterializer(sources=[MeetingZettelSource()])
    materializer._connection = lambda: NonClosingConnection(conn)
    return materializer


def _record_and_stop(meeting_id, name, *, purpose=None, participants=None,
                      audio_source=None, session_id=None, segments=()):
    recorder = MeetingRecorder(meeting_id=meeting_id, audio_source=audio_source,
                                session_id=session_id)
    recorder.start_recording(name, purpose=purpose, participants=participants)
    for start, end, text, speaker in segments:
        recorder.add_transcript_segment(start, end, text, speaker=speaker)
    recorder.stop_recording()
    return recorder


def test_closed_standalone_meeting_is_carded(conn, isolated_home):
    _record_and_stop(
        "m1", "Weekly Sync", purpose="Status update", participants=["Alex", "Sam"],
        segments=[(0.0, 2.0, "Let's get started.", "Alex")],
    )
    result = _materializer(conn).run_pass(since_iso=None)
    assert result.carded == 1
    row = conn.execute(
        "SELECT source_kind, title, summary FROM zettel_entries WHERE source_id='m1'"
    ).fetchone()
    assert row["source_kind"] == "meeting"
    assert row["title"] == "Weekly Sync"


def test_still_recording_meeting_is_not_carded(conn, isolated_home):
    recorder = MeetingRecorder(meeting_id="m2")
    recorder.start_recording("In Progress Call")
    try:
        result = _materializer(conn).run_pass(since_iso=None)
        assert result.carded == 0
    finally:
        recorder.cleanup()


def test_grouped_session_members_produce_one_card(conn, isolated_home):
    _record_and_stop(
        "mic-1", "Client Call - Microphone", audio_source="Microphone",
        session_id="session-1",
        segments=[(0.0, 1.5, "Thanks for joining.", "Speaker 1")],
    )
    _record_and_stop(
        "sys-1", "Client Call - System Audio", audio_source="System Audio",
        session_id="session-1",
        segments=[(0.5, 2.0, "Happy to be here.", "Speaker 2")],
    )
    result = _materializer(conn).run_pass(since_iso=None)
    assert result.carded == 1
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM zettel_entries WHERE source_kind='meeting'"
    ).fetchone()["n"] == 1
    row = conn.execute(
        "SELECT source_id, title FROM zettel_entries WHERE source_kind='meeting'"
    ).fetchone()
    # Microphone member is preferred as the representative id, matching the
    # sidebar's grouping precedence.
    assert row["source_id"] == "mic-1"
    assert row["title"] == "Client Call"


def test_resumed_member_transcript_uses_its_timeline_offset(conn, isolated_home):
    _record_and_stop(
        "part-1",
        "Project Call - Microphone",
        audio_source="Microphone",
        session_id="session-2",
        segments=[(0.0, 1.0, "Opening discussion.", "Alex")],
    )
    _record_and_stop(
        "part-2",
        "Project Call - Microphone",
        audio_source="Microphone",
        session_id="session-2",
        segments=[(0.0, 1.0, "Discussion resumed.", "Alex")],
    )
    metadata_path = MeetingRecorder.get_meeting_directory("part-2") / "metadata.json"
    with open(metadata_path, "r") as handle:
        metadata = json.load(handle)
    metadata["timeline_offset_seconds"] = 60.0
    with open(metadata_path, "w") as handle:
        json.dump(metadata, handle)

    context = MeetingZettelSource().gather_context(conn, ["part-1"])
    transcript = context["part-1"]["transcript"]

    assert transcript.index("Opening discussion.") < transcript.index("Discussion resumed.")
    assert "[60.0s]" in transcript


def test_second_pass_cards_nothing_new(conn, isolated_home):
    _record_and_stop("m3", "One-off", segments=[(0.0, 1.0, "Hello.", "Speaker 1")])
    materializer = _materializer(conn)
    materializer.run_pass(since_iso=None)
    second = materializer.run_pass(since_iso=None)
    assert second.carded == 0
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM zettel_entries WHERE source_kind='meeting'"
    ).fetchone()["n"] == 1


def test_since_iso_excludes_meetings_before_the_floor(conn, isolated_home):
    _record_and_stop("old", "Old Meeting", segments=[(0.0, 1.0, "Hi.", "Speaker 1")])
    metadata_path = MeetingRecorder.get_meeting_directory("old") / "metadata.json"
    with open(metadata_path, "r") as handle:
        data = json.load(handle)
    data["start_time"] = "2020-01-01T00:00:00Z"
    data["end_time"] = "2020-01-01T00:10:00Z"
    with open(metadata_path, "w") as handle:
        json.dump(data, handle)

    result = _materializer(conn).run_pass(since_iso="2026-01-01T00:00:00+00:00")
    assert result.carded == 0


def test_gather_context_returns_merged_transcript_and_latest_analysis(conn, isolated_home):
    _record_and_stop(
        "m4", "Planning Meeting", purpose="Plan next quarter",
        participants=["Alex"],
        segments=[(0.0, 2.0, "Let's plan Q3.", "Alex")],
    )
    analysis_filename = "analysis_20260101_000000.json"
    analysis_path = MeetingRecorder.get_meeting_directory("m4") / analysis_filename
    with open(analysis_path, "w") as handle:
        json.dump({"summary": "Discussed Q3 planning priorities.", "action_items": []}, handle)
    second_analysis_filename = "analysis_20260102_000000.json"
    second_analysis_path = MeetingRecorder.get_meeting_directory("m4") / second_analysis_filename
    with open(second_analysis_path, "w") as handle:
        json.dump({"summary": "Confirmed Q3 owners.", "decisions": []}, handle)
    metadata_path = MeetingRecorder.get_meeting_directory("m4") / "metadata.json"
    with open(metadata_path, "r") as handle:
        data = json.load(handle)
    data["analyses"] = [{
        "timestamp": "2026-01-01T00:00:00Z",
        "filename": analysis_filename,
        "modes": ["summary"],
        "model_used": "test-model",
    }, {
        "timestamp": "2026-01-02T00:00:00Z",
        "filename": second_analysis_filename,
        "modes": ["summary", "decisions"],
        "model_used": "test-model",
    }]
    with open(metadata_path, "w") as handle:
        json.dump(data, handle)

    source = MeetingZettelSource()
    context = source.gather_context(conn, ["m4"])
    assert "Let's plan Q3." in context["m4"]["transcript"]
    assert context["m4"]["latest_analysis"]["summary"] == "Confirmed Q3 owners."
    assert [analysis["content"]["summary"] for analysis in context["m4"]["analyses"]] == [
        "Discussed Q3 planning priorities.",
        "Confirmed Q3 owners.",
    ]
    assert context["m4"]["participants"] == ["Alex"]


def test_malformed_analysis_filename_is_ignored(conn, isolated_home):
    _record_and_stop("m5", "Weird Meeting", segments=[(0.0, 1.0, "Hi.", "Speaker 1")])
    metadata_path = MeetingRecorder.get_meeting_directory("m5") / "metadata.json"
    with open(metadata_path, "r") as handle:
        data = json.load(handle)
    data["analyses"] = [{
        "timestamp": "2026-01-01T00:00:00Z",
        "filename": "../../etc/passwd",
        "modes": ["summary"],
        "model_used": "test-model",
    }]
    with open(metadata_path, "w") as handle:
        json.dump(data, handle)

    source = MeetingZettelSource()
    context = source.gather_context(conn, ["m5"])
    assert context["m5"]["latest_analysis"] is None


def test_retrieval_registry_detail_returns_meeting_context(conn, isolated_home):
    _record_and_stop(
        "m6",
        "Review",
        segments=[(0.0, 1.0, "Review the release notes.", "Alex")],
    )
    _materializer(conn).run_pass(since_iso=None)

    detail = ZettelBackedRetrievalSource("meeting").detail(conn, "m6")

    assert "meeting" in build_default_retrieval_registry().known_kinds()
    assert detail is not None
    assert "Review the release notes." in detail["context"]["transcript"]
    assert detail["detail_available"] is True
