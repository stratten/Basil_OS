"""Whole-file post-processing must leave transcript times on the recording clock.

The fixture mirrors the 11:03 microphone track: a compacted audio file whose captured ranges are separated by a long outage, so file time runs behind the recording clock after the gap.
"""

import json
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.services.meetings.meeting_recorder import MeetingRecorder
from api.services.whisper_live_core.post_processing import meeting_processor

# 100 s in the file: meeting [0, 40) then, after a 500 s outage, meeting [540, 600).
RANGES = [{"start": 0.0, "end": 40.0}, {"start": 540.0, "end": 600.0}]


def _write_wav(path: Path, seconds: int) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16_000)
        writer.writeframes(b"\x00\x00" * 16_000 * seconds)


class _FileClockTranscriber:
    """Returns segments on the file clock, one before and one after the gap."""

    def __init__(self, *_args) -> None:
        pass

    async def transcribe_with_selected_model(self, progress_callback):
        segments = [
            {"start": 10.0, "end": 12.0, "text": " before the gap "},
            {"start": 50.0, "end": 53.0, "text": " after the gap "},
        ]
        await progress_callback(0.5, 50.0, "halfway", 1.0, segments[1:])
        return segments


def _install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, metadata) -> meeting_processor.MeetingProcessor:
    _write_wav(tmp_path / "audio.wav", 100)
    monkeypatch.setattr(MeetingRecorder, "get_meeting_directory", staticmethod(lambda _id: tmp_path))
    monkeypatch.setattr(MeetingRecorder, "load_metadata", staticmethod(lambda _id: metadata))
    monkeypatch.setattr(meeting_processor, "TranscriptionProcessor", _FileClockTranscriber)
    return meeting_processor.MeetingProcessor("gapped", "whisper-1")


@pytest.mark.asyncio
async def test_transcribe_only_places_segments_on_the_recording_clock_and_keeps_them(tmp_path, monkeypatch) -> None:
    metadata = SimpleNamespace(timeline_offset_seconds=0.0, stream_timeline_ranges=RANGES)
    processor = _install(tmp_path, monkeypatch, metadata)
    streamed = []

    async def progress_callback(progress):
        streamed.extend(progress.get("new_segments") or [])

    transcript = await processor.transcribe_only(progress_callback)

    starts = [(seg["start"], seg["end"], seg["text"]) for seg in transcript["segments"]]
    assert starts == [(10.0, 12.0, "before the gap"), (550.0, 553.0, "after the gap")]
    assert [(seg["start"], seg["end"]) for seg in streamed] == [(550.0, 553.0)]
    saved = json.loads(processor.transcript_path.read_text())
    assert [(seg["start"], seg["end"]) for seg in saved["segments"]] == [(10.0, 12.0), (550.0, 553.0)]


@pytest.mark.asyncio
async def test_recording_without_ranges_keeps_the_resume_offset_behavior(tmp_path, monkeypatch) -> None:
    metadata = SimpleNamespace(timeline_offset_seconds=30.0, stream_timeline_ranges=None)
    processor = _install(tmp_path, monkeypatch, metadata)

    async def progress_callback(_progress):
        return None

    transcript = await processor.transcribe_only(progress_callback)

    assert [(seg["start"], seg["end"]) for seg in transcript["segments"]] == [(40.0, 42.0), (80.0, 83.0)]


@pytest.mark.asyncio
async def test_diarization_speaker_segments_are_retimed_before_merging(tmp_path, monkeypatch) -> None:
    metadata = SimpleNamespace(timeline_offset_seconds=0.0, stream_timeline_ranges=RANGES)
    processor = _install(tmp_path, monkeypatch, metadata)
    processor.transcript_path.write_text(
        json.dumps(
            {
                "meeting_id": "gapped",
                "segments": [
                    {"start": 10.0, "end": 12.0, "text": "before the gap", "speaker": None},
                    {"start": 550.0, "end": 553.0, "text": "after the gap", "speaker": None},
                ],
            }
        )
    )

    class _FileClockDiarizer:
        def __init__(self, *_args) -> None:
            pass

        async def diarize(self, _pipeline, _progress):
            return [
                {"start": 9.0, "end": 13.0, "speaker": "SPEAKER_00"},
                {"start": 49.0, "end": 54.0, "speaker": "SPEAKER_01"},
            ]

    async def _load_pipeline():
        return object()

    monkeypatch.setattr(meeting_processor, "DiarizationProcessor", _FileClockDiarizer)
    monkeypatch.setattr(meeting_processor.DiarizationModelLoader, "load_pipeline", staticmethod(_load_pipeline))

    async def progress_callback(_progress):
        return None

    transcript = await processor.diarize_only(progress_callback)

    assert [(seg["start"], seg["speaker"]) for seg in transcript["segments"]] == [
        (10.0, "SPEAKER_00"),
        (550.0, "SPEAKER_01"),
    ]
    saved = json.loads(processor.transcript_path.read_text())
    assert [seg["start"] for seg in saved["segments"]] == [10.0, 550.0]
