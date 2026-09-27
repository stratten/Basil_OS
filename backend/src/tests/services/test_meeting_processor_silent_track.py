import json
import wave
from pathlib import Path

import pytest

from api.services.meetings.meeting_recorder import MeetingRecorder
from api.services.whisper_live_core.post_processing import meeting_processor


def _write_silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16_000)
        writer.writeframes(b"\x00\x00" * 16_000)


class _EmptySegmentTranscriptionProcessor:
    def __init__(self, *_args) -> None:
        pass

    async def transcribe_with_selected_model(self, _progress_callback):
        return []


@pytest.fixture
def silent_track_processor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> meeting_processor.MeetingProcessor:
    _write_silent_wav(tmp_path / "audio.wav")
    monkeypatch.setattr(
        MeetingRecorder,
        "get_meeting_directory",
        staticmethod(lambda _meeting_id: tmp_path),
    )
    monkeypatch.setattr(
        MeetingRecorder,
        "load_metadata",
        staticmethod(lambda _meeting_id: None),
    )
    monkeypatch.setattr(
        meeting_processor,
        "TranscriptionProcessor",
        _EmptySegmentTranscriptionProcessor,
    )
    return meeting_processor.MeetingProcessor("silent-track", "whisper-1")


@pytest.mark.asyncio
async def test_silent_track_completes_with_empty_transcript(
    silent_track_processor: meeting_processor.MeetingProcessor,
) -> None:
    progress_messages = []

    async def progress_callback(progress):
        progress_messages.append(progress["message"])

    transcript = await silent_track_processor.transcribe_only(progress_callback)

    assert transcript == {"meeting_id": "silent-track", "segments": []}
    assert progress_messages[-1] == "No speech detected in this audio source."
    assert json.loads(silent_track_processor.transcript_path.read_text()) == transcript


@pytest.mark.asyncio
async def test_silent_track_preserves_existing_transcript(
    silent_track_processor: meeting_processor.MeetingProcessor,
) -> None:
    existing_transcript = {
        "meeting_id": "silent-track",
        "segments": [
            {"start": 0.0, "end": 1.0, "text": "Keep this text", "speaker": None}
        ],
    }
    silent_track_processor.transcript_path.write_text(json.dumps(existing_transcript))
    progress_messages = []

    async def progress_callback(progress):
        progress_messages.append(progress["message"])

    transcript = await silent_track_processor.transcribe_only(progress_callback)

    assert transcript == existing_transcript
    assert progress_messages[-1] == "No speech detected; existing transcript preserved."
    assert json.loads(silent_track_processor.transcript_path.read_text()) == existing_transcript
