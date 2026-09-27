"""Tests for windowed (closed-range) re-transcription and splicing (2C)."""

import math
import wave
from pathlib import Path

import numpy as np
import pytest

from api.services.whisper_live_core.post_processing.windowed_retranscription import (
    next_checkpoint_end,
    offset_segments,
    plan_on_stop_window,
    read_audio_window,
    read_audio_window_live,
    retranscribe_window_and_splice,
    splice_segments,
    transcribe_window,
    windowed_checkpoints,
)

SAMPLE_RATE = 16000


# ---- cadence planning ----

def test_windowed_checkpoints_cover_full_duration() -> None:
    ranges = windowed_checkpoints(70.0, 30.0)
    assert ranges == [(0.0, 30.0), (30.0, 60.0), (60.0, 70.0)]
    # Contiguous and non-overlapping.
    for (_, end), (start, _) in zip(ranges, ranges[1:]):
        assert end == start


def test_windowed_checkpoints_empty_for_nonpositive() -> None:
    assert windowed_checkpoints(0.0, 30.0) == []
    assert windowed_checkpoints(60.0, 0.0) == []


def test_next_checkpoint_end_triggers_on_full_chunk() -> None:
    # 65s elapsed, 30s chunks, last checkpoint at 30 → next boundary is 60.
    assert next_checkpoint_end(65.0, 30.0, 30.0) == 60.0
    # Not yet a new full chunk past the last checkpoint.
    assert next_checkpoint_end(59.0, 30.0, 30.0) is None
    assert next_checkpoint_end(0.0, 30.0, 0.0) is None


def test_plan_on_stop_window_tail_vs_full() -> None:
    # Thresholds on: only the tail after the last checkpoint.
    assert plan_on_stop_window(True, 60.0, 70.0) == (60.0, 70.0)
    # Thresholds off: full file.
    assert plan_on_stop_window(False, 60.0, 70.0) == (0.0, 70.0)
    # Thresholds on but nothing checkpointed yet: full file.
    assert plan_on_stop_window(True, 0.0, 70.0) == (0.0, 70.0)


# ---- segment math ----

def test_offset_segments_shifts_times() -> None:
    segs = [{"start": 0.0, "end": 1.0, "text": "a"}]
    shifted = offset_segments(segs, 30.0)
    assert shifted[0]["start"] == 30.0 and shifted[0]["end"] == 31.0
    # Original untouched.
    assert segs[0]["start"] == 0.0


def test_splice_replaces_overlapping_range_without_duplication() -> None:
    existing = [
        {"start": 0.0, "end": 10.0, "text": "keep-before"},
        {"start": 30.0, "end": 40.0, "text": "stale-inside"},
        {"start": 70.0, "end": 80.0, "text": "keep-after"},
    ]
    new = [{"start": 30.0, "end": 38.0, "text": "fresh"}]
    merged = splice_segments(existing, new, 30.0, 60.0)
    texts = [s["text"] for s in merged]
    assert texts == ["keep-before", "fresh", "keep-after"]
    # No overlapping ranges remain.
    for a, b in zip(merged, merged[1:]):
        assert a["end"] <= b["start"] + 1e-9


def test_splice_boundary_midword_does_not_duplicate_or_drop() -> None:
    # Adversarial: an existing segment straddles the window start; it overlaps
    # and must be replaced (not duplicated) by the window's output.
    existing = [
        {"start": 28.0, "end": 32.0, "text": "straddles-start"},
        {"start": 45.0, "end": 50.0, "text": "inside"},
    ]
    new = [
        {"start": 30.0, "end": 33.0, "text": "win-a"},
        {"start": 45.0, "end": 49.0, "text": "win-b"},
    ]
    merged = splice_segments(existing, new, 30.0, 60.0)
    texts = [s["text"] for s in merged]
    assert "straddles-start" not in texts
    assert texts == ["win-a", "win-b"]


# ---- audio window IO ----

def _write_ramp_wav(path: Path, seconds: float) -> None:
    n = int(SAMPLE_RATE * seconds)
    # Distinct per-sample values so window extraction is verifiable.
    data = (np.arange(n, dtype=np.int16) % 1000)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(data.tobytes())


def test_read_audio_window_extracts_exact_range(tmp_path: Path) -> None:
    wav_path = tmp_path / "audio.wav"
    _write_ramp_wav(wav_path, 4.0)
    frames, rate, width, channels = read_audio_window(wav_path, 1.0, 3.0)
    assert rate == SAMPLE_RATE and width == 2 and channels == 1
    samples = np.frombuffer(frames, dtype=np.int16)
    assert samples.size == SAMPLE_RATE * 2  # exactly 2 seconds
    # First sample corresponds to frame index SAMPLE_RATE (1.0s in).
    assert samples[0] == (SAMPLE_RATE % 1000)


def test_read_audio_window_empty_for_out_of_bounds(tmp_path: Path) -> None:
    wav_path = tmp_path / "audio.wav"
    _write_ramp_wav(wav_path, 1.0)
    frames, _, _, _ = read_audio_window(wav_path, 5.0, 6.0)
    assert frames == b""


def test_read_audio_window_live_matches_finalized_reader(tmp_path: Path) -> None:
    # On a fully-written (finalized) file the live reader and the header-based
    # reader must agree exactly.
    wav_path = tmp_path / "audio.wav"
    _write_ramp_wav(wav_path, 4.0)
    live_frames, live_rate, live_width, live_channels = read_audio_window_live(wav_path, 1.0, 3.0)
    base_frames, base_rate, base_width, base_channels = read_audio_window(wav_path, 1.0, 3.0)
    assert (live_rate, live_width, live_channels) == (base_rate, base_width, base_channels)
    assert live_frames == base_frames


def test_read_audio_window_live_reads_past_stale_header(tmp_path: Path) -> None:
    # Simulate a mid-recording file: a valid WAV header that under-reports the
    # frame count, followed by additional raw PCM appended after the header was
    # written. The header-based reader is bounded by the stale frame count; the
    # live reader derives availability from file size and sees all the audio.
    wav_path = tmp_path / "audio.wav"
    seconds = 4.0
    n = int(SAMPLE_RATE * seconds)
    data = (np.arange(n, dtype=np.int16) % 1000).tobytes()

    # Write a header claiming only 1 frame, then append the full PCM payload.
    with wave.open(str(wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(data[:2])  # 1 frame -> header data size patched to 2 bytes
    with open(wav_path, "ab") as raw:
        raw.write(data[2:])  # append the rest of the audio after the (stale) header

    # The stale-header reader is clamped to ~1 frame and cannot serve [1, 3).
    base_frames, _, _, _ = read_audio_window(wav_path, 1.0, 3.0)
    assert base_frames == b""

    # The live reader serves the full 2-second window from the real bytes.
    live_frames, rate, width, channels = read_audio_window_live(wav_path, 1.0, 3.0)
    assert (rate, width, channels) == (SAMPLE_RATE, 2, 1)
    samples = np.frombuffer(live_frames, dtype=np.int16)
    assert samples.size == SAMPLE_RATE * 2
    assert samples[0] == (SAMPLE_RATE % 1000)


@pytest.mark.asyncio
async def test_transcribe_window_live_uses_live_reader(tmp_path: Path) -> None:
    wav_path = tmp_path / "audio.wav"
    _write_ramp_wav(wav_path, 4.0)

    captured = {}

    async def fake_runner(frames, rate, width, channels, duration, model_id, cb):
        captured["frames_len"] = len(frames)
        return [{"start": 0.0, "end": duration, "text": "win"}]

    segs = await transcribe_window(
        "m1", 1.0, 3.0, "fake-model", audio_path=wav_path,
        run_transcription=fake_runner, live=True,
    )
    assert len(segs) == 1
    # 2 seconds of 16-bit mono PCM.
    assert captured["frames_len"] == SAMPLE_RATE * 2 * 2


# ---- orchestration with an injected runner ----

@pytest.mark.asyncio
async def test_transcribe_window_offsets_runner_output(tmp_path: Path) -> None:
    wav_path = tmp_path / "audio.wav"
    _write_ramp_wav(wav_path, 4.0)

    async def fake_runner(frames, rate, width, channels, duration, model_id, cb):
        # One window-relative segment spanning the whole window.
        return [{"start": 0.0, "end": duration, "text": "win"}]

    segs = await transcribe_window(
        "m1", 1.0, 3.0, "fake-model", audio_path=wav_path, run_transcription=fake_runner
    )
    assert len(segs) == 1
    assert math.isclose(segs[0]["start"], 1.0)
    assert math.isclose(segs[0]["end"], 3.0)


@pytest.mark.asyncio
async def test_two_window_splice_matches_whole_file(tmp_path: Path) -> None:
    wav_path = tmp_path / "audio.wav"
    _write_ramp_wav(wav_path, 4.0)

    async def fake_runner(frames, rate, width, channels, duration, model_id, cb):
        # Deterministic: one segment per second of the window.
        out = []
        whole = int(round(duration))
        for i in range(whole):
            out.append({"start": float(i), "end": float(i + 1), "text": f"s{i}"})
        return out

    # Whole-file in one shot.
    whole = await transcribe_window(
        "m1", 0.0, 4.0, "fake", audio_path=wav_path, run_transcription=fake_runner
    )

    # Two windows spliced into an (empty) transcript via the orchestrator.
    saved = {}

    def load_fn(_path):
        return {"meeting_id": "m1", "segments": []}

    async def save_fn(transcript, _path):
        saved["transcript"] = transcript

    await retranscribe_window_and_splice(
        "m1", 0.0, 2.0, "fake",
        audio_path=wav_path, run_transcription=fake_runner,
        load_transcript=load_fn, save_transcript=save_fn,
        transcript_path=tmp_path / "transcript.json",
    )

    def load_fn2(_path):
        return saved["transcript"]

    await retranscribe_window_and_splice(
        "m1", 2.0, 4.0, "fake",
        audio_path=wav_path, run_transcription=fake_runner,
        load_transcript=load_fn2, save_transcript=save_fn,
        transcript_path=tmp_path / "transcript.json",
    )

    spliced = saved["transcript"]["segments"]
    # Same number of segments and identical absolute spans as the whole-file run.
    assert len(spliced) == len(whole)
    for s, w in zip(spliced, whole):
        assert math.isclose(s["start"], w["start"])
        assert math.isclose(s["end"], w["end"])
