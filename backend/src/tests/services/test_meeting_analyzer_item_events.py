"""Analyzer wiring: sink creation, progress message for streamed counts, executor hand-off."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.whisper_live_core.post_processing import (
    meeting_analyzer as analyzer_module,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_models import (
    AnalysisMode,
)
from api.services.whisper_live_core.post_processing.meeting_analyzer import (
    MeetingAnalyzer,
)

_ACTION = {"task": "A", "context": "ctx", "timestamp": 1, "speaker": "S"}


def _prepared(monkeypatch, tmp_path, analyze_mode):
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
async def test_streamed_items_become_events_and_a_found_so_far_progress_message(
    monkeypatch, tmp_path
):
    holder = {}

    async def analyze_mode(mode, _instructions, _prior, **_kwargs):
        await holder["analyzer"]._item_sink.emit_element(
            AnalysisMode.ACTION_ITEMS, json.dumps(_ACTION)
        )
        return []

    analyzer = _prepared(monkeypatch, tmp_path, analyze_mode)
    holder["analyzer"] = analyzer
    events = []
    messages = []

    async def event_callback(event):
        events.append(event)

    async def progress_callback(progress):
        messages.append(progress["message"])

    await analyzer.analyze(
        ["action_items"],
        progress_callback=progress_callback,
        event_callback=event_callback,
    )

    assert [event["type"] for event in events] == ["analysis_item"]
    assert "Analyzing action items: 1 found so far..." in messages


@pytest.mark.asyncio
async def test_run_without_any_listener_leaves_the_sink_disabled(monkeypatch, tmp_path):
    async def analyze_mode(mode, _instructions, _prior, **_kwargs):
        return []

    analyzer = _prepared(monkeypatch, tmp_path, analyze_mode)

    await analyzer.analyze(["action_items"])

    assert analyzer._item_sink.enabled is False


@pytest.mark.asyncio
async def test_progress_only_runs_enable_streaming_for_the_count_message(
    monkeypatch, tmp_path
):
    async def analyze_mode(mode, _instructions, _prior, **_kwargs):
        return []

    analyzer = _prepared(monkeypatch, tmp_path, analyze_mode)

    async def progress_callback(_progress):
        return None

    await analyzer.analyze(["action_items"], progress_callback=progress_callback)

    assert analyzer._item_sink.enabled is True


@pytest.mark.asyncio
async def test_analyze_mode_hands_the_sink_to_the_executor():
    analyzer = MeetingAnalyzer("meeting-1", "test-model")
    analyzer.model = AsyncMock()
    analyzer.transcript = {"segments": []}
    sentinel_sink = object()
    analyzer._item_sink = sentinel_sink
    executor = MagicMock()
    executor.analyze_mode = AsyncMock(return_value="summary")
    executor.safety_omissions = []
    executor.enforcement_modes = set()

    with patch.object(
        analyzer_module, "MeetingAnalysisExecutor", return_value=executor
    ) as factory:
        await analyzer._analyze_mode(AnalysisMode.SUMMARY, None)

    assert factory.call_args.kwargs["item_sink"] is sentinel_sink
