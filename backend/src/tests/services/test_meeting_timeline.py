"""Tests for the meeting-clock <-> compacted-file mapping."""

import math

from api.services.whisper_live_core.post_processing.meeting_timeline import MeetingTimeline

# The microphone ranges from the 11:03 meeting: a first connection, two zero-length reconnect attempts, then the connection that resumed after the device switch.
MIC_RANGES = [
    {"start": 0.9, "end": 194.39},
    {"start": 191.86, "end": 191.86},
    {"start": 204.70, "end": 204.70},
    {"start": 598.0, "end": 2151.664},
]


def test_zero_length_ranges_are_skipped_and_pieces_are_contiguous_in_file_time():
    timeline = MeetingTimeline.from_ranges(MIC_RANGES)
    assert not timeline.is_legacy
    assert len(timeline.pieces) == 2
    first, second = timeline.pieces
    assert first.file_start == 0.0
    assert math.isclose(first.file_end, 193.49)
    assert math.isclose(second.file_start, first.file_end)
    assert math.isclose(second.meeting_start, 598.0)


def test_file_time_after_the_gap_maps_forward_to_the_recording_clock():
    timeline = MeetingTimeline.from_ranges(MIC_RANGES)
    assert math.isclose(timeline.file_to_meeting(100.0), 100.9)
    assert math.isclose(timeline.file_to_meeting(193.49 + 10.0), 608.0)


def test_window_before_the_gap_maps_to_one_file_run():
    timeline = MeetingTimeline.from_ranges(MIC_RANGES)
    runs = timeline.meeting_to_file_pieces(0.0, 120.0)
    assert len(runs) == 1
    file_start, file_end, meeting_start = runs[0]
    assert math.isclose(file_start, 0.0, abs_tol=1e-9)
    assert math.isclose(meeting_start, 0.9)
    assert math.isclose(file_end - file_start, 119.1)


def test_window_inside_the_gap_has_no_audio():
    timeline = MeetingTimeline.from_ranges(MIC_RANGES)
    assert timeline.meeting_to_file_pieces(240.0, 360.0) == []


def test_window_spanning_the_gap_yields_a_run_per_piece():
    timeline = MeetingTimeline.from_ranges(MIC_RANGES)
    runs = timeline.meeting_to_file_pieces(120.0, 720.0)
    assert len(runs) == 2
    assert math.isclose(runs[0][2], 120.0)
    assert math.isclose(runs[0][1], 193.49)
    assert math.isclose(runs[1][0], 193.49)
    assert math.isclose(runs[1][2], 598.0)
    assert math.isclose(runs[1][1] - runs[1][0], 122.0)


def test_round_trip_window_to_file_to_meeting():
    timeline = MeetingTimeline.from_ranges(MIC_RANGES)
    for file_start, file_end, meeting_start in timeline.meeting_to_file_pieces(600.0, 660.0):
        assert math.isclose(timeline.file_to_meeting(file_start), meeting_start)
        assert math.isclose(timeline.file_to_meeting(file_end - 1e-3), 660.0 - 1e-3, abs_tol=1e-3)


def test_segments_after_the_gap_are_retimed_and_segments_before_are_shifted_by_the_origin():
    timeline = MeetingTimeline.from_ranges(MIC_RANGES)
    mapped = timeline.map_file_segments(
        [
            {"start": 10.0, "end": 12.0, "text": "early", "speaker": None},
            {"start": 200.0, "end": 203.0, "text": "late", "speaker": "Me"},
        ]
    )
    assert math.isclose(mapped[0]["start"], 10.9)
    assert math.isclose(mapped[0]["end"], 12.9)
    assert math.isclose(mapped[1]["start"], 598.0 + (200.0 - 193.49))
    assert math.isclose(mapped[1]["end"], 598.0 + (203.0 - 193.49))
    assert mapped[1]["text"] == "late" and mapped[1]["speaker"] == "Me"


def test_segment_spanning_the_gap_is_ended_where_its_start_piece_ends():
    timeline = MeetingTimeline.from_ranges(MIC_RANGES)
    mapped = timeline.map_file_segments([{"start": 190.0, "end": 197.0, "text": "bridge"}])
    assert math.isclose(mapped[0]["start"], 190.9)
    assert math.isclose(mapped[0]["end"], 194.39)


def test_input_segments_are_not_mutated():
    timeline = MeetingTimeline.from_ranges(MIC_RANGES)
    source = {"start": 200.0, "end": 203.0, "text": "late"}
    timeline.map_file_segments([source])
    assert source == {"start": 200.0, "end": 203.0, "text": "late"}


def test_segments_without_numeric_times_pass_through_unchanged():
    timeline = MeetingTimeline.from_ranges(MIC_RANGES)
    assert timeline.map_file_segments([{"text": "no times"}]) == [{"text": "no times"}]


def test_live_timeline_treats_the_final_range_as_open_ended_even_when_its_stored_end_is_stale():
    stale = [
        {"start": 0.0, "end": 60.0},
        {"start": 90.0, "end": 90.0},
    ]
    timeline = MeetingTimeline.from_ranges(stale, live=True)
    assert len(timeline.pieces) == 2
    runs = timeline.meeting_to_file_pieces(120.0, 180.0)
    assert len(runs) == 1
    assert math.isclose(runs[0][0], 60.0 + 30.0)
    assert math.isclose(runs[0][1], 60.0 + 90.0)
    assert math.isclose(runs[0][2], 120.0)


def test_closed_timeline_does_not_extend_the_final_stale_range():
    stale = [
        {"start": 0.0, "end": 60.0},
        {"start": 90.0, "end": 90.0},
    ]
    timeline = MeetingTimeline.from_ranges(stale, live=False)
    assert timeline.meeting_to_file_pieces(120.0, 180.0) == []


def test_missing_or_malformed_ranges_fall_back_to_a_legacy_offset_timeline():
    for ranges in (None, [], [{"start": "a", "end": 2}], ["x"], [{"start": 5.0, "end": 5.0}]):
        timeline = MeetingTimeline.from_ranges(ranges, legacy_offset_seconds=30.0)
        assert timeline.is_legacy
        assert math.isclose(timeline.file_to_meeting(10.0), 40.0)
        runs = timeline.meeting_to_file_pieces(40.0, 70.0)
        assert len(runs) == 1
        assert math.isclose(runs[0][0], 10.0) and math.isclose(runs[0][1], 40.0)


def test_legacy_timeline_with_no_offset_is_the_identity():
    timeline = MeetingTimeline.from_ranges(None)
    assert timeline.is_legacy
    assert timeline.file_to_meeting(123.4) == 123.4
    runs = timeline.meeting_to_file_pieces(10.0, 20.0)
    assert runs == [(10.0, 20.0, 10.0)]
