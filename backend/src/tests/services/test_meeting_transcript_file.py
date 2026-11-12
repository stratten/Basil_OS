"""The transcript file is rebuilt from the recordings on disk, on the analysis window's timeline rules.

Fixtures are fake meeting folders in a temp directory: one folder per recording track, linked by session_id, each with metadata.json and transcript.json.
"""

import json
from pathlib import Path

from api.services.whisper_live_core.post_processing import meeting_transcript_file as tf
from api.services.whisper_live_core.post_processing.meeting_transcript_markdown import (
    LABEL_NOTE,
    TRANSCRIPT_MARKDOWN_FILENAME,
)


def _make(root: Path, folder, *, session="S1", source="Microphone", start="2026-11-11T16:03:26.000000Z", part=0, name=None, segments=None, write_transcript=True, extra=None):
    directory = root / folder
    directory.mkdir()
    metadata = {
        "id": folder,
        "name": name if name is not None else f"Stand Up - {source}",
        "session_id": session,
        "audio_source": source,
        "start_time": start,
        "recording_part_index": part,
        "timeline_offset_seconds": 0.0,
    }
    if session is None:
        metadata.pop("session_id")
    metadata.update(extra or {})
    (directory / "metadata.json").write_text(json.dumps(metadata))
    if write_transcript:
        (directory / "transcript.json").write_text(json.dumps({"meeting_id": folder, "segments": segments or []}))
    return directory


def _seg(start, text, speaker=None):
    return {"start": start, "end": start + 1.0, "text": text, "speaker": speaker}


def _read(directory: Path) -> str:
    return (directory / TRANSCRIPT_MARKDOWN_FILENAME).read_text(encoding="utf-8")


def test_two_tracks_are_interleaved_into_one_file_in_the_microphone_folder(tmp_path):
    mic = _make(tmp_path, "mic", segments=[_seg(34.4, "Morning."), _seg(60.0, "Yes.")])
    system = _make(tmp_path, "sys", source="System Audio", segments=[_seg(23.8, "Early."), _seg(48.8, "Reply.")])

    path = tf.ensure_meeting_transcript_markdown(system)

    assert path == mic / TRANSCRIPT_MARKDOWN_FILENAME
    assert not (system / TRANSCRIPT_MARKDOWN_FILENAME).exists()
    text = _read(mic)
    assert text.startswith("# Stand Up - Transcript\n\n*Started: 2026-11-11T16:03:26.000000Z*\n\n" + LABEL_NOTE)
    assert text.endswith(
        "[0:24] System Audio\n    Early.\n\n"
        "[0:34] Microphone\n    Morning.\n\n"
        "[0:49] System Audio\n    Reply.\n\n"
        "[1:00] Microphone\n    Yes.\n"
    )


def test_the_result_is_the_same_whichever_member_folder_is_asked_about(tmp_path):
    mic = _make(tmp_path, "mic", segments=[_seg(5.0, "One.")])
    system = _make(tmp_path, "sys", source="System Audio", segments=[_seg(9.0, "Two.")])
    assert tf.ensure_meeting_transcript_markdown(mic) == tf.ensure_meeting_transcript_markdown(system)


def test_a_late_starting_track_is_shifted_onto_the_shared_timeline(tmp_path):
    """The system tap opened 1.5 s after the microphone: a system line at raw 0.5 s belongs after a mic line at raw 1.0 s."""
    mic = _make(tmp_path, "mic", start="2026-11-11T16:00:00.000000Z", segments=[_seg(1.0, "Mic first.")])
    _make(tmp_path, "sys", source="System Audio", start="2026-11-11T16:00:01.500000Z", segments=[_seg(0.5, "System later.")])
    tf.ensure_meeting_transcript_markdown(mic)
    assert _read(mic).endswith("[0:01] Microphone\n    Mic first.\n\n[0:02] System Audio\n    System later.\n")


def test_a_resumed_part_is_not_shifted_by_the_wall_clock_gap_between_parts(tmp_path):
    """Part 1 started twenty minutes after part 0, but its segment times already carry the resume offset, so only same-part skew applies."""
    mic0 = _make(tmp_path, "mic0", start="2026-11-11T16:00:00.000000Z", segments=[_seg(10.0, "Part zero.")])
    _make(tmp_path, "sys0", source="System Audio", start="2026-11-11T16:00:00.000000Z", segments=[_seg(300.0, "Remote zero.")])
    _make(tmp_path, "mic1", part=1, start="2026-11-11T16:20:00.000000Z", segments=[_seg(700.0, "Part one.")], extra={"timeline_offset_seconds": 690.0})
    _make(tmp_path, "sys1", source="System Audio", part=1, start="2026-11-11T16:20:02.000000Z", segments=[_seg(701.0, "Remote one.")])
    tf.ensure_meeting_transcript_markdown(mic0)
    body = _read(mic0)
    assert "[0:10] Microphone\n    Part zero." in body
    assert "[11:40] Microphone\n    Part one." in body
    assert "[11:43] System Audio\n    Remote one." in body


def test_a_tie_keeps_the_microphone_line_first(tmp_path):
    mic = _make(tmp_path, "mic", segments=[_seg(10.0, "Mic tie.")])
    _make(tmp_path, "sys", source="System Audio", segments=[_seg(10.0, "System tie.")])
    tf.ensure_meeting_transcript_markdown(mic)
    assert _read(mic).endswith("[0:10] Microphone\n    Mic tie.\n\n[0:10] System Audio\n    System tie.\n")


def test_a_standalone_meeting_gets_its_own_file_and_defaults_to_the_microphone_label(tmp_path):
    only = _make(tmp_path, "solo", session=None, source=None, name="Dictation", segments=[_seg(3.0, "Hello.")], extra={"audio_source": None})
    path = tf.ensure_meeting_transcript_markdown(only)
    assert path == only / TRANSCRIPT_MARKDOWN_FILENAME
    assert _read(only).startswith("# Dictation - Transcript")
    assert _read(only).endswith("[0:03] Microphone\n    Hello.\n")


def test_a_lone_system_audio_recording_keeps_its_true_label(tmp_path):
    only = _make(tmp_path, "sys-only", session="S2", source="System Audio", segments=[_seg(3.0, "From the speakers.")])
    tf.ensure_meeting_transcript_markdown(only)
    assert _read(only).endswith("[0:03] System Audio\n    From the speakers.\n")


def test_other_calls_in_the_same_folder_are_not_mixed_in(tmp_path):
    mic = _make(tmp_path, "mic", session="A", segments=[_seg(1.0, "Call A.")])
    _make(tmp_path, "other", session="B", segments=[_seg(2.0, "Call B.")])
    tf.ensure_meeting_transcript_markdown(mic)
    assert "Call B." not in _read(mic)


def test_the_name_loses_the_per_track_suffix(tmp_path):
    mic = _make(tmp_path, "mic", name="Weekly Sync - Microphone", segments=[_seg(1.0, "Hi.")])
    tf.ensure_meeting_transcript_markdown(mic)
    assert _read(mic).startswith("# Weekly Sync - Transcript")


def test_a_track_with_no_transcript_or_an_empty_one_is_skipped(tmp_path):
    mic = _make(tmp_path, "mic", segments=[_seg(1.0, "Only me.")])
    _make(tmp_path, "sys", source="System Audio", write_transcript=False)
    _make(tmp_path, "sys2", source="System Audio", segments=[])
    tf.ensure_meeting_transcript_markdown(mic)
    assert _read(mic).endswith("[0:01] Microphone\n    Only me.\n")


def test_a_corrupt_transcript_file_is_skipped_not_fatal(tmp_path):
    mic = _make(tmp_path, "mic", segments=[_seg(1.0, "Fine.")])
    broken = _make(tmp_path, "sys", source="System Audio", write_transcript=False)
    (broken / "transcript.json").write_text("{not json")
    tf.ensure_meeting_transcript_markdown(mic)
    assert _read(mic).endswith("[0:01] Microphone\n    Fine.\n")


def test_a_call_with_no_speech_writes_nothing_and_returns_none(tmp_path):
    mic = _make(tmp_path, "mic", segments=[_seg(1.0, "   ")])
    assert tf.ensure_meeting_transcript_markdown(mic) is None
    assert not (mic / TRANSCRIPT_MARKDOWN_FILENAME).exists()


def test_a_folder_without_metadata_returns_none(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    assert tf.ensure_meeting_transcript_markdown(bare) is None
    assert tf.ensure_meeting_transcript_markdown(tmp_path / "missing") is None


def test_the_file_follows_the_transcripts_when_they_change_and_stays_put_when_they_do_not(tmp_path):
    mic = _make(tmp_path, "mic", segments=[_seg(1.0, "Draft wording.")])
    tf.ensure_meeting_transcript_markdown(mic)
    target = mic / TRANSCRIPT_MARKDOWN_FILENAME
    first_mtime = target.stat().st_mtime_ns

    tf.ensure_meeting_transcript_markdown(mic)
    assert target.stat().st_mtime_ns == first_mtime

    (mic / "transcript.json").write_text(json.dumps({"segments": [_seg(1.0, "Final wording.")]}))
    tf.ensure_meeting_transcript_markdown(mic)
    assert "Final wording." in _read(mic)
    assert "Draft wording." not in _read(mic)


def test_a_second_track_arriving_later_is_added_to_the_existing_file(tmp_path):
    mic = _make(tmp_path, "mic", segments=[_seg(1.0, "Mic only so far.")])
    tf.ensure_meeting_transcript_markdown(mic)
    assert "System Audio" not in _read(mic).split(LABEL_NOTE)[1]
    _make(tmp_path, "sys", source="System Audio", segments=[_seg(5.0, "Remote now.")])
    tf.ensure_meeting_transcript_markdown(mic)
    assert "[0:05] System Audio\n    Remote now." in _read(mic)


def test_every_line_survives_special_characters_and_long_text(tmp_path):
    long_text = "word " * 4000
    special = "Costs $5 & <b>bold</b> | `code` # not a heading"
    mic = _make(tmp_path, "mic", segments=[_seg(1.0, special), _seg(2.0, long_text)])
    tf.ensure_meeting_transcript_markdown(mic)
    body = _read(mic)
    assert f"    {special}" in body
    assert f"    {long_text.strip()}" in body


def test_the_async_wrapper_returns_the_same_path(tmp_path):
    import asyncio

    mic = _make(tmp_path, "mic", segments=[_seg(1.0, "Hi.")])
    assert asyncio.run(tf.ensure_meeting_transcript_markdown_async(mic)) == mic / TRANSCRIPT_MARKDOWN_FILENAME


def test_the_path_lookup_by_meeting_id_creates_the_file_and_never_raises(tmp_path, monkeypatch):
    mic = _make(tmp_path, "mic-id", segments=[_seg(1.0, "Hi.")])
    monkeypatch.setattr(
        "api.services.meetings.meeting_recorder.MeetingRecorder.get_meeting_directory",
        staticmethod(lambda meeting_id: tmp_path / meeting_id),
    )
    assert tf.meeting_transcript_markdown_path("mic-id") == str(mic / TRANSCRIPT_MARKDOWN_FILENAME)
    assert tf.meeting_transcript_markdown_path("no-such-meeting") is None


def test_stopping_a_recording_writes_the_file_then_kicks_the_memory_scheduler(tmp_path, monkeypatch):
    import asyncio

    mic = _make(tmp_path, "mic-id", segments=[_seg(1.0, "Hi.")])
    kicks = []

    class _Scheduler:
        def kick(self):
            kicks.append(True)

    monkeypatch.setattr(
        "api.services.meetings.meeting_recorder.MeetingRecorder.get_meeting_directory",
        staticmethod(lambda meeting_id: tmp_path / meeting_id),
    )
    monkeypatch.setattr("api.services.zettel.scheduler.get_zettel_scheduler", lambda: _Scheduler())
    asyncio.run(tf.refresh_after_recording_stopped("mic-id"))
    assert (mic / TRANSCRIPT_MARKDOWN_FILENAME).exists()
    assert kicks == [True]


def test_a_failing_file_write_still_kicks_the_scheduler_and_never_raises(tmp_path, monkeypatch):
    import asyncio

    kicks = []

    class _Scheduler:
        def kick(self):
            kicks.append(True)

    def explode(_directory):
        raise OSError("disk full")

    monkeypatch.setattr(tf, "ensure_meeting_transcript_markdown", explode)
    monkeypatch.setattr("api.services.zettel.scheduler.get_zettel_scheduler", lambda: _Scheduler())
    asyncio.run(tf.refresh_after_recording_stopped("anything"))
    assert kicks == [True]


def test_a_failing_scheduler_never_breaks_recording_teardown(tmp_path, monkeypatch):
    import asyncio

    def explode():
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr("api.services.zettel.scheduler.get_zettel_scheduler", explode)
    asyncio.run(tf.refresh_after_recording_stopped("anything"))
