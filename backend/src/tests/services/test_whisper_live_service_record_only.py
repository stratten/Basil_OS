"""Socket-level tests for record-only capture, engine refusal, and discarded-id refusal."""

import asyncio
import json
import uuid
import wave
from pathlib import Path

import pytest

from api.services.live_transcription.live_stream_session import RECORDING_ONLY_STATUS
from api.services.live_transcription.whisper_live_service import WhisperLiveService, is_legacy_termination_control
from api.services.meetings import meeting_recording_registry, meeting_search_indexer


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


class FakeWebSocket:
    def __init__(self, params, messages) -> None:
        self.query_params = params
        self._messages = list(messages)
        self.accepted = False
        self.sent = []
        self.closed = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self):
        if self._messages:
            return self._messages.pop(0)
        return {"type": "websocket.disconnect"}

    async def send_json(self, payload) -> None:
        self.sent.append(payload)

    async def close(self, code: int = 1000, reason=None) -> None:
        self.closed = (code, reason)


def text(payload) -> dict:
    return {"type": "websocket.receive", "text": json.dumps(payload)}


def audio(data: bytes) -> dict:
    return {"type": "websocket.receive", "bytes": data}


def test_record_only_socket_records_every_frame_without_the_live_engine(isolated_home, monkeypatch) -> None:
    service = WhisperLiveService()

    async def fail_engine():
        raise AssertionError("record-only must not initialize the live engine")

    monkeypatch.setattr(service, "_ensure_live_engine", fail_engine)
    reindexed = []
    monkeypatch.setattr(meeting_search_indexer, "reindex", reindexed.append)
    meeting_id = f"record-only-{uuid.uuid4()}"
    websocket = FakeWebSocket(
        {"client": "native", "live_transcription": "false", "meeting_id": meeting_id, "meeting_name": "Record only"},
        [
            text({"type": "native_stream_timing", "stream_offset_seconds": 0.0}),
            audio(b"\x01\x00" * 3200),
            text({"type": "native_stream_clock", "elapsed_seconds": 0.2}),
            text({"type": "native_capture_state", "paused": True}),
            text({"type": "native_capture_state", "paused": False}),
            audio(b"\x02\x00" * 3200),
        ],
    )
    asyncio.run(service._handle_websocket(websocket))
    assert websocket.accepted is True
    assert websocket.sent[0]["status"] == RECORDING_ONLY_STATUS
    with wave.open(str(isolated_home / ".basil" / "meetings" / meeting_id / "audio.wav"), "rb") as recorded:
        assert recorded.getnframes() == 6400
    assert reindexed == [meeting_id]
    assert service.active_processors == {}


def test_unavailable_engine_refuses_before_creating_a_recording(isolated_home, monkeypatch) -> None:
    service = WhisperLiveService()

    async def unavailable():
        return None

    monkeypatch.setattr(service, "_ensure_live_engine", unavailable)
    meeting_id = f"no-engine-{uuid.uuid4()}"
    websocket = FakeWebSocket({"client": "native", "meeting_id": meeting_id, "meeting_name": "Live"}, [])
    asyncio.run(service._handle_websocket(websocket))
    assert websocket.closed == (1000, "Service not initialized")
    assert websocket.accepted is False
    assert (isolated_home / ".basil" / "meetings" / meeting_id).exists() is False


def test_browser_streams_always_require_the_live_engine(isolated_home, monkeypatch) -> None:
    service = WhisperLiveService()

    async def unavailable():
        return None

    monkeypatch.setattr(service, "_ensure_live_engine", unavailable)
    websocket = FakeWebSocket({"live_transcription": "false"}, [])
    asyncio.run(service._handle_websocket(websocket))
    assert websocket.closed == (1000, "Service not initialized")


def test_a_discarded_meeting_cannot_reconnect(isolated_home) -> None:
    service = WhisperLiveService()
    meeting_id = f"discarded-{uuid.uuid4()}"
    meeting_recording_registry.discard(meeting_id, isolated_home / ".basil" / "meetings" / meeting_id)
    websocket = FakeWebSocket(
        {"client": "native", "live_transcription": "false", "meeting_id": meeting_id, "meeting_name": "Gone", "reconnect": "true"},
        [],
    )
    asyncio.run(service._handle_websocket(websocket))
    assert websocket.closed == (1000, "Recording discarded")
    assert websocket.accepted is False
    assert (isolated_home / ".basil" / "meetings" / meeting_id).exists() is False


@pytest.mark.parametrize(
    "control_message",
    [
        '{"type":"native_stream_clock","elapsed_seconds":12.5}',
        '{"type":"native_capture_state","paused":true}',
        '{"type":"native_capture_state","paused":false}',
        '{"type":"native_live_transcription","enabled":false}',
        '{"type":"native_live_transcription","enabled":true}',
    ],
)
def test_new_controls_are_not_legacy_termination_commands(control_message: str) -> None:
    assert is_legacy_termination_control(control_message) is False
