import asyncio
import json
import uuid
import wave
from pathlib import Path

import pytest

from api.services.live_transcription import whisper_live_service
from api.services.live_transcription.live_stream_session import LIVE_TRANSCRIPTION_UNAVAILABLE_STATUS
from api.services.live_transcription.whisper_live_service import WhisperLiveService
from api.services.meeting_cloud_asr.models import EVENT_FINAL, AsrEvent, CloudAsrError
from api.services.meeting_cloud_asr.session import CloudAsrSession
from api.services.meetings import meeting_recording_registry, meeting_search_indexer

from .fakes import FakeProvider, recording_registry


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(meeting_search_indexer, "reindex", lambda meeting_id: None)
    return tmp_path


class FakeWebSocket:
    def __init__(self, params, messages, idle_seconds: float = 0.0) -> None:
        self.query_params = params
        self._messages = list(messages)
        self._idle_seconds = idle_seconds
        self.accepted = False
        self.sent = []
        self.closed = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self):
        if self._messages:
            return self._messages.pop(0)
        if self._idle_seconds:
            await asyncio.sleep(self._idle_seconds)
        return {"type": "websocket.disconnect"}

    async def send_json(self, payload) -> None:
        self.sent.append(payload)

    async def close(self, code: int = 1000, reason=None) -> None:
        self.closed = (code, reason)


def audio(data: bytes) -> dict:
    return {"type": "websocket.receive", "bytes": data}


def text(payload) -> dict:
    return {"type": "websocket.receive", "text": json.dumps(payload)}


def install_cloud(monkeypatch, provider: FakeProvider):
    registry, frames = recording_registry()
    created = []

    def factory(**kwargs):
        session = CloudAsrSession(provider=provider, provider_id="deepgram", tier="streaming", registry=registry, **kwargs)
        created.append(session)
        return session

    monkeypatch.setattr(whisper_live_service, "cloud_transcription_available", lambda: True)
    monkeypatch.setattr(whisper_live_service, "create_cloud_session", factory)
    return frames, created


def native_params(meeting_id: str) -> dict:
    return {"client": "native", "meeting_id": meeting_id, "meeting_name": "Cloud meeting"}


def test_a_cloud_socket_streams_without_the_local_engine_and_keeps_the_last_results(isolated_home, monkeypatch) -> None:
    service = WhisperLiveService()

    async def fail_engine():
        raise AssertionError("cloud transcription must not initialize the local engine")

    monkeypatch.setattr(service, "_ensure_live_engine", fail_engine)
    provider = FakeProvider(final_on_close=AsrEvent(EVENT_FINAL, "closing remarks", 0.0, 1.0, True))
    frames, _ = install_cloud(monkeypatch, provider)
    meeting_id = f"cloud-{uuid.uuid4()}"
    websocket = FakeWebSocket(
        native_params(meeting_id),
        [text({"type": "native_stream_timing", "stream_offset_seconds": 0.0}), audio(b"\x01\x00" * 3200), audio(b"\x02\x00" * 3200)],
    )
    asyncio.run(service._handle_websocket(websocket))
    assert websocket.accepted is True and websocket.closed is None
    meeting_dir = isolated_home / ".basil" / "meetings" / meeting_id
    with wave.open(str(meeting_dir / "audio.wav"), "rb") as recorded:
        assert recorded.getnframes() == 6400
    transcript = json.loads((meeting_dir / "transcript.json").read_text())
    segments = transcript["segments"] if isinstance(transcript, dict) else transcript
    assert [segment["text"] for segment in segments] == ["closing remarks"]
    assert sum(len(chunk) for chunk in provider.sent) == 12800
    assert any(frame.get("lines") and frame["lines"][0]["text"] == "closing remarks" for frame in websocket.sent)
    assert [frame["state"] for frame in frames][-1] == "off"
    assert service.active_processors == {}


def test_a_cloud_failure_keeps_recording_and_reports_when_no_local_engine_can_take_over(isolated_home, monkeypatch) -> None:
    service = WhisperLiveService()

    async def no_engine():
        return None

    monkeypatch.setattr(service, "_ensure_live_engine", no_engine)
    provider = FakeProvider(open_error=CloudAsrError("Deepgram rejected the API key."))
    frames, _ = install_cloud(monkeypatch, provider)
    meeting_id = f"cloud-fail-{uuid.uuid4()}"
    websocket = FakeWebSocket(native_params(meeting_id), [audio(b"\x01\x00" * 3200), audio(b"\x02\x00" * 3200)], idle_seconds=0.3)
    asyncio.run(service._handle_websocket(websocket))
    with wave.open(str(isolated_home / ".basil" / "meetings" / meeting_id / "audio.wav"), "rb") as recorded:
        assert recorded.getnframes() == 6400
    assert LIVE_TRANSCRIPTION_UNAVAILABLE_STATUS in [frame.get("status") for frame in websocket.sent]
    assert ("fallback", "Deepgram rejected the API key.") in [(frame["state"], frame["reason"]) for frame in frames]
    assert frames[-1]["state"] == "off"


def test_browser_streams_still_require_the_local_engine_even_when_cloud_is_selected(isolated_home, monkeypatch) -> None:
    service = WhisperLiveService()

    async def no_engine():
        return None

    monkeypatch.setattr(service, "_ensure_live_engine", no_engine)
    install_cloud(monkeypatch, FakeProvider())
    websocket = FakeWebSocket({}, [])
    asyncio.run(service._handle_websocket(websocket))
    assert websocket.accepted is False and websocket.closed == (1000, "Service not initialized")


def test_without_a_cloud_plan_a_native_socket_still_needs_the_engine(isolated_home, monkeypatch) -> None:
    service = WhisperLiveService()

    async def no_engine():
        return None

    monkeypatch.setattr(service, "_ensure_live_engine", no_engine)
    monkeypatch.setattr(whisper_live_service, "cloud_transcription_available", lambda: False)
    websocket = FakeWebSocket({"client": "native"}, [])
    asyncio.run(service._handle_websocket(websocket))
    assert websocket.accepted is False and websocket.closed == (1000, "Service not initialized")
