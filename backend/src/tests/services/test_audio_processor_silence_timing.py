"""Tests for AudioProcessor's native capture-offset origin setter."""

from types import SimpleNamespace

import pytest

from api.services.whisper_live_core.audio_processor import AudioProcessor


def test_native_stream_offset_updates_emitted_timeline_origin() -> None:
    origins: list[float] = []
    fake = SimpleNamespace(
        native_stream_offset_seconds=0.0,
        meeting_recorder=SimpleNamespace(
            timeline_offset_seconds=120.0,
            set_stream_timeline_origin_seconds=origins.append,
        ),
    )

    AudioProcessor.set_native_stream_offset_seconds(fake, 600.0)

    assert fake.native_stream_offset_seconds == 600.0
    assert origins == [720.0]
    with pytest.raises(ValueError):
        AudioProcessor.set_native_stream_offset_seconds(fake, float("nan"))


def _lag_fake(*, end_buffer: float, silence_active: bool, silence_start_processed: bool) -> SimpleNamespace:
    import asyncio

    return SimpleNamespace(
        lock=asyncio.Lock(),
        beg_loop=0.0,
        current_silence=object() if silence_active else None,
        _silence_start_processed=silence_start_processed,
        state=SimpleNamespace(
            end_buffer=end_buffer,
            tokens=[],
            end_attributed_speaker=0.0,
            remaining_time_transcription=0.0,
            remaining_time_diarization=0.0,
        ),
    )


@pytest.mark.asyncio
async def test_lag_is_zero_while_idle_in_a_processed_silence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("api.services.whisper_live_core.audio_processor.time", lambda: 500.0)
    fake = _lag_fake(end_buffer=213.0, silence_active=True, silence_start_processed=True)

    state = await AudioProcessor.get_current_state(fake)

    assert state.remaining_time_transcription == 0


@pytest.mark.asyncio
async def test_lag_still_reports_a_real_backlog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("api.services.whisper_live_core.audio_processor.time", lambda: 500.0)
    no_silence = _lag_fake(end_buffer=470.0, silence_active=False, silence_start_processed=False)
    unprocessed_silence_start = _lag_fake(end_buffer=470.0, silence_active=True, silence_start_processed=False)

    assert (await AudioProcessor.get_current_state(no_silence)).remaining_time_transcription == 30.0
    assert (await AudioProcessor.get_current_state(unprocessed_silence_start)).remaining_time_transcription == 30.0
