"""Recording-clock window mapping for windowed re-transcription.

The audio fixture stores a distinct constant sample value per file second (second ``n`` holds the value ``n + 1``), so a runner can prove which region of the compacted file a window actually read.
"""

import math
import wave
from pathlib import Path

import numpy as np
import pytest

from api.services.whisper_live_core.post_processing.meeting_timeline import MeetingTimeline
from api.services.whisper_live_core.post_processing.windowed_retranscription import transcribe_window

SAMPLE_RATE = 16000

# 60 s of captured audio in the file: [meeting 0, 30) then, after a 100 s outage, [meeting 130, 160).
RANGES = [{"start": 0.0, "end": 30.0}, {"start": 130.0, "end": 160.0}]


def _write_marked_wav(path: Path, seconds: int) -> None:
    samples = np.concatenate(
        [np.full(SAMPLE_RATE, second + 1, dtype=np.int16) for second in range(seconds)]
    )
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(samples.tobytes())


class RecordingRunner:
    """Records the first file second each run read and returns one segment spanning the run."""

    def __init__(self) -> None:
        self.first_seconds = []
        self.durations = []

    async def __call__(self, frames, rate, width, channels, duration, model_id, callback):
        samples = np.frombuffer(frames, dtype=np.int16)
        self.first_seconds.append(int(samples[0]) - 1)
        self.durations.append(duration)
        return [{"start": 0.0, "end": duration, "text": f"from-file-second-{int(samples[0]) - 1}", "speaker": None}]


@pytest.mark.asyncio
async def test_window_after_the_gap_reads_the_matching_file_region_and_stays_on_the_meeting_clock(tmp_path: Path) -> None:
    wav_path = tmp_path / "audio.wav"
    _write_marked_wav(wav_path, 60)
    runner = RecordingRunner()

    segments = await transcribe_window(
        "m1", 140.0, 150.0, "fake", audio_path=wav_path, run_transcription=runner,
        timeline=MeetingTimeline.from_ranges(RANGES),
    )

    assert runner.first_seconds == [40]
    assert math.isclose(runner.durations[0], 10.0)
    assert len(segments) == 1
    assert math.isclose(segments[0]["start"], 140.0)
    assert math.isclose(segments[0]["end"], 150.0)


@pytest.mark.asyncio
async def test_window_inside_the_gap_returns_no_segments_and_does_not_invoke_the_runner(tmp_path: Path) -> None:
    wav_path = tmp_path / "audio.wav"
    _write_marked_wav(wav_path, 60)
    runner = RecordingRunner()

    segments = await transcribe_window(
        "m1", 40.0, 120.0, "fake", audio_path=wav_path, run_transcription=runner,
        timeline=MeetingTimeline.from_ranges(RANGES),
    )

    assert segments == []
    assert runner.first_seconds == []


@pytest.mark.asyncio
async def test_window_spanning_the_gap_transcribes_each_captured_piece_separately(tmp_path: Path) -> None:
    wav_path = tmp_path / "audio.wav"
    _write_marked_wav(wav_path, 60)
    runner = RecordingRunner()

    segments = await transcribe_window(
        "m1", 20.0, 140.0, "fake", audio_path=wav_path, run_transcription=runner,
        timeline=MeetingTimeline.from_ranges(RANGES),
    )

    assert runner.first_seconds == [20, 30]
    assert [round(seg["start"], 3) for seg in segments] == [20.0, 130.0]
    assert [round(seg["end"], 3) for seg in segments] == [30.0, 140.0]


@pytest.mark.asyncio
async def test_live_window_reads_a_growing_file_through_an_open_ended_final_range(tmp_path: Path) -> None:
    wav_path = tmp_path / "audio.wav"
    _write_marked_wav(wav_path, 60)
    runner = RecordingRunner()
    stale_ranges = [{"start": 0.0, "end": 30.0}, {"start": 130.0, "end": 130.0}]

    segments = await transcribe_window(
        "m1", 140.0, 150.0, "fake", audio_path=wav_path, run_transcription=runner, live=True,
        timeline=MeetingTimeline.from_ranges(stale_ranges, live=True),
    )

    assert runner.first_seconds == [40]
    assert math.isclose(segments[0]["start"], 140.0)


@pytest.mark.asyncio
async def test_live_window_past_the_audio_on_disk_returns_no_segments(tmp_path: Path) -> None:
    wav_path = tmp_path / "audio.wav"
    _write_marked_wav(wav_path, 60)
    runner = RecordingRunner()

    segments = await transcribe_window(
        "m1", 400.0, 460.0, "fake", audio_path=wav_path, run_transcription=runner, live=True,
        timeline=MeetingTimeline.from_ranges([{"start": 0.0, "end": 30.0}, {"start": 130.0, "end": 130.0}], live=True),
    )

    assert segments == []
    assert runner.first_seconds == []


@pytest.mark.asyncio
async def test_legacy_timeline_reads_the_window_at_the_same_file_offsets(tmp_path: Path) -> None:
    wav_path = tmp_path / "audio.wav"
    _write_marked_wav(wav_path, 60)
    runner = RecordingRunner()

    segments = await transcribe_window(
        "m1", 10.0, 20.0, "fake", audio_path=wav_path, run_transcription=runner,
        timeline=MeetingTimeline.from_ranges(None),
    )

    assert runner.first_seconds == [10]
    assert math.isclose(segments[0]["start"], 10.0)
