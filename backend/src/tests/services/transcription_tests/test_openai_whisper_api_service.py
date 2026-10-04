import asyncio
import io
import logging
import struct
import threading
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.services.transcription.backends.openai_whisper_api.direct_client import (
    DirectOpenAITranscriptionClient,
)
from api.services.transcription.backends.openai_whisper_api.request_policy import (
    build_transcription_attempt_policies,
    estimate_wav_duration_seconds,
    should_retry_transcription_error,
)
from api.services.transcription.backends.openai_whisper_api_service import (
    OpenAIWhisperAPITranscriptionService,
)
from api.services.transcription.backends.openai_whisper_api import service as openai_whisper_api_service
from api.services.transcription.backends.openai_whisper_api import upload_chunking


def _wav_bytes(*, seconds: float, sample_rate: int = 100) -> bytes:
    frame_count = int(seconds * sample_rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x00" * frame_count)
    return buffer.getvalue()


def _wav_bytes_with_quiet_span(
    *,
    seconds: float,
    quiet_start: float,
    quiet_end: float,
    sample_rate: int = 100,
) -> bytes:
    frame_count = int(seconds * sample_rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        frames = []
        for frame_index in range(frame_count):
            current_second = frame_index / sample_rate
            sample = 0 if quiet_start <= current_second <= quiet_end else 10_000
            frames.append(struct.pack("<h", sample))
        writer.writeframes(b"".join(frames))
    return buffer.getvalue()


def _wav_with_leading_silence(
    *,
    silence_seconds: float,
    loud_seconds: float,
    sample_rate: int = 1000,
    amplitude: int = 10_000,
) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        frames = []
        for _ in range(int(silence_seconds * sample_rate)):
            frames.append(struct.pack("<h", 0))
        for _ in range(int(loud_seconds * sample_rate)):
            frames.append(struct.pack("<h", amplitude))
        writer.writeframes(b"".join(frames))
    return buffer.getvalue()


def _incrementing_monotonic():
    current_time = -1.0

    def fake_monotonic() -> float:
        nonlocal current_time
        current_time += 1.0
        return current_time

    return fake_monotonic


def _ready_service() -> OpenAIWhisperAPITranscriptionService:
    service = OpenAIWhisperAPITranscriptionService(model_id="openai-whisper-1")
    service._model_loaded = True
    service._api_model_name = "whisper-1"
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("use_auth_proxy", "provider_text", "expected_text"),
    [
        (False, "  Hello from direct OpenAI. \n", "Hello from direct OpenAI. "),
        (True, "Hello from the auth proxy.  ", "Hello from the auth proxy. "),
        (False, " \t\n", ""),
    ],
)
async def test_transcribe_normalizes_api_output_for_continuous_dictation(
    monkeypatch: pytest.MonkeyPatch,
    use_auth_proxy: bool,
    provider_text: str,
    expected_text: str,
) -> None:
    service = _ready_service()
    persisted_texts: list[str] = []
    monkeypatch.setattr(
        openai_whisper_api_service,
        "should_route_through_auth_service",
        lambda: use_auth_proxy,
    )

    async def fake_begin(*args, **kwargs):
        return SimpleNamespace(is_retranscription=False)

    async def fake_complete(*args, **kwargs):
        persisted_texts.append(args[1])

    async def fake_provider_transcription(*args, **kwargs):
        return provider_text

    monkeypatch.setattr(openai_whisper_api_service.transcription_lifecycle, "begin", fake_begin)
    monkeypatch.setattr(openai_whisper_api_service.transcription_lifecycle, "complete", fake_complete)
    service._prepare_audio = lambda audio_data, context_info: (audio_data, ".wav")
    if use_auth_proxy:
        service._transcribe_via_auth_proxy = fake_provider_transcription
    else:
        service._transcribe_direct = fake_provider_transcription

    result = await service.transcribe(_wav_bytes(seconds=1.0))

    assert result == expected_text
    assert persisted_texts == [expected_text]


class _FakeOpenAITextResponse:
    text = "background transcription"


class _SlowFakeTranscriptions:
    def create(self, **kwargs):
        time.sleep(0.05)
        return _FakeOpenAITextResponse()


class _SlowFakeAudio:
    transcriptions = _SlowFakeTranscriptions()


class _SlowFakeOpenAIClient:
    audio = _SlowFakeAudio()

    def with_options(self, **kwargs):
        return self


class _GatedFakeTranscriptions:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.calling_thread_ids: list[int] = []

    def create(self, **kwargs):
        self.calling_thread_ids.append(threading.get_ident())
        if not self.release.wait(timeout=5):
            raise RuntimeError("gated fake transcription was never released")
        return _FakeOpenAITextResponse()


class _GatedFakeOpenAIClient:
    def __init__(self) -> None:
        self.transcriptions = _GatedFakeTranscriptions()
        self.audio = SimpleNamespace(transcriptions=self.transcriptions)

    def with_options(self, **kwargs):
        return self


class _FakeRetryableProviderError(Exception):
    status_code = 429


class _FakeNonRetryableProviderError(Exception):
    status_code = 401


class APITimeoutError(Exception):
    pass


class _RecordingFakeTranscriptions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _RecordingFakeAudio:
    def __init__(self, transcriptions):
        self.transcriptions = transcriptions


class _RecordingFakeOpenAIClient:
    def __init__(self, outcomes):
        self.transcriptions = _RecordingFakeTranscriptions(outcomes)
        self.audio = _RecordingFakeAudio(self.transcriptions)
        self.with_options_calls = []

    def with_options(self, **kwargs):
        self.with_options_calls.append(kwargs)
        return self


def test_openai_transcription_policy_uses_duration_aware_attempt_timeouts() -> None:
    policies = build_transcription_attempt_policies(audio_duration_seconds=30.0)

    assert [policy.read_timeout_seconds for policy in policies] == [6.0, 10.0]
    assert [policy.attempt_number for policy in policies] == [1, 2]
    assert all(policy.max_attempts == 2 for policy in policies)
    assert all(policy.connect_timeout_seconds == 5.0 for policy in policies)
    assert all(policy.write_timeout_seconds == 15.0 for policy in policies)
    assert all(policy.pool_timeout_seconds == 5.0 for policy in policies)


def test_openai_transcription_policy_scales_and_caps_long_audio() -> None:
    medium_policies = build_transcription_attempt_policies(audio_duration_seconds=120.0)
    long_policies = build_transcription_attempt_policies(audio_duration_seconds=600.0)

    assert [policy.read_timeout_seconds for policy in medium_policies] == [12.0, 24.0]
    assert [policy.read_timeout_seconds for policy in long_policies] == [18.0, 45.0]


def test_openai_transcription_policy_handles_unknown_duration_audio() -> None:
    policies = build_transcription_attempt_policies(audio_duration_seconds=None)

    assert [policy.read_timeout_seconds for policy in policies] == [12.0, 30.0]
    assert all(policy.audio_duration_seconds is None for policy in policies)


def test_estimate_wav_duration_seconds_reads_prepared_wav_audio() -> None:
    assert estimate_wav_duration_seconds(_wav_bytes(seconds=28.7)) == pytest.approx(
        28.7,
        abs=0.01,
    )
    assert estimate_wav_duration_seconds(b"not a wav") is None


def test_should_retry_transcription_error_classifies_provider_failures() -> None:
    assert should_retry_transcription_error(_FakeRetryableProviderError("rate limited"))
    assert not should_retry_transcription_error(_FakeNonRetryableProviderError("auth failed"))
    assert not should_retry_transcription_error(ValueError("unsupported model"))


@pytest.mark.asyncio
async def test_transcribe_segments_from_file_uses_single_request_under_upload_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "api.services.auth_service_client.should_route_through_auth_service",
        lambda: False,
    )
    monkeypatch.setattr(
        OpenAIWhisperAPITranscriptionService,
        "_OPENAI_AUDIO_UPLOAD_BUDGET_BYTES",
        1024 * 1024,
    )
    monkeypatch.setattr(
        OpenAIWhisperAPITranscriptionService,
        "_SINGLE_REQUEST_MAX_BYTES",
        1024 * 1024,
    )

    audio_path = tmp_path / "meeting.wav"
    audio_path.write_bytes(_wav_bytes(seconds=1.0))
    service = _ready_service()
    calls = []

    async def fake_transcribe_direct_segments(wav_bytes, suffix, language=None):
        calls.append((wav_bytes, suffix, language))
        return [{"start": 0.1, "end": 0.5, "text": "single request"}]

    service._transcribe_direct_segments = fake_transcribe_direct_segments

    segments = await service.transcribe_segments_from_file(audio_path, language="en")

    assert segments == [{"start": 0.1, "end": 0.5, "text": "single request"}]
    assert len(calls) == 1
    assert calls[0][1] == ".wav"
    assert calls[0][2] == "en"


@pytest.mark.asyncio
async def test_transcribe_segments_from_file_chunks_oversized_wav_and_offsets_timestamps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "api.services.auth_service_client.should_route_through_auth_service",
        lambda: False,
    )
    monkeypatch.setattr(
        OpenAIWhisperAPITranscriptionService,
        "_OPENAI_AUDIO_UPLOAD_BUDGET_BYTES",
        1_000,
    )
    monkeypatch.setattr(
        OpenAIWhisperAPITranscriptionService,
        "_WAV_CHUNK_HEADER_MARGIN_BYTES",
        100,
    )
    monkeypatch.setattr(
        OpenAIWhisperAPITranscriptionService,
        "_SINGLE_REQUEST_MAX_BYTES",
        1_000,
    )
    current_time = -1.0

    def fake_monotonic() -> float:
        nonlocal current_time
        current_time += 1.0
        return current_time

    monkeypatch.setattr(openai_whisper_api_service, "monotonic", fake_monotonic)

    audio_path = tmp_path / "meeting.wav"
    audio_path.write_bytes(_wav_bytes(seconds=20.0))
    service = _ready_service()
    calls = []
    progress_events = []

    async def fake_transcribe_direct_segments(wav_bytes, suffix, language=None):
        calls.append((wav_bytes, suffix, language))
        return [{
            "start": 0.25,
            "end": 0.75,
            "text": f"chunk {len(calls)}",
        }]

    service._transcribe_direct_segments = fake_transcribe_direct_segments

    async def progress_callback(stage_progress, current_time, message, eta_seconds):
        progress_events.append((stage_progress, current_time, message, eta_seconds))

    segments = await service.transcribe_segments_from_file(
        audio_path,
        language="en",
        progress_callback=progress_callback,
    )

    assert len(calls) > 1
    assert all(len(call[0]) <= 1_000 for call in calls)
    assert all(call[1] == ".wav" for call in calls)
    assert all(call[2] == "en" for call in calls)
    assert any("Preparing" in event[2] and "audio segments" in event[2] for event in progress_events)
    assert any("Transcribing audio segment 1 of" in event[2] for event in progress_events)
    assert any("Finished audio segment" in event[2] for event in progress_events)
    assert not any("API chunk" in event[2] for event in progress_events)
    assert any(
        "Finished audio segment" in event[2] and event[3] > 0
        for event in progress_events
    )
    assert [segment["text"] for segment in segments] == [
        f"chunk {index}" for index in range(1, len(calls) + 1)
    ]
    assert [segment["start"] for segment in segments] == sorted(
        segment["start"] for segment in segments
    )
    assert segments[0]["start"] == pytest.approx(0.25)
    assert segments[1]["start"] > segments[0]["start"]


def test_split_wav_for_upload_budget_prefers_quiet_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(upload_chunking, "TARGET_WAV_CHUNK_SECONDS", 6)
    monkeypatch.setattr(upload_chunking, "QUIET_SPLIT_SEARCH_RADIUS_SECONDS", 2)
    monkeypatch.setattr(upload_chunking, "QUIET_SPLIT_WINDOW_SECONDS", 0.1)
    monkeypatch.setattr(upload_chunking, "MIN_QUIET_SPLIT_SECONDS", 0.5)
    monkeypatch.setattr(upload_chunking, "MIN_WAV_CHUNK_SECONDS", 2)

    chunks = upload_chunking.split_wav_for_upload_budget(
        _wav_bytes_with_quiet_span(seconds=12.0, quiet_start=5.8, quiet_end=6.8),
        upload_budget_bytes=2_044,
        header_margin_bytes=44,
    )

    assert len(chunks) == 2
    assert 5.8 <= chunks[0][2] <= 6.8
    assert all(len(chunk_bytes) <= 2_044 for chunk_bytes, _, _ in chunks)


@pytest.mark.asyncio
async def test_direct_openai_text_request_does_not_block_event_loop(caplog) -> None:
    caplog.set_level(
        logging.INFO,
        logger="api.services.transcription.backends.openai_whisper_api.direct_client",
    )
    client = DirectOpenAITranscriptionClient(api_model_name="whisper-1")
    fake_client = _GatedFakeOpenAIClient()
    client._client = fake_client
    event_loop_thread_id = threading.get_ident()

    transcription_task = asyncio.create_task(
        client.transcribe_text(_wav_bytes(seconds=1.0), ".wav")
    )

    for _ in range(200):
        if fake_client.transcriptions.calling_thread_ids:
            break
        await asyncio.sleep(0.01)

    assert fake_client.transcriptions.calling_thread_ids
    assert event_loop_thread_id not in fake_client.transcriptions.calling_thread_ids
    assert not transcription_task.done()
    fake_client.transcriptions.release.set()
    assert await transcription_task == "background transcription"
    assert "request_id=" in caplog.text
    assert "OpenAI transcription request queued" in caplog.text
    assert "OpenAI transcription worker started" in caplog.text
    assert "OpenAI transcription request completed" in caplog.text


@pytest.mark.asyncio
async def test_direct_openai_segment_request_accepts_no_speech_response(caplog) -> None:
    caplog.set_level(
        logging.INFO,
        logger="api.services.transcription.backends.openai_whisper_api.direct_client",
    )
    client = DirectOpenAITranscriptionClient(api_model_name="whisper-1")
    client._client = _SlowFakeOpenAIClient()

    segments = await client.transcribe_segments(_wav_bytes(seconds=1.0), ".wav")

    assert segments == []
    assert "returned no segments" in caplog.text


@pytest.mark.asyncio
async def test_direct_openai_segment_request_rejects_malformed_segments() -> None:
    client = DirectOpenAITranscriptionClient(api_model_name="whisper-1")
    client._client = _RecordingFakeOpenAIClient(
        [{"segments": [{"start": None, "end": 1.0, "text": "invalid"}]}]
    )

    with pytest.raises(ValueError, match="invalid timestamped segments"):
        await client.transcribe_segments(_wav_bytes(seconds=1.0), ".wav")


@pytest.mark.asyncio
async def test_direct_openai_text_request_retries_once_with_per_attempt_timeouts() -> None:
    client = DirectOpenAITranscriptionClient(api_model_name="whisper-1")
    fake_openai = _RecordingFakeOpenAIClient([
        _FakeRetryableProviderError("rate limited"),
        _FakeOpenAITextResponse(),
    ])
    client._client = fake_openai

    result = await client.transcribe_text(_wav_bytes(seconds=30.0), ".wav")

    assert result == "background transcription"
    assert len(fake_openai.transcriptions.calls) == 2
    assert len(fake_openai.with_options_calls) == 2
    assert all(call["max_retries"] == 0 for call in fake_openai.with_options_calls)
    assert [
        call["timeout"].read
        for call in fake_openai.with_options_calls
    ] == [6.0, 10.0]


@pytest.mark.asyncio
async def test_direct_openai_text_request_does_not_retry_non_retryable_errors() -> None:
    client = DirectOpenAITranscriptionClient(api_model_name="whisper-1")
    fake_openai = _RecordingFakeOpenAIClient([
        _FakeNonRetryableProviderError("auth failed"),
    ])
    client._client = fake_openai

    with pytest.raises(_FakeNonRetryableProviderError):
        await client.transcribe_text(_wav_bytes(seconds=30.0), ".wav")

    assert len(fake_openai.transcriptions.calls) == 1
    assert len(fake_openai.with_options_calls) == 1


@pytest.mark.asyncio
async def test_direct_openai_text_request_reports_final_timeout_after_retry() -> None:
    client = DirectOpenAITranscriptionClient(api_model_name="whisper-1")
    fake_openai = _RecordingFakeOpenAIClient([
        APITimeoutError("first attempt timed out"),
        APITimeoutError("second attempt timed out"),
    ])
    client._client = fake_openai

    with pytest.raises(TimeoutError, match="timed out after 2 attempts"):
        await client.transcribe_text(_wav_bytes(seconds=30.0), ".wav")

    assert len(fake_openai.transcriptions.calls) == 2
    assert len(fake_openai.with_options_calls) == 2


@pytest.mark.asyncio
async def test_single_shot_trims_leading_silence_and_offsets_segments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        openai_whisper_api_service,
        "should_route_through_auth_service",
        lambda: False,
    )

    # 3s of dead air then 2s of audible tone. Onset is at 3.0s; a 0.3s lead-in
    # is retained, so 2.7s is trimmed and re-applied as an offset.
    audio_path = tmp_path / "meeting.wav"
    audio_path.write_bytes(
        _wav_with_leading_silence(silence_seconds=3.0, loud_seconds=2.0)
    )
    service = _ready_service()
    received: dict = {}

    async def fake_transcribe_direct_segments(wav_bytes, suffix, language=None):
        received["wav"] = wav_bytes
        received["suffix"] = suffix
        return [{"start": 0.0, "end": 1.0, "text": "hello"}]

    service._transcribe_direct_segments = fake_transcribe_direct_segments

    segments = await service.transcribe_segments_from_file(audio_path, language="en")

    assert segments == [
        {"start": pytest.approx(2.7), "end": pytest.approx(3.7), "text": "hello"}
    ]
    # The audio actually sent is the trimmed (shorter) clip.
    assert estimate_wav_duration_seconds(received["wav"]) == pytest.approx(2.3, abs=0.05)
    assert received["suffix"] == ".wav"


@pytest.mark.asyncio
async def test_chunked_path_offsets_by_trimmed_leading_silence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        openai_whisper_api_service,
        "should_route_through_auth_service",
        lambda: False,
    )
    monkeypatch.setattr(
        OpenAIWhisperAPITranscriptionService,
        "_OPENAI_AUDIO_UPLOAD_BUDGET_BYTES",
        1_000,
    )
    monkeypatch.setattr(
        OpenAIWhisperAPITranscriptionService,
        "_WAV_CHUNK_HEADER_MARGIN_BYTES",
        100,
    )
    monkeypatch.setattr(
        openai_whisper_api_service, "monotonic", _incrementing_monotonic()
    )
    monkeypatch.setattr(
        OpenAIWhisperAPITranscriptionService,
        "_SINGLE_REQUEST_MAX_BYTES",
        1_000,
    )
    # Force a known 1.0s leading trim per chunk so we can assert the offset math.
    monkeypatch.setattr(
        openai_whisper_api_service,
        "trim_leading_silence_wav",
        lambda chunk_bytes: (chunk_bytes, 1.0),
    )

    audio_path = tmp_path / "meeting.wav"
    audio_path.write_bytes(_wav_bytes(seconds=20.0))
    service = _ready_service()

    async def fake_transcribe_direct_segments(wav_bytes, suffix, language=None):
        return [{"start": 0.0, "end": 0.5, "text": "x"}]

    service._transcribe_direct_segments = fake_transcribe_direct_segments

    segments = await service.transcribe_segments_from_file(audio_path, language="en")

    assert len(segments) > 1
    # First chunk starts at 0.0; its segment is offset by the 1.0s trim.
    assert segments[0]["start"] == pytest.approx(1.0)
    assert all(segment["start"] >= 1.0 for segment in segments)


@pytest.mark.asyncio
async def test_chunked_path_drops_degenerate_chunk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog,
) -> None:
    caplog.set_level(
        logging.WARNING,
        logger="api.services.transcription.backends.openai_whisper_api.service",
    )
    monkeypatch.setattr(
        openai_whisper_api_service,
        "should_route_through_auth_service",
        lambda: False,
    )
    monkeypatch.setattr(
        OpenAIWhisperAPITranscriptionService,
        "_OPENAI_AUDIO_UPLOAD_BUDGET_BYTES",
        1_000,
    )
    monkeypatch.setattr(
        OpenAIWhisperAPITranscriptionService,
        "_WAV_CHUNK_HEADER_MARGIN_BYTES",
        100,
    )
    monkeypatch.setattr(
        openai_whisper_api_service, "monotonic", _incrementing_monotonic()
    )
    monkeypatch.setattr(
        openai_whisper_api_service,
        "trim_leading_silence_wav",
        lambda chunk_bytes: (chunk_bytes, 0.0),
    )
    monkeypatch.setattr(
        OpenAIWhisperAPITranscriptionService,
        "_SINGLE_REQUEST_MAX_BYTES",
        1_000,
    )

    def fake_guard(segments, *, chunk_duration_seconds):
        return bool(segments) and segments[0].get("text") == "DEGEN"

    monkeypatch.setattr(
        openai_whisper_api_service, "is_degenerate_segment_run", fake_guard
    )

    audio_path = tmp_path / "meeting.wav"
    audio_path.write_bytes(_wav_bytes(seconds=20.0))
    service = _ready_service()
    call_count = {"n": 0}

    async def fake_transcribe_direct_segments(wav_bytes, suffix, language=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [{"start": 0.0, "end": 0.5, "text": "DEGEN"}]
        return [{"start": 0.0, "end": 0.5, "text": f"chunk {call_count['n']}"}]

    service._transcribe_direct_segments = fake_transcribe_direct_segments

    segments = await service.transcribe_segments_from_file(audio_path, language="en")

    texts = [segment["text"] for segment in segments]
    assert "DEGEN" not in texts
    assert texts  # other chunks still produced output
    assert all(text.startswith("chunk ") for text in texts)
    # Every chunk was still sent to the API; only the degenerate one was dropped.
    assert call_count["n"] == len(texts) + 1
    assert "Dropping degenerate OpenAI re-transcription chunk" in caplog.text
