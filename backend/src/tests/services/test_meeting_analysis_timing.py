"""Tests for per-call and per-mode meeting analysis timing capture."""

from api.services.whisper_live_core.post_processing.meeting_analysis_timing import (
    AnalysisCallTiming,
    AnalysisTimingRecorder,
    describe_model_id,
    summarize_report_for_log,
)


def _call(mode: str, kind: str = "chunk", outcome: str = "ok") -> AnalysisCallTiming:
    return AnalysisCallTiming(
        mode=mode,
        kind=kind,
        model_id="test-model",
        max_tokens=100,
        estimated_input_tokens=10,
        queued_seconds=0.0,
        started_offset_seconds=0.0,
        duration_seconds=0.5,
        outcome=outcome,
    )


def test_report_counts_calls_per_mode_and_preserves_call_order():
    recorder = AnalysisTimingRecorder()
    recorder.begin_mode("summary")
    recorder.begin_mode("decisions")
    recorder.record_call(_call("summary"))
    recorder.record_call(_call("decisions"))
    recorder.record_call(_call("summary", kind="reduction"))
    recorder.end_mode("summary", "ok")
    recorder.end_mode("decisions", "error")

    report = recorder.build_report(concurrency_limit=3)

    assert report.concurrency_limit == 3
    assert [call.mode for call in report.calls] == ["summary", "decisions", "summary"]
    by_mode = {mode.mode: mode for mode in report.modes}
    assert by_mode["summary"].call_count == 2
    assert by_mode["summary"].outcome == "ok"
    assert by_mode["decisions"].call_count == 1
    assert by_mode["decisions"].outcome == "error"


def test_unfinished_mode_is_reported_as_error_not_dropped():
    recorder = AnalysisTimingRecorder()
    recorder.begin_mode("questions")

    report = recorder.build_report(concurrency_limit=1)

    assert [mode.mode for mode in report.modes] == ["questions"]
    assert report.modes[0].outcome == "error"


def test_begin_mode_keeps_the_first_start_offset():
    recorder = AnalysisTimingRecorder()
    recorder.begin_mode("summary")
    first = recorder.build_report(concurrency_limit=1).modes[0].started_offset_seconds
    recorder.begin_mode("summary")
    second = recorder.build_report(concurrency_limit=1).modes[0].started_offset_seconds

    assert first == second


def test_describe_model_id_never_raises_for_unknown_objects():
    class Unknown:
        model_name = "my-test-model"

    assert isinstance(describe_model_id(Unknown()), str)
    assert isinstance(describe_model_id(None), str)


def test_summary_line_lists_every_mode():
    recorder = AnalysisTimingRecorder()
    recorder.begin_mode("summary")
    recorder.end_mode("summary", "ok")

    line = summarize_report_for_log(recorder.build_report(concurrency_limit=2))

    assert "concurrency=2" in line
    assert "summary=" in line
