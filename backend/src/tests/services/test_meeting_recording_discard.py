"""Tests for canceling a recording part: registry, recorder abandonment, and the discard route."""

import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.meetings import lifecycle_routes
from api.routes.meetings import router as meetings_router
from api.services.meetings import meeting_recording_registry
from api.services.meetings.meeting_recorder import MeetingRecorder


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def new_id() -> str:
    return f"discard-test-{uuid.uuid4()}"


def test_discard_abandons_the_live_recorder_and_deletes_its_files(isolated_home) -> None:
    meeting_id = new_id()
    recorder = MeetingRecorder(meeting_id=meeting_id)
    recorder.start_recording(meeting_name="Accidental meeting")
    recorder.write_audio_chunk(b"\x00\x00" * 160)
    assert meeting_recording_registry.is_active(meeting_id) is True

    assert meeting_recording_registry.discard(meeting_id, recorder.meeting_dir) is True
    assert recorder.meeting_dir.exists() is False
    assert recorder.is_recording is False
    assert meeting_recording_registry.is_active(meeting_id) is False
    recorder.write_audio_chunk(b"\x00\x00" * 160)
    recorder.set_stream_timeline_origin_seconds(1.0)
    assert recorder.stop_recording() is None
    assert recorder.meeting_dir.exists() is False
    assert meeting_recording_registry.is_discarded(meeting_id) is True


def test_a_discarded_id_refuses_a_reconnecting_recorder(isolated_home) -> None:
    meeting_id = new_id()
    meeting_recording_registry.discard(meeting_id, MeetingRecorder.get_meeting_directory(meeting_id))
    with pytest.raises(PermissionError):
        MeetingRecorder(meeting_id=meeting_id)
    assert MeetingRecorder.get_meeting_directory(meeting_id).exists() is False


def test_stop_unregisters_and_unregister_is_identity_checked(isolated_home) -> None:
    meeting_id = new_id()
    recorder = MeetingRecorder(meeting_id=meeting_id)
    recorder.start_recording(meeting_name="Kept meeting")
    recorder.stop_recording()
    assert meeting_recording_registry.is_active(meeting_id) is False

    other_id = new_id()
    first, second = object(), object()
    meeting_recording_registry.register(other_id, first)
    meeting_recording_registry.register(other_id, second)
    meeting_recording_registry.unregister(other_id, first)
    assert meeting_recording_registry.is_active(other_id) is True
    meeting_recording_registry.unregister(other_id, second)
    assert meeting_recording_registry.is_active(other_id) is False


def test_discard_route_reports_found_and_not_found(isolated_home, monkeypatch) -> None:
    removed = []
    monkeypatch.setattr(lifecycle_routes.meeting_search_indexer, "remove", removed.append)
    app = FastAPI()
    app.include_router(meetings_router)
    client = TestClient(app)

    meeting_id = new_id()
    recorder = MeetingRecorder(meeting_id=meeting_id)
    recorder.start_recording(meeting_name="Route discard")
    response = client.post(f"/meetings/{meeting_id}/discard-recording")
    assert response.status_code == 200
    assert response.json() == {"status": "discarded", "meeting_id": meeting_id}
    assert recorder.meeting_dir.exists() is False
    assert removed == [meeting_id]

    missing_id = new_id()
    response = client.post(f"/meetings/{missing_id}/discard-recording")
    assert response.json() == {"status": "not_found", "meeting_id": missing_id}

    response = client.post("/meetings/bad_id!/discard-recording")
    assert response.status_code == 400
