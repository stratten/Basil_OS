import uuid

import pytest

from api.services.meetings import meeting_recording_registry as registry
from api.services.meetings.meeting_recorder import MeetingRecorder


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def events():
    captured = []

    def listener(event, meeting_id, recorder, payload):
        captured.append((event, meeting_id, payload))

    registry.add_listener(listener)
    yield captured
    registry.remove_listener(listener)


def new_id() -> str:
    return f"companion-tap-{uuid.uuid4()}"


def test_started_segment_and_stopped_are_announced(isolated_home, events):
    meeting_id = new_id()
    recorder = MeetingRecorder(meeting_id=meeting_id, audio_source="Microphone")
    recorder.start_recording(meeting_name="Tap test")
    recorder.add_transcript_segment(start=1.0, end=2.0, text=" hello there", speaker=None)
    recorder.add_transcript_segment(start=2.0, end=3.0, text=" interim", speaker=None, is_interim=True)
    recorder.stop_recording()

    names = [event[0] for event in events if event[1] == meeting_id]
    assert names == ["started", "segment", "stopped"]
    segment_payload = next(event[2] for event in events if event[0] == "segment")
    assert segment_payload["segment"]["text"] == " hello there"
    assert segment_payload["segment"]["start"] == 1.0


def test_discard_announces_discarded_once(isolated_home, events):
    meeting_id = new_id()
    recorder = MeetingRecorder(meeting_id=meeting_id)
    recorder.start_recording(meeting_name="Discard tap test")
    registry.discard(meeting_id, recorder.meeting_dir)
    names = [event[0] for event in events if event[1] == meeting_id]
    assert names == ["started", "discarded"]


def test_raising_listener_does_not_break_recording_or_other_listeners(isolated_home, events):
    def broken(event, meeting_id, recorder, payload):
        raise RuntimeError("boom")

    registry.add_listener(broken)
    try:
        meeting_id = new_id()
        recorder = MeetingRecorder(meeting_id=meeting_id)
        recorder.start_recording(meeting_name="Broken listener test")
        recorder.add_transcript_segment(start=0.0, end=1.0, text=" still recorded", speaker=None)
        recorder.stop_recording()
        assert len(recorder.transcript_segments) == 1
        assert [event[0] for event in events if event[1] == meeting_id] == ["started", "segment", "stopped"]
    finally:
        registry.remove_listener(broken)


def test_active_recorders_snapshot(isolated_home):
    meeting_id = new_id()
    recorder = MeetingRecorder(meeting_id=meeting_id)
    recorder.start_recording(meeting_name="Snapshot test")
    try:
        assert recorder in registry.active_recorders()
    finally:
        recorder.stop_recording()
    assert recorder not in registry.active_recorders()
