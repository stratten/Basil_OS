"""Tests for durable completion of iterative retranscription."""

import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from api.routes.meetings.post_processing_routes import complete_windowed_retranscription
from api.services.meetings.meeting_recorder import MeetingMetadata, MeetingRecorder


def _metadata(*, end_time: str | None) -> MeetingMetadata:
    return MeetingMetadata(
        id="meeting-1",
        name="Test meeting",
        start_time="2026-07-10T09:00:00Z",
        end_time=end_time,
    )


@pytest.mark.asyncio
async def test_completion_rejects_active_recording(tmp_path, monkeypatch):
    metadata = _metadata(end_time=None)
    monkeypatch.setattr(
        MeetingRecorder,
        "get_meeting_directory",
        staticmethod(lambda _meeting_id: tmp_path),
    )
    monkeypatch.setattr(
        MeetingRecorder,
        "load_metadata",
        staticmethod(lambda _meeting_id: metadata),
    )

    with pytest.raises(HTTPException) as error:
        await complete_windowed_retranscription("meeting-1")

    assert error.value.status_code == 409
    assert metadata.is_post_processed is False
    assert not (tmp_path / "metadata.json").exists()


@pytest.mark.asyncio
async def test_completion_persists_stopped_recording(tmp_path, monkeypatch):
    metadata = _metadata(end_time="2026-07-10T10:00:00Z")
    monkeypatch.setattr(
        MeetingRecorder,
        "get_meeting_directory",
        staticmethod(lambda _meeting_id: tmp_path),
    )
    monkeypatch.setattr(
        MeetingRecorder,
        "load_metadata",
        staticmethod(lambda _meeting_id: metadata),
    )
    (tmp_path / "transcript.json").write_text(json.dumps({"segments": []}))

    result = await complete_windowed_retranscription("meeting-1")

    assert result == {"meeting_id": "meeting-1", "status": "complete"}
    assert metadata.is_post_processed is True
    assert json.loads((tmp_path / "metadata.json").read_text())["is_post_processed"] is True
