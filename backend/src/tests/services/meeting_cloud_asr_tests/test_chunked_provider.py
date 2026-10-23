import asyncio
import wave
import io
from array import array
from typing import List

import pytest

from api.services.meeting_cloud_asr import chunked_provider
from api.services.meeting_cloud_asr.chunked_provider import ChunkedProxyProvider, peak_amplitude, pcm_to_wav, trim_overlap
from api.services.meeting_cloud_asr.models import EVENT_FINAL, CloudAsrError

SECOND = 16000 * 2


def loud(seconds: float) -> bytes:
    return array("h", [4000] * int(16000 * seconds)).tobytes()


def quiet(seconds: float) -> bytes:
    return array("h", [10] * int(16000 * seconds)).tobytes()


def test_trim_overlap_drops_repeated_leading_words_ignoring_case_and_punctuation() -> None:
    assert trim_overlap("we reviewed the budget today", "The budget, today. and then the plan") == "and then the plan"
    assert trim_overlap("alpha beta", "gamma delta") == "gamma delta"
    assert trim_overlap("", "fresh start") == "fresh start"
    assert trim_overlap("same words", "same words") == ""
    assert trim_overlap("a b c", "...") == "..."


def test_wav_and_peak_helpers() -> None:
    wav_bytes = pcm_to_wav(loud(0.5))
    with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
        assert (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getnframes()) == (1, 2, 16000, 8000)
    assert peak_amplitude(loud(0.1)) == 4000
    assert peak_amplitude(b"") == 0
    assert peak_amplitude(b"\x01") == 0


async def drive(provider: ChunkedProxyProvider, audio: List[bytes]) -> list:
    await provider.open()
    for chunk in audio:
        await provider.send_audio(chunk)
    await provider.close()
    return [event async for event in provider.events()]


def test_windows_overlap_dedupe_and_timestamps_follow_the_fresh_audio() -> None:
    windows: List[bytes] = []
    replies = ["we reviewed the budget", "the budget and the hiring plan", "plan for next quarter"]

    async def transcribe(wav_bytes: bytes) -> str:
        windows.append(wav_bytes)
        return replies[len(windows) - 1]

    provider = ChunkedProxyProvider(transcribe=transcribe, window_seconds=2.0, overlap_seconds=0.5)
    events = asyncio.run(drive(provider, [loud(2.0), loud(2.0), loud(1.5)]))
    assert [event.text for event in events] == ["we reviewed the budget", "and the hiring plan", "for next quarter"]
    assert [event.kind for event in events] == [EVENT_FINAL] * 3 and all(event.utterance_end for event in events)
    assert [(event.start_seconds, event.end_seconds) for event in events] == [(0.0, 2.0), (2.0, 4.0), (4.0, 5.5)]
    frames = []
    for wav_bytes in windows:
        with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
            frames.append(reader.getnframes())
    assert frames == [32000, 40000, 32000]


def test_silent_windows_are_never_sent_and_a_short_tail_is_dropped() -> None:
    sent: List[bytes] = []

    async def transcribe(wav_bytes: bytes) -> str:
        sent.append(wav_bytes)
        return "spoken"

    provider = ChunkedProxyProvider(transcribe=transcribe, window_seconds=2.0, overlap_seconds=0.5)
    events = asyncio.run(drive(provider, [quiet(2.0), loud(2.0), loud(0.4)]))
    assert len(sent) == 1
    assert [event.text for event in events] == ["spoken"]


def test_a_transient_connection_error_is_retried_once() -> None:
    attempts: List[int] = []

    async def transcribe(wav_bytes: bytes) -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("offline")
        return "recovered"

    async def scenario() -> list:
        original = asyncio.sleep

        async def fast_sleep(seconds: float) -> None:
            await original(0)

        asyncio.sleep = fast_sleep  # type: ignore[assignment]
        try:
            provider = ChunkedProxyProvider(transcribe=transcribe, window_seconds=2.0, overlap_seconds=0.5)
            return await drive(provider, [loud(2.0)])
        finally:
            asyncio.sleep = original  # type: ignore[assignment]

    events = asyncio.run(scenario())
    assert len(attempts) == 2 and [event.text for event in events] == ["recovered"]


def test_a_proxy_failure_surfaces_a_user_safe_error_and_stops_accepting_audio() -> None:
    async def transcribe(wav_bytes: bytes) -> str:
        raise ValueError("Subscription inactive -- please update your subscription")

    async def scenario() -> str:
        provider = ChunkedProxyProvider(transcribe=transcribe, window_seconds=2.0, overlap_seconds=0.5)
        await provider.open()
        await provider.send_audio(loud(2.0))
        with pytest.raises(CloudAsrError) as raised:
            async for _ in provider.events():
                pass
        with pytest.raises(CloudAsrError):
            await provider.send_audio(loud(2.0))
        await provider.close()
        return str(raised.value)

    assert asyncio.run(scenario()) == "Subscription inactive -- please update your subscription"


def test_a_backlog_of_unsent_windows_fails_instead_of_growing_without_bound() -> None:
    gate = asyncio.Event

    async def scenario() -> None:
        release = gate()

        async def transcribe(wav_bytes: bytes) -> str:
            await release.wait()
            return "late"

        provider = ChunkedProxyProvider(transcribe=transcribe, window_seconds=1.0, overlap_seconds=0.0)
        await provider.open()
        with pytest.raises(CloudAsrError) as raised:
            for _ in range(chunked_provider.MAX_PENDING_WINDOWS + 3):
                await provider.send_audio(loud(1.0))
                await asyncio.sleep(0)
        assert "falling behind" in str(raised.value)
        release.set()
        await provider.close()

    asyncio.run(scenario())
