"""Tests for leading-silence trimming before OpenAI upload."""

import io
import struct
import wave

import pytest

from api.services.transcription.backends.openai_whisper_api import leading_silence_trim
from api.services.transcription.backends.openai_whisper_api.leading_silence_trim import (
    ONSET_LEAD_IN_SECONDS,
    find_speech_onset_frame,
    leading_trim_frames,
    trim_leading_silence_wav,
)

SAMPLE_RATE = 1000
LOUD_AMPLITUDE = 10_000


def _build_wav(spans, *, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Build a mono 16-bit WAV from ``[(seconds, amplitude), ...]`` spans."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        frames = []
        for seconds, amplitude in spans:
            for _ in range(int(seconds * sample_rate)):
                frames.append(struct.pack("<h", amplitude))
        writer.writeframes(b"".join(frames))
    return buffer.getvalue()


def _wav_frame_count(wav_bytes: bytes) -> int:
    with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
        return reader.getnframes()


def test_trims_long_leading_silence_frame_exact() -> None:
    wav = _build_wav([(5.0, 0), (5.0, LOUD_AMPLITUDE)])
    total_frames = _wav_frame_count(wav)

    trimmed_wav, trimmed_seconds = trim_leading_silence_wav(wav)

    onset_frame = 5 * SAMPLE_RATE
    lead_in_frames = int(ONSET_LEAD_IN_SECONDS * SAMPLE_RATE)
    expected_drop = onset_frame - lead_in_frames

    assert trimmed_seconds == pytest.approx(expected_drop / SAMPLE_RATE)
    # Frame-exact: the reported duration maps back to a whole number of frames.
    assert round(trimmed_seconds * SAMPLE_RATE) == expected_drop
    assert _wav_frame_count(trimmed_wav) == total_frames - expected_drop


def test_lead_in_retained_so_first_phoneme_not_clipped() -> None:
    wav = _build_wav([(5.0, 0), (5.0, LOUD_AMPLITUDE)])
    trimmed_wav, _ = trim_leading_silence_wav(wav)

    lead_in_frames = int(ONSET_LEAD_IN_SECONDS * SAMPLE_RATE)
    with wave.open(io.BytesIO(trimmed_wav), "rb") as reader:
        head = reader.readframes(lead_in_frames)
    # The retained lead-in is the silence just before onset (all zero samples).
    assert head == b"\x00\x00" * lead_in_frames


def test_all_silent_audio_is_noop() -> None:
    wav = _build_wav([(8.0, 0)])
    trimmed_wav, trimmed_seconds = trim_leading_silence_wav(wav)
    assert trimmed_seconds == 0.0
    assert trimmed_wav == wav


def test_short_leading_silence_not_trimmed() -> None:
    # 1s of silence is below MIN_LEADING_TRIM_SECONDS once the lead-in is kept.
    wav = _build_wav([(1.0, 0), (5.0, LOUD_AMPLITUDE)])
    trimmed_wav, trimmed_seconds = trim_leading_silence_wav(wav)
    assert trimmed_seconds == 0.0
    assert trimmed_wav == wav


def test_trim_is_idempotent() -> None:
    wav = _build_wav([(5.0, 0), (5.0, LOUD_AMPLITUDE)])
    once, first_trim = trim_leading_silence_wav(wav)
    assert first_trim > 0.0
    twice, second_trim = trim_leading_silence_wav(once)
    assert second_trim == 0.0
    assert twice == once


def test_invalid_audio_is_noop() -> None:
    garbage = b"not a wav file at all"
    trimmed_wav, trimmed_seconds = trim_leading_silence_wav(garbage)
    assert trimmed_seconds == 0.0
    assert trimmed_wav == garbage


def test_onset_rejects_transient_click() -> None:
    # A 0.1s click at 0.5s is shorter than ONSET_MIN_SUSTAIN_SECONDS and must
    # not be mistaken for speech onset; the real onset is the sustained tone.
    wav = _build_wav([
        (0.5, 0),
        (0.1, LOUD_AMPLITUDE),
        (4.4, 0),
        (3.0, LOUD_AMPLITUDE),
    ])
    with wave.open(io.BytesIO(wav), "rb") as reader:
        sample_width = reader.getsampwidth()
        frame_rate = reader.getframerate()
        channels = reader.getnchannels()
        frame_bytes = reader.readframes(reader.getnframes())

    onset = find_speech_onset_frame(
        frame_bytes,
        bytes_per_frame=channels * sample_width,
        sample_width=sample_width,
        frame_rate=frame_rate,
    )
    assert onset is not None
    # Real tone starts at 0.5 + 0.1 + 4.4 = 5.0s.
    assert onset == pytest.approx(5.0 * SAMPLE_RATE, abs=frame_rate * ONSET_LEAD_IN_SECONDS)
    assert onset >= int(4.9 * SAMPLE_RATE)


def test_leading_trim_frames_zero_when_no_onset() -> None:
    wav = _build_wav([(3.0, 0)])
    with wave.open(io.BytesIO(wav), "rb") as reader:
        sample_width = reader.getsampwidth()
        frame_rate = reader.getframerate()
        channels = reader.getnchannels()
        frame_bytes = reader.readframes(reader.getnframes())

    assert (
        leading_trim_frames(
            frame_bytes,
            bytes_per_frame=channels * sample_width,
            sample_width=sample_width,
            frame_rate=frame_rate,
        )
        == 0
    )
