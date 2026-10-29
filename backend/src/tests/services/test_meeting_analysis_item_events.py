"""Sink validation, resets, the To-Do candidate hook, and executor streaming wiring."""

import asyncio
import json

import pytest

from api.core.models.model_invocation import (
    StructuredModelOutputError,
    StructuredModelResponse,
)
from api.services.whisper_live_core.post_processing import (
    meeting_analysis_executor as executor_module,
)
from api.services.whisper_live_core.post_processing import (
    meeting_analysis_events as events_module,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_concurrency import (
    AnalysisCallLimiter,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_events import (
    AnalysisItemSink,
    subscribe_todo_candidates,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_executor import (
    MeetingAnalysisExecutor,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_models import (
    AnalysisMode,
    SuggestedActionDraft,
    build_action_proposals,
)
from api.services.whisper_live_core.post_processing.meeting_analysis_prompts import (
    MeetingAnalysisPromptBuilder,
)

_ACTION_A = {"task": "A", "context": "ctx", "timestamp": 1, "speaker": "S"}
_ACTION_B = {"task": "B", "context": "ctx", "timestamp": 2, "speaker": "S"}
_DRAFT = {
    "source_task": "Send budget",
    "suggested_agent_task": "Draft the budget email",
    "why_basil_can_help": "Drafting",
    "source_action_item_indexes": [0],
    "disposition": "todo_candidate",
}


class _Model:
    model_name = "unknown-test-model"
    max_context_length = 1_000_000
    max_output_tokens = 8192


def _metadata():
    return {"name": "Planning", "participants": ["A"], "duration": 100.0, "speaker_count": 1}


def _transcript(segment_count=3, words=10):
    return {
        "segments": [
            {
                "start": index * 10,
                "end": index * 10 + 9,
                "speaker": "A",
                "text": f"segment-{index} " + " ".join(["word"] * words),
            }
            for index in range(segment_count)
        ]
    }


def _collector():
    events = []

    async def callback(event):
        events.append(event)

    return events, callback


@pytest.fixture(autouse=True)
def _clean_subscribers():
    events_module._todo_candidate_subscribers.clear()
    yield
    events_module._todo_candidate_subscribers.clear()


@pytest.mark.asyncio
async def test_sink_publishes_validated_items_with_increasing_sequence():
    events, callback = _collector()
    sink = AnalysisItemSink(meeting_id="m", event_callback=callback)

    await sink.emit_element(AnalysisMode.ACTION_ITEMS, json.dumps(_ACTION_A))
    await sink.emit_element(AnalysisMode.ACTION_ITEMS, json.dumps(_ACTION_B))

    assert [(event["type"], event["sequence"]) for event in events] == [
        ("analysis_item", 0),
        ("analysis_item", 1),
    ]
    assert events[0]["provisional"] is True
    assert events[0]["item"]["task"] == "A"
    assert events[0]["mode"] == "action_items"


@pytest.mark.asyncio
async def test_invalid_elements_and_item_less_modes_are_skipped():
    events, callback = _collector()
    sink = AnalysisItemSink(meeting_id="m", event_callback=callback)

    await sink.emit_element(AnalysisMode.ACTION_ITEMS, json.dumps({**_ACTION_A, "extra": 1}))
    await sink.emit_element(AnalysisMode.ACTION_ITEMS, "{not json")
    await sink.emit_element(AnalysisMode.SUMMARY, json.dumps(_ACTION_A))

    assert events == []


@pytest.mark.asyncio
async def test_reset_is_only_emitted_when_items_were_published():
    events, callback = _collector()
    sink = AnalysisItemSink(meeting_id="m", event_callback=callback)

    await sink.reset(AnalysisMode.ACTION_ITEMS)
    await sink.emit_element(AnalysisMode.ACTION_ITEMS, json.dumps(_ACTION_A))
    await sink.reset(AnalysisMode.ACTION_ITEMS)
    await sink.emit_element(AnalysisMode.ACTION_ITEMS, json.dumps(_ACTION_B))

    assert [event["type"] for event in events] == [
        "analysis_item",
        "analysis_items_reset",
        "analysis_item",
    ]
    assert events[-1]["sequence"] == 0


@pytest.mark.asyncio
async def test_a_failing_event_callback_never_raises_into_the_analysis():
    async def broken(_event):
        raise RuntimeError("socket closed")

    sink = AnalysisItemSink(meeting_id="m", event_callback=broken)

    await sink.emit_element(AnalysisMode.ACTION_ITEMS, json.dumps(_ACTION_A))


def test_sink_is_enabled_only_when_someone_listens():
    async def callback(_event):
        return None

    assert AnalysisItemSink(meeting_id="m").enabled is False
    assert AnalysisItemSink(meeting_id="m", event_callback=callback).enabled is True
    unsubscribe = subscribe_todo_candidates(callback)
    assert AnalysisItemSink(meeting_id="m").enabled is True
    unsubscribe()
    assert AnalysisItemSink(meeting_id="m").enabled is False


@pytest.mark.asyncio
async def test_todo_candidate_event_carries_the_same_stable_id_as_the_final_proposal():
    events, callback = _collector()
    received = []

    async def subscriber(event):
        received.append(event)

    subscribe_todo_candidates(subscriber)
    sink = AnalysisItemSink(meeting_id="meeting-9", event_callback=callback)

    await sink.emit_element(AnalysisMode.SUGGESTED_ACTIONS, json.dumps(_DRAFT))

    candidate_events = [event for event in events if event["type"] == "todo_candidate_streamed"]
    final = build_action_proposals(
        [SuggestedActionDraft.model_validate(_DRAFT)], meeting_id="meeting-9"
    )
    assert len(candidate_events) == 1
    assert candidate_events[0]["stable_id"] == final[0].id
    assert candidate_events[0]["candidate"]["suggested_agent_task"] == "Draft the budget email"
    assert candidate_events[0]["provisional"] is True
    assert received == candidate_events


@pytest.mark.asyncio
async def test_non_candidate_dispositions_and_failing_subscribers_are_harmless():
    events, callback = _collector()

    async def broken_subscriber(_event):
        raise RuntimeError("subscriber bug")

    subscribe_todo_candidates(broken_subscriber)
    sink = AnalysisItemSink(meeting_id="meeting-9", event_callback=callback)

    await sink.emit_element(
        AnalysisMode.SUGGESTED_ACTIONS,
        json.dumps({**_DRAFT, "disposition": "non_actionable"}),
    )
    await sink.emit_element(AnalysisMode.SUGGESTED_ACTIONS, json.dumps(_DRAFT))

    types = [event["type"] for event in events]
    assert types.count("analysis_item") == 2
    assert types.count("todo_candidate_streamed") == 1


@pytest.mark.asyncio
async def test_count_callback_reports_running_counts():
    counts = []

    async def count_callback(mode, count):
        counts.append((mode, count))

    sink = AnalysisItemSink(meeting_id="m", count_callback=count_callback)

    await sink.emit_element(AnalysisMode.ACTION_ITEMS, json.dumps(_ACTION_A))
    await sink.emit_element(AnalysisMode.ACTION_ITEMS, json.dumps(_ACTION_B))

    assert counts == [("action_items", 1), ("action_items", 2)]


def _streaming_fake(pieces_per_attempt, after_each=None, fail_after=None):
    attempts = {"count": 0}

    async def fake_call(_model, *, prompt, response_model, max_tokens, on_text_delta=None):
        attempt = attempts["count"]
        attempts["count"] += 1
        pieces = pieces_per_attempt[min(attempt, len(pieces_per_attempt) - 1)]
        if on_text_delta is not None:
            for piece in pieces:
                await on_text_delta(piece)
                if after_each is not None:
                    after_each(attempt)
        if fail_after is not None and attempt in fail_after:
            raise fail_after[attempt]
        payload = json.loads("".join(pieces))
        return StructuredModelResponse(
            value=response_model.model_validate(payload),
            enforcement="strict_json_fallback",
        )

    return fake_call


def _executor(sink):
    return MeetingAnalysisExecutor(
        "meeting-1",
        MeetingAnalysisPromptBuilder(),
        call_limiter=AnalysisCallLimiter(3),
        item_sink=sink,
    )


async def _run(executor, mode=AnalysisMode.ACTION_ITEMS, transcript=None, model=None):
    return await executor.analyze_mode(
        mode=mode,
        transcript=transcript or _transcript(),
        meeting_metadata=_metadata(),
        custom_instructions=None,
        prior_results={},
        model=model or _Model(),
    )


@pytest.mark.asyncio
async def test_items_reach_the_consumer_before_the_call_returns(monkeypatch):
    events, callback = _collector()
    text = json.dumps({"items": [_ACTION_A, _ACTION_B]})
    split = text.index('"task": "B"')
    seen_counts = []
    fake = _streaming_fake(
        [[text[:split], text[split:]]],
        after_each=lambda _attempt: seen_counts.append(len(events)),
    )
    monkeypatch.setattr(executor_module, "call_model_with_schema", fake)

    result = await _run(_executor(AnalysisItemSink(meeting_id="m", event_callback=callback)))

    assert seen_counts == [1, 2]
    assert [item.task for item in result] == ["A", "B"]
    assert [event["item"]["task"] for event in events] == ["A", "B"]


@pytest.mark.asyncio
async def test_streamed_items_equal_the_final_result(monkeypatch):
    events, callback = _collector()
    text = json.dumps({"items": [_ACTION_A, _ACTION_B]})
    monkeypatch.setattr(
        executor_module, "call_model_with_schema", _streaming_fake([[text]])
    )

    result = await _run(_executor(AnalysisItemSink(meeting_id="m", event_callback=callback)))

    assert [event["item"] for event in events] == [
        item.model_dump(mode="json") for item in result
    ]


@pytest.mark.asyncio
async def test_a_retry_resets_the_provisional_items_of_the_abandoned_attempt(monkeypatch):
    events, callback = _collector()
    first = json.dumps({"items": [_ACTION_A]})
    second = json.dumps({"items": [_ACTION_A, _ACTION_B]})
    fake = _streaming_fake(
        [[first], [second]],
        fail_after={
            0: StructuredModelOutputError("temporary", category="transient", retryable=True)
        },
    )
    monkeypatch.setattr(executor_module, "call_model_with_schema", fake)

    result = await _run(_executor(AnalysisItemSink(meeting_id="m", event_callback=callback)))

    assert [event["type"] for event in events] == [
        "analysis_item",
        "analysis_items_reset",
        "analysis_item",
        "analysis_item",
    ]
    assert [item.task for item in result] == ["A", "B"]


@pytest.mark.asyncio
async def test_a_terminal_failure_resets_the_provisional_items(monkeypatch):
    events, callback = _collector()
    text = json.dumps({"items": [_ACTION_A]})
    fake = _streaming_fake(
        [[text]],
        fail_after={0: StructuredModelOutputError("bad", category="provider")},
    )
    monkeypatch.setattr(executor_module, "call_model_with_schema", fake)

    with pytest.raises(StructuredModelOutputError):
        await _run(_executor(AnalysisItemSink(meeting_id="m", event_callback=callback)))

    assert [event["type"] for event in events] == ["analysis_item", "analysis_items_reset"]


@pytest.mark.asyncio
async def test_chunked_modes_never_receive_a_streaming_callback(monkeypatch):
    events, callback = _collector()

    async def fake_call(_model, *, prompt, response_model, max_tokens):
        return StructuredModelResponse(
            value=response_model.model_validate({"items": [_ACTION_A]}),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_call)
    model = _Model()
    model.max_context_length = 20_000

    await _run(
        _executor(AnalysisItemSink(meeting_id="m", event_callback=callback)),
        transcript=_transcript(segment_count=4, words=3000),
        model=model,
    )

    assert events == []


@pytest.mark.asyncio
async def test_unobserved_runs_use_the_unchanged_blocking_call(monkeypatch):
    async def fake_call(_model, *, prompt, response_model, max_tokens):
        return StructuredModelResponse(
            value=response_model.model_validate({"items": [_ACTION_A]}),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_call)

    result = await _run(_executor(AnalysisItemSink(meeting_id="m")))

    assert [item.task for item in result] == ["A"]


@pytest.mark.asyncio
async def test_item_less_modes_never_stream_even_when_observed(monkeypatch):
    events, callback = _collector()

    async def fake_call(_model, *, prompt, response_model, max_tokens):
        return StructuredModelResponse(
            value=response_model.model_validate({"markdown": "summary"}),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_call)

    result = await _run(
        _executor(AnalysisItemSink(meeting_id="m", event_callback=callback)),
        mode=AnalysisMode.SUMMARY,
    )

    assert result == "summary"
    assert events == []


@pytest.mark.asyncio
async def test_invalid_streamed_elements_are_skipped_but_final_result_is_authoritative(
    monkeypatch,
):
    events, callback = _collector()
    text = json.dumps({"items": [_ACTION_A, _ACTION_B]})

    async def fake_call(_model, *, prompt, response_model, max_tokens, on_text_delta=None):
        await on_text_delta('{"items": [{"task": "bad", "extra": 1}, ')
        await on_text_delta(text[text.index('{"task": "B"'):])
        return StructuredModelResponse(
            value=response_model.model_validate({"items": [_ACTION_A, _ACTION_B]}),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_call)

    result = await _run(_executor(AnalysisItemSink(meeting_id="m", event_callback=callback)))

    assert [event["item"]["task"] for event in events] == ["B"]
    assert [item.task for item in result] == ["A", "B"]


@pytest.mark.asyncio
async def test_concurrent_modes_keep_independent_sequences(monkeypatch):
    events, callback = _collector()
    sink = AnalysisItemSink(meeting_id="m", event_callback=callback)
    text_actions = json.dumps({"items": [_ACTION_A, _ACTION_B]})
    text_decisions = json.dumps(
        {
            "items": [
                {"decision": "D", "context": "c", "timestamp": 3},
            ]
        }
    )

    async def fake_call(_model, *, prompt, response_model, max_tokens, on_text_delta=None):
        is_actions = "extracting actionable tasks" in prompt
        text = text_actions if is_actions else text_decisions
        for index in range(0, len(text), 9):
            await on_text_delta(text[index : index + 9])
            await asyncio.sleep(0)
        return StructuredModelResponse(
            value=response_model.model_validate(json.loads(text)),
            enforcement="strict_json_fallback",
        )

    monkeypatch.setattr(executor_module, "call_model_with_schema", fake_call)

    await asyncio.gather(
        _run(_executor(sink), mode=AnalysisMode.ACTION_ITEMS),
        _run(_executor(sink), mode=AnalysisMode.DECISIONS),
    )

    by_mode = {}
    for event in events:
        by_mode.setdefault(event["mode"], []).append(event["sequence"])
    assert by_mode == {"action_items": [0, 1], "decisions": [0]}
