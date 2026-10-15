"""Mode-level scheduling: dependency graph, isolation, ordering, cancellation, fallback."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.core.models.model_types import ModelCapability
from api.services.whisper_live_core.post_processing import (
    meeting_analyzer as analyzer_module,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_concurrency import (
    CONCURRENCY_ENV_VAR,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_models import (
    ActionItem,
    AnalysisMode,
)
from api.services.whisper_live_core.post_processing.meeting_analyzer import (
    MeetingAnalyzer,
)


def _analyzer(monkeypatch, tmp_path, analyze_mode):
    monkeypatch.setenv(CONCURRENCY_ENV_VAR, "3")
    analyzer = MeetingAnalyzer("meeting-1", "test-model")
    analyzer.meeting_dir = tmp_path

    async def no_op():
        return None

    async def no_save(_result):
        return None

    monkeypatch.setattr(analyzer, "_load_transcript", no_op)
    monkeypatch.setattr(analyzer, "_load_model", no_op)
    monkeypatch.setattr(analyzer, "_load_identity_and_capabilities", no_op)
    monkeypatch.setattr(analyzer, "_save_analysis", no_save)
    monkeypatch.setattr(analyzer, "_analyze_mode", analyze_mode)
    return analyzer


@pytest.mark.asyncio
async def test_independent_modes_overlap_and_dependent_mode_waits(monkeypatch, tmp_path):
    started = []
    finished = []
    active = 0
    peak = 0
    seen_prior = {}

    async def analyze_mode(mode, _instructions, prior, **_kwargs):
        nonlocal active, peak
        started.append(mode.value)
        active += 1
        peak = max(peak, active)
        if mode == AnalysisMode.SUGGESTED_ACTIONS:
            seen_prior["action_items"] = prior.get("action_items")
        await asyncio.sleep(0.05 if mode == AnalysisMode.ACTION_ITEMS else 0.01)
        active -= 1
        finished.append(mode.value)
        if mode == AnalysisMode.ACTION_ITEMS:
            return [
                ActionItem(task="send budget", context="evidence", timestamp=1.0)
            ]
        return "summary" if mode == AnalysisMode.SUMMARY else []

    analyzer = _analyzer(monkeypatch, tmp_path, analyze_mode)

    result = await analyzer.analyze(
        [
            AnalysisMode.SUGGESTED_ACTIONS.value,
            AnalysisMode.SUMMARY.value,
            AnalysisMode.ACTION_ITEMS.value,
            AnalysisMode.DECISIONS.value,
        ]
    )

    assert peak >= 3
    assert started.index("suggested_actions") > finished.index("action_items")
    assert [item.task for item in seen_prior["action_items"]] == ["send budget"]
    assert result.failed_modes == []


@pytest.mark.asyncio
async def test_dependent_mode_still_runs_when_its_dependency_fails(monkeypatch, tmp_path):
    seen_prior = {}

    async def analyze_mode(mode, _instructions, prior, **_kwargs):
        if mode == AnalysisMode.ACTION_ITEMS:
            raise RuntimeError("action items failed")
        if mode == AnalysisMode.SUGGESTED_ACTIONS:
            seen_prior.update(prior)
        return []

    analyzer = _analyzer(monkeypatch, tmp_path, analyze_mode)

    result = await analyzer.analyze(
        [AnalysisMode.ACTION_ITEMS.value, AnalysisMode.SUGGESTED_ACTIONS.value]
    )

    assert "action_items" not in seen_prior
    assert [failure.mode for failure in result.failed_modes] == ["action_items"]
    assert "suggested_actions" in result.requested_modes


@pytest.mark.asyncio
async def test_results_and_failures_follow_requested_order_not_completion_order(
    monkeypatch, tmp_path
):
    async def analyze_mode(mode, _instructions, _prior, **_kwargs):
        delays = {"summary": 0.06, "decisions": 0.0, "questions": 0.03, "sentiment": 0.01}
        await asyncio.sleep(delays[mode.value])
        if mode == AnalysisMode.SENTIMENT:
            raise RuntimeError("sentiment failed")
        if mode == AnalysisMode.QUESTIONS:
            raise RuntimeError("questions failed")
        return "summary" if mode == AnalysisMode.SUMMARY else []

    analyzer = _analyzer(monkeypatch, tmp_path, analyze_mode)
    requested = ["summary", "decisions", "questions", "sentiment"]

    result = await analyzer.analyze(requested)

    assert result.requested_modes == requested
    assert result.modes_analyzed == ["summary", "decisions"]
    assert [failure.mode for failure in result.failed_modes] == ["questions", "sentiment"]


@pytest.mark.asyncio
async def test_failed_mode_does_not_cancel_siblings(monkeypatch, tmp_path):
    async def analyze_mode(mode, _instructions, _prior, **_kwargs):
        if mode == AnalysisMode.DECISIONS:
            raise RuntimeError("decisions failed")
        await asyncio.sleep(0.03)
        return "summary"

    analyzer = _analyzer(monkeypatch, tmp_path, analyze_mode)

    result = await analyzer.analyze(["decisions", "summary"])

    assert result.summary == "summary"
    assert [failure.mode for failure in result.failed_modes] == ["decisions"]


@pytest.mark.asyncio
async def test_canceling_the_run_cancels_every_pending_mode(monkeypatch, tmp_path):
    canceled = []
    entered = asyncio.Event()

    async def analyze_mode(mode, _instructions, _prior, **_kwargs):
        entered.set()
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            canceled.append(mode.value)
            raise

    analyzer = _analyzer(monkeypatch, tmp_path, analyze_mode)
    run = asyncio.ensure_future(analyzer.analyze(["summary", "decisions"]))
    await entered.wait()
    await asyncio.sleep(0.01)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run

    assert sorted(canceled) == ["decisions", "summary"]


@pytest.mark.asyncio
async def test_saved_result_carries_timings_for_each_mode(monkeypatch, tmp_path):
    async def analyze_mode(mode, _instructions, _prior, **_kwargs):
        return "summary" if mode == AnalysisMode.SUMMARY else []

    analyzer = _analyzer(monkeypatch, tmp_path, analyze_mode)

    result = await analyzer.analyze(["summary", "decisions"])

    assert result.timings is not None
    assert result.timings.concurrency_limit == 3
    assert {mode.mode for mode in result.timings.modes} == {"summary", "decisions"}
    assert all(mode.outcome == "ok" for mode in result.timings.modes)
    assert result.to_dict()["timings"]["concurrency_limit"] == 3


@pytest.mark.asyncio
async def test_concurrent_unreachable_failures_switch_to_the_fallback_exactly_once():
    primary = AsyncMock()
    fallback = AsyncMock()
    fallback.model_name = "local-fallback-model"
    used_models = []

    analyzer = MeetingAnalyzer("meeting-1", "test-model")
    analyzer.model = primary
    analyzer.transcript = {"segments": []}
    analyzer._active_call_limiter().set_limit(3)

    executor = MagicMock()
    executor.safety_omissions = []
    executor.enforcement_modes = set()

    async def fake_executor_call(*, model, mode, **_kwargs):
        used_models.append((mode.value, model))
        await asyncio.sleep(0.01)
        if model is primary:
            raise ConnectionError("nodename nor servname provided, or not known")
        return f"{mode.value}-from-fallback"

    executor.analyze_mode = AsyncMock(side_effect=fake_executor_call)
    usage_service = MagicMock()
    usage_service.get_designated_local_fallback_model = AsyncMock(return_value=fallback)

    with patch.object(
        analyzer_module, "MeetingAnalysisExecutor", return_value=executor
    ), patch.object(
        analyzer_module, "ModelUsageService", return_value=usage_service
    ), patch.object(
        analyzer_module, "get_model_service", return_value=MagicMock()
    ):
        results = await asyncio.gather(
            analyzer._analyze_mode(AnalysisMode.SUMMARY, None),
            analyzer._analyze_mode(AnalysisMode.DECISIONS, None),
        )

    assert sorted(results) == ["decisions-from-fallback", "summary-from-fallback"]
    usage_service.get_designated_local_fallback_model.assert_awaited_once_with(
        {ModelCapability.REASONING}
    )
    assert analyzer.model is fallback
    assert analyzer.fallback_model_used == "local-fallback-model"
    assert analyzer._call_limiter.limit == 1
    assert [model for _mode, model in used_models[2:]] == [fallback, fallback]
