"""The transcript file reads exactly like the analysis window's Copy All and Export.

Rules mirrored from web-components/MeetingAssistant/src/lib/transcriptFormatting.ts and the Swift fallback in MeetingAnalysisWebWindowController.swift: consecutive lines from the same source and speaker form one turn with a [timestamp] Label header and four-space-indented lines, turns are separated by a blank line, a source wins over a speaker id for the label, and timestamps are [m:ss] under an hour and [h:mm:ss] after.
"""

from api.services.whisper_live_core.post_processing import meeting_transcript_markdown as md


def _line(start, text, source="Microphone", speaker=None):
    return {"start": start, "end": (start or 0) + 1, "text": text, "source": source, "speaker": speaker or source}


def test_timestamps_are_unpadded_minutes_under_an_hour_and_full_after():
    assert md.format_timestamp(0.4) == "[0:00]"
    assert md.format_timestamp(34.37) == "[0:34]"
    assert md.format_timestamp(192.4) == "[3:12]"
    assert md.format_timestamp(3599.4) == "[59:59]"
    assert md.format_timestamp(3599.5) == "[1:00:00]"
    assert md.format_timestamp(3725.0) == "[1:02:05]"


def test_timestamp_rounds_half_up_like_the_app_and_never_goes_negative():
    assert md.format_timestamp(2.5) == "[0:03]"
    assert md.format_timestamp(-4.0) == "[0:00]"


def test_a_missing_or_invalid_start_renders_as_zero():
    assert md.format_timestamp(None) == "[00:00]"
    assert md.format_timestamp(float("nan")) == "[00:00]"


def test_consecutive_lines_from_the_same_source_form_one_indented_turn():
    text = md.format_transcript_turns([
        _line(34.4, "Good morning."),
        _line(38.0, "Let's start."),
        _line(48.8, "Hi there.", source="System Audio"),
        _line(60.0, "Yes.", source="Microphone"),
    ])
    assert text == (
        "[0:34] Microphone\n    Good morning.\n    Let's start.\n\n"
        "[0:49] System Audio\n    Hi there.\n\n"
        "[1:00] Microphone\n    Yes."
    )


def test_every_non_microphone_track_is_labeled_system_audio():
    text = md.format_transcript_turns([_line(5.0, "From a browser.", source="Google Chrome Helper")])
    assert text == "[0:05] System Audio\n    From a browser."


def test_the_microphone_source_is_recognized_regardless_of_case():
    assert md.format_transcript_turns([_line(1.0, "Hi.", source="microphone")]).startswith("[0:01] Microphone")


def test_two_diarized_speakers_on_one_track_stay_separate_turns_with_the_same_label():
    text = md.format_transcript_turns([
        _line(1.0, "First.", source="System Audio", speaker="System Audio - Speaker 1"),
        _line(2.0, "Second.", source="System Audio", speaker="System Audio - Speaker 2"),
    ])
    assert text == "[0:01] System Audio\n    First.\n\n[0:02] System Audio\n    Second."


def test_a_line_with_no_source_falls_back_to_a_speaker_number():
    assert md.format_transcript_turns([{"start": 3.0, "text": "Hi.", "speaker": "speaker0"}]) == "[0:03] Speaker 1\n    Hi."
    assert md.format_transcript_turns([{"start": 3.0, "text": "Hi.", "speaker": "2"}]) == "[0:03] Speaker 2\n    Hi."


def test_a_line_with_no_source_and_no_usable_speaker_has_a_bare_timestamp_header():
    assert md.format_transcript_turns([{"start": 3.0, "text": "Hi.", "speaker": None}]) == "[0:03]\n    Hi."
    assert md.format_transcript_turns([{"start": 3.0, "text": "Hi.", "speaker": "0"}]) == "[0:03]\n    Hi."


def test_empty_and_whitespace_lines_are_dropped_and_do_not_split_a_turn():
    text = md.format_transcript_turns([
        _line(1.0, "One."),
        _line(2.0, "   "),
        _line(3.0, ""),
        _line(4.0, None),
        _line(5.0, "Two."),
    ])
    assert text == "[0:01] Microphone\n    One.\n    Two."


def test_lines_are_ordered_by_start_with_a_stable_sort_and_unstarted_lines_last():
    text = md.format_transcript_turns([
        _line(None, "Last."),
        _line(10.0, "Mic tie.", source="Microphone"),
        _line(10.0, "System tie.", source="System Audio"),
        _line(2.0, "First."),
    ])
    assert text == (
        "[0:02] Microphone\n    First.\n    Mic tie.\n\n"
        "[0:10] System Audio\n    System tie.\n\n"
        "[00:00] Microphone\n    Last."
    )


def test_special_characters_and_long_text_pass_through_unchanged():
    long_text = "word " * 4000
    special = "Costs $5 & <b>bold</b> | `code` # not a heading"
    text = md.format_transcript_turns([_line(1.0, special), _line(2.0, long_text)])
    assert f"    {special}" in text
    assert f"    {long_text.strip()}" in text


def test_the_file_has_a_title_a_start_time_the_label_note_and_the_turns():
    markdown = md.build_transcript_markdown(
        [_line(1.0, "Hi.")], meeting_name="Stand Up", started_at="2026-11-11T16:03:26Z"
    )
    assert markdown.startswith("# Stand Up - Transcript\n\n*Started: 2026-11-11T16:03:26Z*\n\n")
    assert md.LABEL_NOTE in markdown
    assert markdown.endswith("[0:01] Microphone\n    Hi.\n")


def test_the_file_defaults_the_title_and_omits_the_start_line_when_unknown():
    markdown = md.build_transcript_markdown([_line(1.0, "Hi.")], meeting_name="  ")
    assert markdown.startswith("# Meeting - Transcript\n\n" + md.LABEL_NOTE)
    assert "Started" not in markdown


def test_a_transcript_with_no_speech_produces_no_file_content():
    assert md.build_transcript_markdown([]) == ""
    assert md.build_transcript_markdown([_line(1.0, "  ")]) == ""


def test_writing_creates_the_file_then_skips_an_unchanged_rewrite(tmp_path):
    markdown = md.build_transcript_markdown([_line(1.0, "Hi.")])
    assert md.write_transcript_markdown(tmp_path, markdown) is True
    target = tmp_path / md.TRANSCRIPT_MARKDOWN_FILENAME
    assert target.read_text(encoding="utf-8") == markdown
    first_mtime = target.stat().st_mtime_ns
    assert md.write_transcript_markdown(tmp_path, markdown) is False
    assert target.stat().st_mtime_ns == first_mtime


def test_writing_replaces_changed_content_and_leaves_no_temporary_files(tmp_path):
    md.write_transcript_markdown(tmp_path, md.build_transcript_markdown([_line(1.0, "Old.")]))
    updated = md.build_transcript_markdown([_line(1.0, "New.")])
    assert md.write_transcript_markdown(tmp_path, updated) is True
    assert (tmp_path / md.TRANSCRIPT_MARKDOWN_FILENAME).read_text(encoding="utf-8") == updated
    assert [p.name for p in tmp_path.iterdir()] == [md.TRANSCRIPT_MARKDOWN_FILENAME]


def test_writing_empty_content_does_nothing(tmp_path):
    assert md.write_transcript_markdown(tmp_path, "") is False
    assert list(tmp_path.iterdir()) == []


def test_the_real_merge_output_renders_end_to_end():
    from api.services.whisper_live_core.post_processing.transcript_merger import merge_session_transcripts

    merged = merge_session_transcripts([
        {"source": "Microphone", "segments": [{"start": 34.4, "end": 40.0, "text": "Morning.", "speaker": None}], "start_offset_seconds": 0.0},
        {"source": "System Audio", "segments": [{"start": 23.8, "end": 30.0, "text": "Early.", "speaker": None}, {"start": 48.8, "end": 52.0, "text": "Reply.", "speaker": None}], "start_offset_seconds": 0.0},
    ])
    assert md.format_transcript_turns(merged["segments"]) == (
        "[0:24] System Audio\n    Early.\n\n"
        "[0:34] Microphone\n    Morning.\n\n"
        "[0:49] System Audio\n    Reply."
    )


def test_output_is_identical_to_the_web_bundle_formatter_on_the_parity_fixture():
    """Golden output captured by running formatTranscriptForCopy(buildTranscriptRows(...)) on the same lines, with displayStart built by the Swift elapsed-time rule. If transcriptFormatting.ts changes, this must change with it."""
    fixture = [
        (0.4, "Opening line.", "Microphone", "Microphone"),
        (2.5, "Same turn, rounds up.", "Microphone", "Microphone"),
        (34.37, "Remote reply.", "System Audio", "System Audio"),
        (40.0, "Remote continues.", "System Audio", "System Audio"),
        (41.0, "Second remote voice.", "System Audio", "System Audio - Speaker 1"),
        (192.4, "Back to me.", "Microphone", "Microphone"),
        (3599.4, "Just under an hour.", "System Audio", "System Audio"),
        (3599.5, "Exactly the hour.", "Microphone", "Microphone"),
        (3725.0, "Past the hour.", "System Audio", "System Audio"),
    ]
    rendered = md.format_transcript_turns(
        [{"start": s, "text": t, "source": src, "speaker": sp} for s, t, src, sp in fixture]
    )
    assert rendered == (
        "[0:00] Microphone\n    Opening line.\n    Same turn, rounds up.\n\n"
        "[0:34] System Audio\n    Remote reply.\n    Remote continues.\n\n"
        "[0:41] System Audio\n    Second remote voice.\n\n"
        "[3:12] Microphone\n    Back to me.\n\n"
        "[59:59] System Audio\n    Just under an hour.\n\n"
        "[1:00:00] Microphone\n    Exactly the hour.\n\n"
        "[1:02:05] System Audio\n    Past the hour."
    )
