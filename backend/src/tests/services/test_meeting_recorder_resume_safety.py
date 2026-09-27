"""
Tests for MeetingRecorder overwrite safety and resume timeline support.

These cover the safety net that prevents a reused meeting id from silently
destroying an existing recording, plus the resume continuation behavior that
keeps a resumed part's transcript on the logical meeting timeline.
"""
import json
from pathlib import Path

import pytest

from api.services.meetings.meeting_recorder import MeetingRecorder, MeetingMetadata
from api.services.whisper_live_core.post_processing.meeting_transcript_upgrade_ledger import (
    record_window_upgrade,
)


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Redirect Path.home() so recordings are written under a temp directory."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def _record_short_meeting(meeting_id: str, name: str = "Test Meeting") -> None:
    """Create a recording with real audio frames, then stop it."""
    recorder = MeetingRecorder(meeting_id=meeting_id)
    recorder.start_recording(name)
    # 1000 samples of 16-bit silence => real, non-empty audio content.
    recorder.write_audio_chunk(b"\x00\x01" * 1000)
    recorder.stop_recording()


def test_overwrite_guard_blocks_reused_id_with_existing_audio(isolated_home):
    """A reused meeting id must not truncate an existing non-empty recording."""
    _record_short_meeting("meeting-collision")

    audio_path = MeetingRecorder.get_meeting_directory("meeting-collision") / "audio.wav"
    size_before = audio_path.stat().st_size
    assert size_before > 44  # header + audio frames

    # Simulate stale client state reusing the same id.
    colliding = MeetingRecorder(meeting_id="meeting-collision")
    with pytest.raises(FileExistsError):
        colliding.start_recording("Accidental Overwrite")

    # The original audio is untouched.
    assert audio_path.stat().st_size == size_before


def test_empty_stub_recording_can_be_restarted(isolated_home):
    """An existing header-only (no frames) audio file is safe to replace."""
    recorder = MeetingRecorder(meeting_id="meeting-empty")
    recorder.start_recording("Empty Meeting")
    # No audio written.
    recorder.stop_recording()

    # Restarting with the same id is allowed because nothing real was captured.
    restarted = MeetingRecorder(meeting_id="meeting-empty")
    restarted.start_recording("Empty Meeting Retry")  # should not raise
    restarted.write_audio_chunk(b"\x00\x01" * 10)
    restarted.stop_recording()


def test_overwrite_guard_blocks_reused_id_with_existing_transcript(isolated_home):
    """A reused id must not clobber a meeting that has a persisted transcript.

    Covers the case the audio guard alone misses: a meeting carrying a real
    transcript with empty/zero-length audio (e.g. post-processed/imported).
    """
    meeting_dir = MeetingRecorder.get_meeting_directory("meeting-has-transcript")
    meeting_dir.mkdir(parents=True, exist_ok=True)
    (meeting_dir / "transcript.json").write_text(
        json.dumps({"segments": [{"start": 0.0, "end": 1.0, "text": "real content"}]})
    )

    colliding = MeetingRecorder(meeting_id="meeting-has-transcript")
    with pytest.raises(FileExistsError):
        colliding.start_recording("Accidental Overwrite")


def test_empty_transcript_does_not_block_restart(isolated_home):
    """A segment-less transcript.json does not block a fresh start (empty stub)."""
    meeting_dir = MeetingRecorder.get_meeting_directory("meeting-empty-transcript")
    meeting_dir.mkdir(parents=True, exist_ok=True)
    (meeting_dir / "transcript.json").write_text(json.dumps({"segments": []}))

    recorder = MeetingRecorder(meeting_id="meeting-empty-transcript")
    recorder.start_recording("Restartable")  # should not raise
    recorder.write_audio_chunk(b"\x00\x01" * 10)
    recorder.stop_recording()


def test_resume_offset_applied_to_transcript_segments(isolated_home):
    """Resumed parts store transcript segments on the logical meeting timeline."""
    recorder = MeetingRecorder(
        meeting_id="meeting-resume-part",
        timeline_offset_seconds=600.0,
        recording_part_index=1,
        resumed_from_meeting_id="meeting-original",
    )

    recorder.add_transcript_segment(start=1.0, end=2.0, text="resumed line")

    assert len(recorder.transcript_segments) == 1
    segment = recorder.transcript_segments[0]
    assert segment["start"] == pytest.approx(601.0)
    assert segment["end"] == pytest.approx(602.0)


def test_fresh_recording_has_no_offset(isolated_home):
    """A normal (non-resume) recording keeps original 0-based timestamps."""
    recorder = MeetingRecorder(meeting_id="meeting-fresh")

    recorder.add_transcript_segment(start=1.0, end=2.0, text="fresh line")

    segment = recorder.transcript_segments[0]
    assert segment["start"] == pytest.approx(1.0)
    assert segment["end"] == pytest.approx(2.0)


def test_recorder_finalization_replays_durable_window_upgrade(isolated_home):
    """The recorder's final raw write must not overwrite a live upgraded window."""
    recorder = MeetingRecorder(meeting_id="meeting-window-upgrade")
    recorder.start_recording("Window Upgrade")
    recorder.write_audio_chunk(b"\x00\x01" * 1000)
    recorder.add_transcript_segment(start=0.0, end=1.0, text="raw stream")
    record_window_upgrade(
        recorder.meeting_dir,
        0.0,
        1.0,
        [{"start": 0.0, "end": 1.0, "text": "improved stream", "speaker": None}],
    )

    recorder.stop_recording()

    data = json.loads(recorder.transcript_path.read_text())
    assert [segment["text"] for segment in data["segments"]] == ["improved stream"]


def test_reconnect_appends_audio_and_transcript_without_truncation(isolated_home):
    """An auto-reconnect (resume_existing=True) preserves the in-progress part.

    The same meeting id re-opening must append to the existing audio + transcript
    rather than raise the collision guard or truncate prior content.
    """
    # First connection: real audio + a persisted transcript segment. Chunk
    # sizes are chosen so the resulting audio.wav duration (at the recorder's
    # 16kHz sample rate) actually covers each segment's timestamp - the
    # persistence integrity guard now clamps segments to the real audio
    # duration, so an unrealistically short fixture would be (correctly)
    # rejected by that guard rather than exercising the reconnect behavior
    # this test is about.
    recorder = MeetingRecorder(meeting_id="meeting-reconnect")
    recorder.start_recording("Reconnect Meeting")
    recorder.write_audio_chunk(b"\x00\x01" * 20000)  # 20000 frames = 1.25s @ 16kHz
    recorder.add_transcript_segment(start=0.0, end=1.0, text="before drop")
    recorder.stop_recording()

    audio_path = MeetingRecorder.get_meeting_directory("meeting-reconnect") / "audio.wav"
    frames_before = 0
    import wave
    with wave.open(str(audio_path), "rb") as wav:
        frames_before = wav.getnframes()
    assert frames_before == 20000

    # Reconnect: new recorder, same id, resume_existing=True (must NOT raise).
    reconnected = MeetingRecorder(meeting_id="meeting-reconnect")
    reconnected.start_recording("Reconnect Meeting", resume_existing=True)

    # Prior transcript is carried into memory so the next save keeps it.
    assert any(s["text"] == "before drop" for s in reconnected.transcript_segments)
    # Frame counter resumes from the preserved frame count (no truncation).
    assert reconnected.frames_written == frames_before

    # Append more audio + a later segment, then stop.
    reconnected.write_audio_chunk(b"\x00\x01" * 40000)  # +40000 frames = +2.5s @ 16kHz
    reconnected.add_transcript_segment(start=2.0, end=3.0, text="after reconnect")
    reconnected.stop_recording()

    # Audio grew (old frames preserved + new appended).
    with wave.open(str(audio_path), "rb") as wav:
        assert wav.getnframes() == frames_before + 40000

    # Transcript retains both the pre-drop and post-reconnect segments.
    transcript_path = MeetingRecorder.get_meeting_directory("meeting-reconnect") / "transcript.json"
    data = json.loads(transcript_path.read_text())
    texts = [s["text"] for s in data["segments"]]
    assert "before drop" in texts
    assert "after reconnect" in texts


def test_native_stream_origins_preserve_discontinuous_reconnect_timestamps(isolated_home):
    recorder = MeetingRecorder(meeting_id="meeting-native-timing")
    recorder.start_recording("Native Timing")
    recorder.set_stream_timeline_origin_seconds(10.0)
    recorder.write_audio_chunk(b"\x00\x01" * 16000)
    recorder.add_transcript_segment(start=10.2, end=10.8, text="before reconnect")
    recorder.stop_recording()

    reconnected = MeetingRecorder(meeting_id="meeting-native-timing")
    reconnected.start_recording("Native Timing", resume_existing=True)
    reconnected.set_stream_timeline_origin_seconds(13.0)
    reconnected.write_audio_chunk(b"\x00\x01" * 16000)
    reconnected.add_transcript_segment(start=13.2, end=13.8, text="after reconnect")
    reconnected.stop_recording()

    metadata = MeetingRecorder.load_metadata("meeting-native-timing")
    assert metadata is not None
    assert metadata.stream_timeline_ranges == [
        {"start": 10.0, "end": 11.0},
        {"start": 13.0, "end": 14.0},
    ]
    transcript = json.loads(reconnected.transcript_path.read_text())
    assert [segment["text"] for segment in transcript["segments"]] == [
        "before reconnect",
        "after reconnect",
    ]


def test_reconnect_on_empty_meeting_starts_fresh(isolated_home):
    """resume_existing=True with no prior content behaves like a fresh start."""
    recorder = MeetingRecorder(meeting_id="meeting-reconnect-empty")
    # Nothing recorded yet; reconnect flag must not raise or misbehave.
    recorder.start_recording("Empty Reconnect", resume_existing=True)
    recorder.write_audio_chunk(b"\x00\x01" * 10)
    recorder.stop_recording()

    audio_path = MeetingRecorder.get_meeting_directory("meeting-reconnect-empty") / "audio.wav"
    import wave
    with wave.open(str(audio_path), "rb") as wav:
        assert wav.getnframes() == 10


def test_resume_metadata_persisted_and_legacy_metadata_loads(isolated_home):
    """New resume fields persist, and legacy metadata without them still loads."""
    # New recording persists resume fields.
    recorder = MeetingRecorder(
        meeting_id="meeting-with-resume-meta",
        timeline_offset_seconds=42.5,
        recording_part_index=2,
        resumed_from_meeting_id="origin-id",
    )
    recorder.start_recording("Resume Meta Meeting")
    recorder.stop_recording()

    loaded = MeetingRecorder.load_metadata("meeting-with-resume-meta")
    assert loaded is not None
    assert loaded.timeline_offset_seconds == pytest.approx(42.5)
    assert loaded.recording_part_index == 2
    assert loaded.resumed_from_meeting_id == "origin-id"

    # Legacy metadata (no resume fields) still loads with safe defaults.
    legacy_dir = MeetingRecorder.get_meeting_directory("legacy-meeting")
    legacy_dir.mkdir(parents=True, exist_ok=True)
    legacy_payload = {
        "id": "legacy-meeting",
        "name": "Legacy Meeting",
        "start_time": "2024-01-01T00:00:00Z",
        "session_id": "legacy-session",
        "audio_source": "Microphone",
    }
    (legacy_dir / "metadata.json").write_text(json.dumps(legacy_payload))

    legacy = MeetingRecorder.load_metadata("legacy-meeting")
    assert legacy is not None
    assert legacy.timeline_offset_seconds == 0.0
    assert legacy.recording_part_index == 0
    assert legacy.resumed_from_meeting_id is None
