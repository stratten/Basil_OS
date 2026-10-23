"""Route-level persistence checks for windowed retranscription."""

import json
from datetime import datetime

import pytest
from fastapi import HTTPException

from api.routes.meetings import post_processing_routes
from api.routes.meetings.models import RetranscribeWindowConfig
from api.services.meetings.meeting_recorder import MeetingMetadata, MeetingRecorder
from api.services.whisper_live_core.post_processing.meeting_transcript_upgrade_ledger import (
    get_upgrade_ledger_path,
)


@pytest.mark.asyncio
async def test_window_route_records_successful_response(tmp_path, monkeypatch):
    (tmp_path / "audio.wav").write_bytes(b"audio")
    monkeypatch.setattr(
        MeetingRecorder,
        "get_meeting_directory",
        staticmethod(lambda _meeting_id: tmp_path),
    )

    async def fake_transcribe(*_args, **_kwargs):
        return [{"start": 0.0, "end": 5.0, "text": "upgraded", "speaker": None}]

    from api.services.whisper_live_core.post_processing import windowed_retranscription

    monkeypatch.setattr(windowed_retranscription, "transcribe_window", fake_transcribe)
    result = await post_processing_routes.retranscribe_window(
        "meeting-1",
        RetranscribeWindowConfig(model="test", start_seconds=0, end_seconds=5),
    )

    assert result["segments"][0]["text"] == "upgraded"
    ledger = json.loads(get_upgrade_ledger_path(tmp_path).read_text())
    assert ledger["upgrades"][0]["segments"][0]["text"] == "upgraded"


@pytest.mark.asyncio
async def test_completion_rejects_active_meeting_without_finalizing(tmp_path, monkeypatch):
    metadata = MeetingMetadata(id="meeting-1", name="Active")
    monkeypatch.setattr(
        MeetingRecorder,
        "get_meeting_directory",
        staticmethod(lambda _meeting_id: tmp_path),
    )
    monkeypatch.setattr(MeetingRecorder, "load_metadata", staticmethod(lambda _meeting_id: metadata))

    with pytest.raises(HTTPException) as error:
        await post_processing_routes.complete_windowed_retranscription("meeting-1")

    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_completion_finalizes_before_marking_processed(tmp_path, monkeypatch):
    transcript_path = tmp_path / "transcript.json"
    transcript_path.write_text(
        json.dumps({"meeting_id": "meeting-1", "segments": [{"start": 0, "end": 5, "text": "raw"}]})
    )
    metadata = MeetingMetadata(
        id="meeting-1",
        name="Finished",
        end_time=datetime.utcnow().isoformat() + "Z",
    )
    monkeypatch.setattr(
        MeetingRecorder,
        "get_meeting_directory",
        staticmethod(lambda _meeting_id: tmp_path),
    )
    monkeypatch.setattr(MeetingRecorder, "load_metadata", staticmethod(lambda _meeting_id: metadata))
    monkeypatch.setattr(
        post_processing_routes,
        "finalize_recorded_window_upgrades",
        lambda _meeting_id: {"segments": []},
    )

    from api.services.meetings import meeting_search_indexer

    reindexed = []
    monkeypatch.setattr(meeting_search_indexer, "reindex", lambda meeting_id: reindexed.append(meeting_id))

    result = await post_processing_routes.complete_windowed_retranscription("meeting-1")

    assert result["status"] == "complete"
    assert metadata.is_post_processed is True
    assert reindexed == ["meeting-1"]
