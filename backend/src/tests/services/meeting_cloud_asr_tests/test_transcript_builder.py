import importlib.util
from datetime import timedelta
from pathlib import Path

from api.services.meeting_cloud_asr.models import EVENT_FINAL, EVENT_INTERIM, AsrEvent
from api.services.meeting_cloud_asr.transcript_builder import CloudTranscriptBuilder, format_clock
from api.services.live_transcription.stream_clock import StreamClock


def build(base_sample: int = 0, clock: StreamClock | None = None):
    segments = []
    mapper = (clock.timeline_seconds_for_sample if clock is not None else (lambda sample: None))
    builder = CloudTranscriptBuilder(base_sample=base_sample, timeline_for_sample=mapper, add_segment=lambda **kw: segments.append(kw))
    return builder, segments


def final(text: str, start: float, end: float, utterance_end: bool = False) -> AsrEvent:
    return AsrEvent(EVENT_FINAL, text, start, end, utterance_end)


def test_interim_text_is_the_buffer_and_a_final_replaces_it_with_a_committed_segment() -> None:
    builder, segments = build()
    assert builder.apply(AsrEvent(EVENT_INTERIM, "hello wor", 0.0, 1.0)) is True
    assert builder.apply(AsrEvent(EVENT_INTERIM, "hello wor", 0.0, 1.0)) is False
    assert builder.front_data()["buffer_transcription"] == "hello wor"
    assert builder.front_data()["status"] == "active_transcription"
    assert builder.apply(final("hello world", 0.0, 1.5)) is True
    frame = builder.front_data()
    assert frame["buffer_transcription"] == ""
    assert [line["text"] for line in frame["lines"]] == ["hello world"]
    assert segments == [{"start": 0.0, "end": 1.5, "text": "hello world", "speaker": 1, "is_interim": False}]


def test_finals_extend_one_line_until_an_utterance_end_then_a_new_line_starts() -> None:
    builder, segments = build()
    builder.apply(final("first part", 0.0, 1.0))
    builder.apply(final("second part", 1.0, 2.0, utterance_end=True))
    builder.apply(final("next thought", 3.0, 4.0))
    lines = builder.front_data()["lines"]
    assert [(line["text"], line["line_complete"]) for line in lines] == [("first part second part", True), ("next thought", False)]
    assert [segment["text"] for segment in segments] == ["first part", "second part", "next thought"]
    assert lines[0]["end"] == "0:00:02" and lines[1]["start"] == "0:00:03"
    assert builder.front_data()["line_complete"] is False


def test_an_empty_final_with_utterance_end_only_closes_the_open_line() -> None:
    builder, segments = build()
    builder.apply(final("open line", 0.0, 1.0))
    assert builder.apply(final("", 1.0, 1.0, utterance_end=True)) is True
    assert builder.front_data()["line_complete"] is True
    assert len(segments) == 1
    assert builder.apply(final("", 1.0, 1.0, utterance_end=True)) is False


def test_times_use_the_client_clock_anchors_and_never_run_backwards() -> None:
    clock = StreamClock(16000)
    clock.add_anchor(16000, 10.0)
    builder, segments = build(base_sample=16000, clock=clock)
    builder.apply(final("anchored", 0.0, 2.0))
    builder.apply(final("overlapping", 1.0, 1.5))
    assert segments[0]["start"] == 10.0 and segments[0]["end"] == 12.0
    assert segments[1]["start"] >= segments[0]["end"] and segments[1]["end"] >= segments[1]["start"]


def test_without_clock_anchors_times_fall_back_to_session_seconds_including_the_base() -> None:
    builder, segments = build(base_sample=16000 * 30)
    builder.apply(final("late start", 2.0, 3.0))
    assert (segments[0]["start"], segments[0]["end"]) == (32.0, 33.0)
    assert builder.front_data()["lines"][0]["start"] == "0:00:32"


def test_format_clock_matches_the_local_engine_format() -> None:
    for seconds in (0.0, 5.9, 61.0, 3725.4):
        assert format_clock(seconds) == str(timedelta(seconds=int(seconds)))
    assert format_clock(-3.0) == "0:00:00"


def load_local_engine_types():
    path = Path(__file__).resolve().parents[3] / "api" / "services" / "whisper_live_core" / "timed_objects.py"
    spec = importlib.util.spec_from_file_location("timed_objects_standalone", path)
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules["timed_objects_standalone"] = module
    spec.loader.exec_module(module)
    return module


def test_frames_carry_exactly_the_keys_the_local_engine_sends() -> None:
    types = load_local_engine_types()
    line = types.Line(start=1.0, end=2.0, text="hi", speaker=1, timeline_start_seconds=1.0, timeline_end_seconds=2.0)
    local = types.FrontData(status="active_transcription", lines=[line]).to_dict()
    builder, _ = build()
    builder.apply(final("hi", 1.0, 2.0))
    cloud = builder.front_data()
    assert set(cloud) == set(local)
    assert set(cloud["lines"][0]) == set(local["lines"][0])
    assert cloud["lines"][0]["start"] == local["lines"][0]["start"]
