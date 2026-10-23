"""The analysis websocket forwards provisional item events and still completes."""

import json
from types import SimpleNamespace

import pytest

from api.routes.meetings import analysis_routes
from api.services.whisper_live_core.post_processing import (
    meeting_analyzer as analyzer_module,
)


class _FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_event_callback_frames_are_sent_before_the_complete_frame(monkeypatch, tmp_path):
    (tmp_path / "transcript.json").write_text(json.dumps({"segments": []}))
    monkeypatch.setattr(
        analysis_routes.MeetingRecorder,
        "get_meeting_directory",
        staticmethod(lambda _meeting_id: tmp_path),
    )
    analysis_routes.active_analysis["meeting-ws"] = {
        "model_id": "test-model",
        "modes": ["action_items"],
        "custom_instructions": None,
        "status": "pending",
        "progress": 0.0,
    }

    class FakeAnalyzer:
        saved_analysis_filename = "analysis_test.json"

        def __init__(self, _meeting_id, _model_id):
            pass

        async def analyze(self, modes, custom_instructions, progress_callback, event_callback):
            await event_callback({"type": "analysis_item", "mode": "action_items", "sequence": 0})
            await progress_callback({"overall_progress": 0.5, "message": "half"})
            return SimpleNamespace(to_dict=lambda: {"meeting_id": "meeting-ws"})

    monkeypatch.setattr(analyzer_module, "MeetingAnalyzer", FakeAnalyzer)
    websocket = _FakeWebSocket()

    await analysis_routes.meeting_analysis_status(websocket, "meeting-ws")

    assert websocket.accepted is True
    assert [frame["type"] for frame in websocket.sent] == [
        "analysis_item",
        "progress",
        "complete",
    ]
    assert websocket.sent[-1]["analysis"] == {"meeting_id": "meeting-ws"}
    assert "meeting-ws" not in analysis_routes.active_analysis
