"""Idle unload of the live transcription engine after a meeting switches to record-only."""

import asyncio
import json
import sys
import types
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.services.live_transcription.whisper_live_service import WhisperLiveService
from api.services.meetings import meeting_search_indexer
from api.services.whisper_live_core import TranscriptionEngine

AGENT_STREAMING_MODULE = "api.routes.websocket_routes.agent_task_streaming"


class FakeWebSocket:
    def __init__(self, params, messages) -> None:
        self.query_params = params
        self._messages = list(messages)
        self.sent = []

    async def accept(self) -> None:
        return None

    async def receive(self):
        if self._messages:
            return self._messages.pop(0)
        return {"type": "websocket.disconnect"}

    async def send_json(self, payload) -> None:
        self.sent.append(payload)

    async def close(self, code: int = 1000, reason=None) -> None:
        return None


def text(payload) -> dict:
    return {"type": "websocket.receive", "text": json.dumps(payload)}


def audio(data: bytes) -> dict:
    return {"type": "websocket.receive", "bytes": data}


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def loaded_service(monkeypatch):
    engine = object()
    monkeypatch.setattr(TranscriptionEngine, "_instance", engine)
    monkeypatch.setattr(TranscriptionEngine, "_initialized", True)
    fake_streaming = types.ModuleType(AGENT_STREAMING_MODULE)
    fake_streaming.streaming_manager = SimpleNamespace(whisper_kit=None)
    monkeypatch.setitem(sys.modules, AGENT_STREAMING_MODULE, fake_streaming)
    service = WhisperLiveService()
    service.kit = engine
    service.is_initialized = True
    return service, engine, fake_streaming


def test_idle_engine_is_released_including_the_singleton(loaded_service) -> None:
    service, _engine, _streaming = loaded_service
    assert asyncio.run(service.unload_live_engine_if_idle()) is True
    assert service.kit is None
    assert service.is_initialized is False
    assert TranscriptionEngine._instance is None
    assert TranscriptionEngine._initialized is False


def test_engine_stays_loaded_while_any_socket_uses_it(loaded_service) -> None:
    service, engine, _streaming = loaded_service
    service.active_processors[1] = SimpleNamespace(uses_live_engine=False)
    service.active_processors[2] = SimpleNamespace(uses_live_engine=True)
    assert asyncio.run(service.unload_live_engine_if_idle()) is False
    assert service.kit is engine
    assert TranscriptionEngine._instance is engine


def test_engine_shared_with_agent_task_streaming_is_never_released(loaded_service) -> None:
    service, engine, streaming = loaded_service
    streaming.streaming_manager.whisper_kit = engine
    assert asyncio.run(service.unload_live_engine_if_idle()) is False
    assert service.kit is engine
    assert TranscriptionEngine._initialized is True


def test_record_only_socket_close_unloads_after_the_idle_delay(loaded_service, isolated_home, monkeypatch) -> None:
    service, _engine, _streaming = loaded_service
    service.idle_unload_seconds = 0.0
    monkeypatch.setattr(meeting_search_indexer, "reindex", lambda meeting_id: None)
    websocket = FakeWebSocket(
        {"client": "native", "live_transcription": "false", "meeting_id": f"idle-{uuid.uuid4()}", "meeting_name": "Idle"},
        [text({"type": "native_stream_timing", "stream_offset_seconds": 0.0}), audio(b"\x01\x00" * 320)],
    )

    async def scenario():
        await service._handle_websocket(websocket)
        assert service._idle_unload_task is not None
        await service._idle_unload_task

    asyncio.run(scenario())
    assert service.kit is None
    assert service.is_initialized is False


def test_requesting_the_engine_cancels_a_pending_unload(loaded_service) -> None:
    service, engine, _streaming = loaded_service
    service.idle_unload_seconds = 60.0

    async def scenario():
        service._schedule_idle_unload()
        pending = service._idle_unload_task
        assert pending is not None
        assert await service._ensure_live_engine() is engine
        await asyncio.sleep(0)
        return pending

    pending = asyncio.run(scenario())
    assert pending.done()
    assert service._idle_unload_task is None
    assert service.kit is engine
