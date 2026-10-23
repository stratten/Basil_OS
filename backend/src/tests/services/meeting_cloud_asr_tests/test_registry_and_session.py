import asyncio

import pytest

from api.services.meeting_cloud_asr import session as session_module
from api.services.meeting_cloud_asr.models import (
    EVENT_FINAL,
    EVENT_INTERIM,
    STATE_CONNECTING,
    STATE_FALLBACK,
    STATE_OFF,
    STATE_STREAMING,
    AsrEvent,
    CloudAsrError,
)
from api.services.meeting_cloud_asr.registry import CloudStatusRegistry, SessionStatus
from api.services.meeting_cloud_asr.session import CloudAsrSession

from .fakes import FakeProvider, FakeRecorder, recording_registry, settle

CHUNK = session_module.SEND_CHUNK_BYTES


def build_session(provider, registry, recorder=None, failures=None, sent=None):
    recorder = recorder if recorder is not None else FakeRecorder()
    failures = failures if failures is not None else []
    sent = sent if sent is not None else []

    async def send_json(payload):
        sent.append(payload)

    session = CloudAsrSession(
        provider=provider,
        provider_id="deepgram",
        tier="streaming",
        base_sample=0,
        timeline_for_sample=lambda sample: None,
        meeting_recorder=recorder,
        send_json=send_json,
        on_failure=failures.append,
        registry=registry,
    )
    return session, recorder, failures, sent


def test_registry_aggregates_by_priority_and_publishes_only_changes() -> None:
    async def scenario():
        registry, frames = recording_registry()
        await registry.update(1, SessionStatus(STATE_FALLBACK, "deepgram", "streaming", "Deepgram closed the connection."))
        await registry.update(2, SessionStatus(STATE_CONNECTING, "deepgram", "streaming"))
        await registry.update(2, SessionStatus(STATE_CONNECTING, "deepgram", "streaming"))
        await registry.update(3, SessionStatus(STATE_STREAMING, "deepgram", "streaming"))
        await registry.update(3, None)
        await registry.update(2, None)
        await registry.update(1, None)
        return [frame["state"] for frame in frames], frames[0]["reason"]

    states, first_reason = asyncio.run(scenario())
    assert states == [STATE_FALLBACK, STATE_CONNECTING, STATE_STREAMING, STATE_CONNECTING, STATE_FALLBACK, STATE_OFF]
    assert first_reason == "Deepgram closed the connection."


def test_a_failing_broadcaster_never_breaks_a_session_update() -> None:
    async def broken(frame):
        raise RuntimeError("no sockets")

    registry = CloudStatusRegistry(broken)
    asyncio.run(registry.update(1, SessionStatus(STATE_STREAMING, "deepgram", "streaming")))
    assert registry.aggregate()["state"] == STATE_STREAMING


def test_audio_is_resent_in_100ms_chunks_results_become_frames_and_stop_flushes_the_remainder() -> None:
    async def scenario():
        registry, frames = recording_registry()
        provider = FakeProvider()
        session, recorder, failures, sent = build_session(provider, registry)
        session.start()
        await settle()
        session.feed(b"\x01\x00" * 800)
        session.feed(b"\x01\x00" * 800)
        session.feed(b"\x01\x00" * 1000)
        await settle()
        provider.push(AsrEvent(EVENT_INTERIM, "hel", 0.0, 0.5))
        provider.push(AsrEvent(EVENT_FINAL, "hello there", 0.0, 1.0, True))
        await settle()
        await session.stop()
        return provider, recorder, failures, sent, frames

    provider, recorder, failures, sent, frames = asyncio.run(scenario())
    assert [len(chunk) for chunk in provider.sent] == [CHUNK, 2000]
    assert provider.closed >= 1 and failures == []
    assert [frame["buffer_transcription"] for frame in sent] == ["hel", ""]
    assert sent[-1]["lines"][0]["text"] == "hello there"
    assert recorder.segments[0]["text"] == "hello there"
    assert [frame["state"] for frame in frames] == [STATE_CONNECTING, STATE_STREAMING, STATE_OFF]


def test_a_tail_shorter_than_fifty_milliseconds_is_dropped_on_stop() -> None:
    async def scenario():
        registry, _ = recording_registry()
        provider = FakeProvider()
        session, *_ = build_session(provider, registry)
        session.start()
        await settle()
        session.feed(b"\x01\x00" * 100)
        await session.stop()
        return provider

    assert asyncio.run(scenario()).sent == []


def test_results_that_arrive_while_stopping_are_recorded_before_stop_returns() -> None:
    async def scenario():
        registry, _ = recording_registry()
        provider = FakeProvider(final_on_close=AsrEvent(EVENT_FINAL, "last words", 2.0, 3.0, True))
        session, recorder, _, sent = build_session(provider, registry)
        session.start()
        await settle()
        session.feed(b"\x01\x00" * 1600)
        await settle()
        await session.stop()
        return recorder, sent

    recorder, sent = asyncio.run(scenario())
    assert [segment["text"] for segment in recorder.segments] == ["last words"]
    assert sent[-1]["lines"][-1]["text"] == "last words"


def test_a_connection_failure_reports_fallback_once_and_stops_taking_audio() -> None:
    async def scenario():
        registry, frames = recording_registry()
        provider = FakeProvider(open_error=CloudAsrError("Deepgram rejected the API key."))
        session, recorder, failures, _ = build_session(provider, registry)
        session.start()
        await settle(12)
        session.feed(b"\x01\x00" * 1600)
        await session.stop()
        return provider, failures, frames

    provider, failures, frames = asyncio.run(scenario())
    assert failures == ["Deepgram rejected the API key."]
    assert provider.sent == []
    assert [(frame["state"], frame["reason"]) for frame in frames] == [
        (STATE_CONNECTING, None),
        (STATE_FALLBACK, "Deepgram rejected the API key."),
        (STATE_OFF, None),
    ]


def test_a_provider_failure_mid_stream_triggers_the_fallback_callback() -> None:
    async def scenario():
        registry, frames = recording_registry()
        provider = FakeProvider()
        session, _, failures, _ = build_session(provider, registry)
        session.start()
        await settle()
        provider.push(CloudAsrError("The Deepgram connection was lost."))
        await settle(12)
        await session.stop()
        return failures, session.failed

    failures, failed = asyncio.run(scenario())
    assert failures == ["The Deepgram connection was lost."] and failed is True


def test_unexpected_exceptions_fall_back_with_a_generic_message() -> None:
    async def scenario():
        registry, _ = recording_registry()
        provider = FakeProvider(open_error=RuntimeError("secret internals"))
        session, _, failures, _ = build_session(provider, registry)
        session.start()
        await settle(12)
        await session.stop()
        return failures

    assert asyncio.run(scenario()) == ["Cloud transcription failed."]


def test_an_unbounded_backlog_while_connecting_falls_back_instead_of_growing() -> None:
    async def scenario():
        registry, _ = recording_registry()
        provider = FakeProvider()
        provider.open_gate = asyncio.Event()
        session, _, failures, _ = build_session(provider, registry)
        session.start()
        await settle()
        seconds = int(session_module.MAX_BUFFERED_SECONDS) + 2
        for _ in range(seconds):
            session.feed(b"\x00\x00" * 16000)
        await settle(12)
        provider.open_gate.set()
        await session.stop()
        return failures

    assert asyncio.run(scenario()) == ["Cloud transcription is falling behind."]


def test_stopping_before_the_connection_finishes_does_not_hang_or_leak_a_registry_entry(monkeypatch) -> None:
    monkeypatch.setattr(session_module, "STOP_FLUSH_SECONDS", 0.05)

    async def scenario():
        registry, frames = recording_registry()
        provider = FakeProvider()
        provider.open_gate = asyncio.Event()
        session, *_ = build_session(provider, registry)
        session.start()
        await settle()
        await asyncio.wait_for(session.stop(), timeout=5)
        await session.stop()
        return registry.aggregate()["state"]

    assert asyncio.run(scenario()) == STATE_OFF


def test_lag_is_audio_sent_minus_the_end_of_the_latest_result() -> None:
    async def scenario():
        registry, _ = recording_registry()
        provider = FakeProvider()
        session, recorder, _, _ = build_session(provider, registry)
        session.start()
        await settle()
        for _ in range(20):
            session.feed(b"\x01\x00" * 1600)
        await settle(12)
        provider.push(AsrEvent(EVENT_INTERIM, "working", 0.0, 1.5))
        await settle()
        lag = recorder.transcription_lag_seconds
        await session.stop()
        return lag

    assert asyncio.run(scenario()) == pytest.approx(0.5, abs=1e-6)
