"""Concurrent chunks, timing capture, progress, and suggested-actions narrowing."""

import asyncio
from types import SimpleNamespace

import pytest

from api.core.models.model_invocation import (
    StructuredModelOutputError,
    StructuredModelResponse,
)
from api.services.whisper_live_core.post_processing import (
    meeting_analysis_executor as executor_module,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_concurrency import (
    AnalysisCallLimiter,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_executor import (
    MeetingAnalysisExecutor,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_models import (
    ActionItem,
    AnalysisMode,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_prompts import (
    MeetingAnalysisPromptBuilder,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_timing import (
    AnalysisTimingRecorder,
)


def _model(context_window=20_000, max_output_tokens=8_192):
    return SimpleNamespace(
        model_name="unknown-test-model",
        max_context_length=context_window,
        max_output_tokens=max_output_tokens,
    )


def _metadata():
    return {"name": "Planning", "participants": ["A"], "duration": 100.0, "speaker_count": 1}


def _transcript(segment_count=4, words_per_segment=3_000):
    return {
        "segments": [
            {
                "start": index * 10,
                "end": index * 10 + 9,
                "speaker": "A",
                "text": f"segment-{index} " + " ".join(["word"] * words_per_segment),
            }
            for index in range(segment_count)
        ]
    }


def _action_payload(task):
    return {
        "items": [
            {"task": task, "context": "evidence", "timestamp": 1, "speaker": "A"}
        ]
    }


@pytest.mark.asyncio
async def test_chunk_calls_overlap_under_the_limiter_and_reduction_waits_for_all(monkeypatch):
    active = 0
    peak = 0
    finished_chunks = 0
    reduction_saw_finished_chunks = None
    reduction_prompt = None

    async def fake_call(_model, *, prompt, response_model, max_tokens):
        nonlocal active, peak, finished_chunks, reduction_saw_finished_chunks, reduction_prompt
        if "reconciling a complete meeting analysis" in prompt:
            reduction_saw_finished_chunks = finished_chunks
            reduction_prompt = prompt
            return StructuredModelResponse(
                value=response_model.model_validate(_action_payload("reduced")),
                enforcement="strict_json_fallback",
            )
        index = 1 if "chunk 1 of" in prompt else 2
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05 if index == 1 else 0.0)
        active -= 1
        finished_chunks += 1
        return StructuredModelResponse(
            value=response_model.model_validate(_action_payload(f"chunk-{index}-task")),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_call)
    executor = MeetingAnalysisExecutor(
        "meeting-1",
        MeetingAnalysisPromptBuilder(),
        call_limiter=AnalysisCallLimiter(3),
    )

    result = await executor.analyze_mode(
        mode=AnalysisMode.ACTION_ITEMS,
        transcript=_transcript(),
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=_model(),
    )

    assert result[0].task == "reduced"
    assert peak == 2
    assert reduction_saw_finished_chunks == 2
    assert reduction_prompt.index("chunk-1-task") < reduction_prompt.index("chunk-2-task")


@pytest.mark.asyncio
async def test_default_executor_serializes_chunk_calls(monkeypatch):
    active = 0
    peak = 0

    async def fake_call(_model, *, prompt, response_model, max_tokens):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return StructuredModelResponse(
            value=response_model.model_validate(_action_payload("task")),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_call)
    executor = MeetingAnalysisExecutor("meeting-1", MeetingAnalysisPromptBuilder())

    await executor.analyze_mode(
        mode=AnalysisMode.ACTION_ITEMS,
        transcript=_transcript(),
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=_model(),
    )

    assert peak == 1


@pytest.mark.asyncio
async def test_one_failing_chunk_cancels_its_siblings_and_propagates(monkeypatch):
    sibling_canceled = asyncio.Event()

    async def fake_call(_model, *, prompt, response_model, max_tokens):
        if "chunk 1 of" in prompt:
            await asyncio.sleep(0.01)
            raise StructuredModelOutputError("bad output", category="provider")
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            sibling_canceled.set()
            raise

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_call)
    executor = MeetingAnalysisExecutor(
        "meeting-1",
        MeetingAnalysisPromptBuilder(),
        call_limiter=AnalysisCallLimiter(3),
    )

    with pytest.raises(StructuredModelOutputError, match="bad output"):
        await executor.analyze_mode(
            mode=AnalysisMode.ACTION_ITEMS,
            transcript=_transcript(),
            meeting_metadata=_metadata(),
            custom_instructions=None,
            prior_results={},
            model=_model(),
        )

    assert sibling_canceled.is_set()


@pytest.mark.asyncio
async def test_timing_recorder_captures_chunk_reduction_usage_and_errors(monkeypatch):
    async def fake_call(_model, *, prompt, response_model, max_tokens):
        if "reconciling a complete meeting analysis" in prompt:
            return StructuredModelResponse(
                value=response_model.model_validate(_action_payload("reduced")),
                enforcement="strict_json_fallback",
                finish_reason="stop",
                usage={"input_tokens": 10, "cached_tokens": 4},
            )
        return StructuredModelResponse(
            value=response_model.model_validate(_action_payload("chunk")),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_call)
    recorder = AnalysisTimingRecorder()
    executor = MeetingAnalysisExecutor(
        "meeting-1",
        MeetingAnalysisPromptBuilder(),
        timing_recorder=recorder,
        call_limiter=AnalysisCallLimiter(3),
    )

    await executor.analyze_mode(
        mode=AnalysisMode.ACTION_ITEMS,
        transcript=_transcript(),
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=_model(),
    )

    calls = recorder.build_report(concurrency_limit=3).calls
    kinds = sorted(call.kind for call in calls)
    assert kinds == ["chunk", "chunk", "reduction"]
    reduction = next(call for call in calls if call.kind == "reduction")
    assert reduction.provider_usage == {"input_tokens": 10, "cached_tokens": 4}
    assert reduction.finish_reason == "stop"
    assert reduction.outcome == "ok"
    assert all(call.estimated_input_tokens > 0 for call in calls)
    assert all(call.estimated_output_tokens for call in calls)
    assert {call.chunk_total for call in calls if call.kind == "chunk"} == {2}


@pytest.mark.asyncio
async def test_failed_and_retried_calls_are_recorded_with_attempt_numbers(monkeypatch):
    attempts = {"count": 0}

    async def fake_call(_model, *, prompt, response_model, max_tokens):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise StructuredModelOutputError(
                "temporary", category="transient", retryable=True
            )
        return StructuredModelResponse(
            value=response_model.model_validate(_action_payload("ok")),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_call)
    recorder = AnalysisTimingRecorder()
    executor = MeetingAnalysisExecutor(
        "meeting-1", MeetingAnalysisPromptBuilder(), timing_recorder=recorder
    )

    await executor.analyze_mode(
        mode=AnalysisMode.ACTION_ITEMS,
        transcript=_transcript(segment_count=1, words_per_segment=10),
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=_model(),
    )

    calls = recorder.build_report(concurrency_limit=1).calls
    assert [(call.attempt, call.outcome) for call in calls] == [(1, "error"), (2, "ok")]
    assert calls[0].error_category == "transient"


@pytest.mark.asyncio
async def test_a_broken_recorder_never_breaks_the_analysis(monkeypatch):
    async def fake_call(_model, *, prompt, response_model, max_tokens):
        return StructuredModelResponse(
            value=response_model.model_validate(_action_payload("ok")),
            enforcement="strict_json_fallback",
        )

    class BrokenRecorder:
        def offset(self):
            return 0.0

        def record_call(self, _timing):
            raise RuntimeError("recorder bug")

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_call)
    executor = MeetingAnalysisExecutor(
        "meeting-1", MeetingAnalysisPromptBuilder(), timing_recorder=BrokenRecorder()
    )

    result = await executor.analyze_mode(
        mode=AnalysisMode.ACTION_ITEMS,
        transcript=_transcript(segment_count=1, words_per_segment=10),
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=_model(),
    )

    assert result[0].task == "ok"


@pytest.mark.asyncio
async def test_chunk_progress_counts_completed_chunks_monotonically(monkeypatch):
    async def fake_call(_model, *, prompt, response_model, max_tokens):
        return StructuredModelResponse(
            value=response_model.model_validate(_action_payload("ok")),
            enforcement="strict_json_fallback",
        )

    updates = []

    async def progress(update):
        updates.append(update)

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_call)
    executor = MeetingAnalysisExecutor(
        "meeting-1", MeetingAnalysisPromptBuilder(), call_limiter=AnalysisCallLimiter(3)
    )

    await executor.analyze_mode(
        mode=AnalysisMode.ACTION_ITEMS,
        transcript=_transcript(),
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=_model(),
        progress_callback=progress,
    )

    chunk_updates = [
        u["stage_progress"]
        for u in updates
        if "chunk" in u["message"] and " of " in u["message"]
    ]
    assert chunk_updates == sorted(chunk_updates)
    assert len(chunk_updates) == 2
    assert updates[-1]["stage_progress"] == 1.0


@pytest.mark.asyncio
async def test_suggested_actions_prompt_contains_only_cited_windows_for_long_meetings(monkeypatch):
    prompts = []

    async def fake_call(_model, *, prompt, response_model, max_tokens):
        prompts.append(prompt)
        return StructuredModelResponse(
            value=response_model.model_validate({"items": []}),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_call)
    executor = MeetingAnalysisExecutor("meeting-1", MeetingAnalysisPromptBuilder())
    action_item = ActionItem(
        task="send budget", context="evidence", timestamp=100.0, speaker="A"
    )

    await executor.analyze_mode(
        mode=AnalysisMode.SUGGESTED_ACTIONS,
        transcript=_transcript(segment_count=400, words_per_segment=40),
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={AnalysisMode.ACTION_ITEMS.value: [action_item]},
        model=_model(context_window=1_000_000),
    )

    assert len(prompts) == 1
    assert "segment-10 " in prompts[0]
    assert "segment-300 " not in prompts[0]


@pytest.mark.asyncio
async def test_suggested_actions_without_citations_sends_the_full_transcript(monkeypatch):
    prompts = []

    async def fake_call(_model, *, prompt, response_model, max_tokens):
        prompts.append(prompt)
        return StructuredModelResponse(
            value=response_model.model_validate({"items": []}),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_call)
    executor = MeetingAnalysisExecutor("meeting-1", MeetingAnalysisPromptBuilder())

    await executor.analyze_mode(
        mode=AnalysisMode.SUGGESTED_ACTIONS,
        transcript=_transcript(segment_count=400, words_per_segment=40),
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=_model(context_window=1_000_000),
    )

    assert "segment-10 " in prompts[0]
    assert "segment-300 " in prompts[0]


@pytest.mark.asyncio
async def test_narrowed_run_still_validates_timestamps_against_the_full_transcript(monkeypatch):
    async def fake_call(_model, *, prompt, response_model, max_tokens):
        return StructuredModelResponse(
            value=response_model.model_validate(
                {
                    "items": [
                        {
                            "source_task": "t",
                            "suggested_agent_task": "t",
                            "why_basil_can_help": "w",
                            "source_timestamp": 999999.0,
                            "disposition": "todo_candidate",
                        }
                    ]
                }
            ),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_call)
    executor = MeetingAnalysisExecutor("meeting-1", MeetingAnalysisPromptBuilder())
    action_item = ActionItem(
        task="send budget", context="evidence", timestamp=100.0, speaker="A"
    )

    with pytest.raises(RuntimeError, match="outside the transcript range"):
        await executor.analyze_mode(
            mode=AnalysisMode.SUGGESTED_ACTIONS,
            transcript=_transcript(segment_count=400, words_per_segment=40),
            meeting_metadata=_metadata(),
            custom_instructions=None,
            prior_results={AnalysisMode.ACTION_ITEMS.value: [action_item]},
            model=_model(context_window=1_000_000),
        )
