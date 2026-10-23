"""Overall analysis progress is monotonic even when modes report concurrently."""

import asyncio

import pytest

from api.services.whisper_live_core.post_processing.meeting_analysis_concurrency import (
    CONCURRENCY_ENV_VAR,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_models import (
    AnalysisMode,
)
from api.services.whisper_live_core.post_processing.meeting_analyzer import (
    MeetingAnalyzer,
)


async def _send(analyzer, frames, completed, total=2):
    sent = []

    async def callback(progress):
        sent.append(progress)

    for stage, stage_progress in frames:
        await analyzer._send_progress(
            callback,
            stage=stage,
            stage_progress=stage_progress,
            completed_modes=completed,
            total_modes=total,
            message="m",
        )
    return [frame["overall_progress"] for frame in sent]


@pytest.mark.asyncio
async def test_a_later_mode_start_frame_never_lowers_the_bar():
    analyzer = MeetingAnalyzer("meeting-1", "test-model")

    values = await _send(
        analyzer,
        [
            ("analyzing_summary", 0.0),
            ("analyzing_summary", 0.6),
            ("analyzing_decisions", 0.0),
        ],
        completed=[],
    )

    assert values == sorted(values)
    assert values[1] == pytest.approx(0.3)
    assert values[2] == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_two_modes_in_flight_add_their_progress_together():
    analyzer = MeetingAnalyzer("meeting-1", "test-model")

    values = await _send(
        analyzer,
        [("analyzing_summary", 0.5), ("analyzing_decisions", 0.5)],
        completed=[],
    )

    assert values == [pytest.approx(0.25), pytest.approx(0.5)]


@pytest.mark.asyncio
async def test_completed_modes_count_once_and_failed_modes_advance_the_bar():
    analyzer = MeetingAnalyzer("meeting-1", "test-model")

    values = await _send(
        analyzer,
        [
            ("analyzing_summary", 0.4),
            ("analyzing_decisions", 1.0),
            ("analyzing_summary", 1.0),
        ],
        completed=["summary"],
    )

    assert values == sorted(values)
    assert values[-1] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_complete_stage_reports_exactly_one_and_loading_reports_zero():
    analyzer = MeetingAnalyzer("meeting-1", "test-model")

    values = await _send(
        analyzer,
        [("loading", 0.0), ("loading", 1.0), ("complete", 1.0)],
        completed=[],
    )

    assert values[0] == 0.0
    assert values[1] == 0.0
    assert values[2] == 1.0


@pytest.mark.asyncio
async def test_full_concurrent_run_emits_a_non_decreasing_bar(monkeypatch, tmp_path):
    monkeypatch.setenv(CONCURRENCY_ENV_VAR, "3")
    analyzer = MeetingAnalyzer("meeting-1", "test-model")
    analyzer.meeting_dir = tmp_path

    async def no_op():
        return None

    async def no_save(_result):
        return None

    async def analyze_mode(mode, _instructions, _prior, progress_callback=None, **kwargs):
        await asyncio.sleep(0.01 if mode == AnalysisMode.SUMMARY else 0.03)
        await analyzer._send_progress(
            progress_callback,
            stage=f"analyzing_{mode.value}",
            stage_progress=0.5,
            completed_modes=kwargs["completed_modes"],
            total_modes=kwargs["total_modes"],
            message="halfway",
            current_mode=mode.value,
        )
        await asyncio.sleep(0.01)
        return "summary" if mode == AnalysisMode.SUMMARY else []

    monkeypatch.setattr(analyzer, "_load_transcript", no_op)
    monkeypatch.setattr(analyzer, "_load_model", no_op)
    monkeypatch.setattr(analyzer, "_load_identity_and_capabilities", no_op)
    monkeypatch.setattr(analyzer, "_save_analysis", no_save)
    monkeypatch.setattr(analyzer, "_analyze_mode", analyze_mode)
    frames = []

    async def callback(progress):
        frames.append(progress["overall_progress"])

    await analyzer.analyze(["summary", "decisions", "questions"], progress_callback=callback)

    assert frames == sorted(frames)
    assert frames[-1] == 1.0
