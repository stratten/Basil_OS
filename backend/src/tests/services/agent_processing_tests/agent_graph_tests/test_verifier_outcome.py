"""The outcome verifier judges the delivered response against the request, shows its reasoning, is bounded, and always resolves."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

import pytest

from api.core.models.reasoning.streaming_contract import StreamEvent, terminal_from_provider_reason
from api.services.agent_processing.lifecycle.execution_graph import async_finalizer
from api.services.agent_processing.lifecycle.finalization import evaluation as evaluation_module
from api.services.agent_processing.lifecycle.finalization.evaluation import (
    MAX_STEPS_METADATA_CHARS,
    VERIFIER_THINKING_ITERATION,
    build_evaluation_prompt,
    evaluate_finalizer_with_llm,
    format_steps_metadata,
)
from api.services.agent_processing.lifecycle.finalization.task_state_persistence import (
    normalize_thinking_history,
)

REQUEST = "Run sed -n 2p on the notes file and tell me the second line."
GARBAGE_RESPONSE = "I'm ready to help, but I don't see a request yet. Could you please provide the specific request?"
AGENT_ANSWER = "The second line of notes.txt is: Buy oat milk."

MISMATCH_VERDICT = json.dumps(
    {
        "outcome": "failure",
        "success": False,
        "failure_basis": "content_mismatch",
        "user_reason": "The response asked for the request again instead of answering it.",
        "technical_reason": "Delivered response does not address the request.",
        "should_retry": True,
    }
)


def _prompt(**overrides: Any) -> str:
    kwargs: Dict[str, Any] = dict(
        original_prompt=REQUEST,
        self_assessment=None,
        full_agent_output=GARBAGE_RESPONSE,
        max_output_chars=20000,
        steps=[],
        tool_error_history=None,
        evaluation_context=None,
        agent_final_answer=AGENT_ANSWER,
    )
    kwargs.update(overrides)
    return build_evaluation_prompt(**kwargs)


def test_prompt_contains_request_delivered_response_and_agent_answer():
    prompt = _prompt()
    assert REQUEST in prompt
    assert GARBAGE_RESPONSE in prompt
    assert AGENT_ANSWER in prompt
    assert "THE DELIVERED RESPONSE" in prompt


def test_prompt_checks_the_delivered_response_before_the_ground_truth_rule():
    prompt = _prompt()
    assert "FIRST CHECK" in prompt
    assert prompt.index("FIRST CHECK") < prompt.index("TOOL OUTPUT IS GROUND TRUTH")
    assert "content_mismatch" in prompt[prompt.index("FIRST CHECK") : prompt.index("TOOL OUTPUT IS GROUND TRUTH")]


def test_prompt_omits_agent_answer_block_when_absent():
    prompt = _prompt(agent_final_answer=None)
    assert "THE AGENT'S OWN FINAL ANSWER" not in prompt.split("YOUR ROLE AS FINALIZER")[0]


def test_steps_metadata_is_bounded_for_huge_traces():
    steps = [
        {"service": "file_service", "method": "read_file", "success": True, "result": "x" * 50000}
        for _ in range(500)
    ]
    summary = format_steps_metadata(steps)
    assert len(summary) <= MAX_STEPS_METADATA_CHARS + 200
    assert "more step(s) omitted" in summary
    assert "x" * 1000 not in summary


def test_steps_metadata_handles_empty_and_non_dict_steps():
    assert format_steps_metadata([]) == "(No steps recorded)"
    assert "odd step" in format_steps_metadata(["odd step"])  # type: ignore[list-item]


def test_prompt_size_does_not_grow_with_tool_payloads():
    small = _prompt(steps=[{"service": "a", "method": "b", "success": True, "result": "ok"}])
    huge = _prompt(steps=[{"service": "a", "method": "b", "success": True, "result": "y" * 200000}])
    assert len(huge) - len(small) < 1000


class _StreamingVerifier:
    def __init__(self, chunks: List[str]):
        self.chunks = chunks
        self.prompts: List[str] = []

    async def generate_response(self, prompt: str, max_tokens: int = 1024) -> str:
        raise AssertionError("the streaming path must be used when a reasoning sink is supplied")

    async def stream_chat_completion(self, messages, budget):
        self.prompts.append(messages[0]["content"])
        for chunk in self.chunks:
            yield StreamEvent(text=chunk)
        yield StreamEvent(terminal=terminal_from_provider_reason("completed"))


@pytest.mark.asyncio
async def test_garbage_response_is_judged_content_mismatch_and_reasoning_is_streamed():
    thought = "The user asked for line 2 of a file. The delivered response asks for the request again. That does not answer it. " * 2
    model = _StreamingVerifier(["<think>", thought[:60], thought[60:], "</think>", MISMATCH_VERDICT])
    seen: List[tuple] = []

    async def sink(text: str, complete: bool) -> None:
        seen.append((text, complete))

    result = await evaluate_finalizer_with_llm(
        llm_model=model,
        original_prompt=REQUEST,
        self_assessment=None,
        full_agent_output=GARBAGE_RESPONSE,
        steps=[],
        tool_error_history=None,
        evaluation_context=None,
        agent_final_answer=AGENT_ANSWER,
        on_reasoning=sink,
    )

    assert result is not None
    assert result.outcome == "failure"
    assert result.failure_basis == "content_mismatch"
    assert result.should_retry is True
    assert GARBAGE_RESPONSE in model.prompts[0] and REQUEST in model.prompts[0]
    assert seen, "verifier reasoning must reach the UI"
    assert seen[-1][1] is True
    assert "delivered response asks for the request again" in seen[-1][0]
    assert all(complete is False for _, complete in seen[:-1])


@pytest.mark.asyncio
async def test_hung_streaming_verifier_times_out_and_closes_its_reasoning():
    class _Hung:
        async def generate_response(self, prompt: str, max_tokens: int = 1024) -> str:
            return ""

        async def stream_chat_completion(self, messages, budget):
            yield StreamEvent(text="<think>" + "still thinking " * 20)
            await asyncio.sleep(3600)
            yield StreamEvent(text="never")

    seen: List[tuple] = []

    async def sink(text: str, complete: bool) -> None:
        seen.append((text, complete))

    result = await evaluate_finalizer_with_llm(
        llm_model=_Hung(),
        original_prompt=REQUEST,
        self_assessment=None,
        full_agent_output=GARBAGE_RESPONSE,
        steps=[],
        tool_error_history=None,
        evaluation_context=None,
        timeout_seconds=0.2,
        on_reasoning=sink,
    )

    assert result is None
    assert seen and seen[-1][1] is True


@pytest.mark.asyncio
async def test_timeout_is_a_total_deadline_across_the_budget_retry(monkeypatch):
    calls: List[int] = []

    class _SlowThenCut:
        async def generate_response(self, prompt: str, max_tokens: int = 1024, preserve_thinking: bool = False) -> str:
            calls.append(max_tokens)
            await asyncio.sleep(0.15)
            return "<think>never closes"

    result = await evaluate_finalizer_with_llm(
        llm_model=_SlowThenCut(),
        original_prompt=REQUEST,
        self_assessment=None,
        full_agent_output=GARBAGE_RESPONSE,
        steps=[],
        tool_error_history=None,
        evaluation_context=None,
        timeout_seconds=0.2,
    )

    assert result is None
    assert len(calls) <= 2


def _provisional(success: bool = True) -> Dict[str, Any]:
    return {
        "success": success,
        "summary_text": "Provisional summary",
        "result_payload": {"outcome": "success" if success else "failure", "verification_status": "pending"},
    }


def _inputs(local: bool = True) -> async_finalizer.FinalizeInputs:
    return async_finalizer.FinalizeInputs(
        original_prompt=REQUEST,
        agent_task_id="task-1",
        active_app=None,
        steps=[],
        standardized_messages=[GARBAGE_RESPONSE],
        agent_final_answer=AGENT_ANSWER,
        is_local_model=local,
    )


class _Broadcaster:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []

    async def broadcast(self, event: Dict[str, Any]) -> None:
        self.events.append(event)

    def outcome_updates(self) -> List[Dict[str, Any]]:
        return [e for e in self.events if e.get("event_type") == "agent_task_outcome_update"]


@pytest.fixture()
def persisted(monkeypatch):
    saved: List[Dict[str, Any]] = []

    async def fake_persist(agent_task_id, refined, verifier_thinking=None):
        saved.append({"refined": refined, "thinking": verifier_thinking})

    monkeypatch.setattr(async_finalizer, "_persist_refined_outcome", fake_persist)
    return saved


async def _run(finalize, persisted_unused=None, cancel_event=None):
    broadcaster = _Broadcaster()
    await async_finalizer._run_outcome_verification(
        inputs=_inputs(),
        llm_model=object(),
        ws_manager=broadcaster,
        agent_task_id="task-1",
        root_task_id="root-1",
        previous_task_id=None,
        cancel_event=cancel_event,
        provisional_envelope=_provisional(),
    )
    return broadcaster


@pytest.mark.asyncio
async def test_verifier_exception_still_resolves_with_the_provisional_outcome(monkeypatch, persisted):
    async def boom(**kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(async_finalizer, "finalize_agent_task_result", boom)
    broadcaster = await _run(boom)

    updates = broadcaster.outcome_updates()
    assert len(updates) == 1
    assert updates[0]["result_payload"]["verification_status"] == "resolved"
    assert persisted[0]["refined"]["result_payload"]["verification_status"] == "resolved"


@pytest.mark.asyncio
async def test_verifier_non_dict_result_still_resolves(monkeypatch, persisted):
    async def empty(**kwargs):
        return None

    monkeypatch.setattr(async_finalizer, "finalize_agent_task_result", empty)
    broadcaster = await _run(empty)

    assert broadcaster.outcome_updates()[0]["result_payload"]["verification_status"] == "resolved"


@pytest.mark.asyncio
async def test_verifier_outer_timeout_still_resolves(monkeypatch, persisted):
    async def hang(**kwargs):
        await asyncio.sleep(3600)

    monkeypatch.setattr(async_finalizer, "finalize_agent_task_result", hang)
    monkeypatch.setattr(async_finalizer, "_VERIFICATION_OUTER_TIMEOUT_SECONDS", 0.05)
    broadcaster = await _run(hang)

    assert broadcaster.outcome_updates()[0]["result_payload"]["verification_status"] == "resolved"


@pytest.mark.asyncio
async def test_canceled_verification_resolves_then_propagates_cancellation(monkeypatch, persisted):
    started = asyncio.Event()

    async def hang(**kwargs):
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(async_finalizer, "finalize_agent_task_result", hang)
    broadcaster = _Broadcaster()
    task = asyncio.create_task(
        async_finalizer._run_outcome_verification(
            inputs=_inputs(),
            llm_model=object(),
            ws_manager=broadcaster,
            agent_task_id="task-1",
            root_task_id="root-1",
            previous_task_id=None,
            cancel_event=None,
            provisional_envelope=_provisional(),
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert broadcaster.outcome_updates()[0]["result_payload"]["verification_status"] == "resolved"
    assert persisted


@pytest.mark.asyncio
async def test_verifier_reasoning_is_broadcast_and_persisted_with_the_task(monkeypatch, persisted):
    async def finalize(**kwargs):
        await kwargs["on_verifier_reasoning"]("Checking the answer against the request.", False)
        await kwargs["on_verifier_reasoning"]("Checking the answer against the request. It does not match.", True)
        return _provisional(False)

    monkeypatch.setattr(async_finalizer, "finalize_agent_task_result", finalize)
    broadcaster = await _run(finalize)

    thinking_events = [e for e in broadcaster.events if "thinking" in e]
    assert thinking_events[-1]["thinking_iteration"] == VERIFIER_THINKING_ITERATION
    assert thinking_events[-1]["thinking_complete"] is True
    assert "message" not in thinking_events[-1]
    assert persisted[0]["thinking"]["iteration"] == VERIFIER_THINKING_ITERATION
    assert "does not match" in persisted[0]["thinking"]["text"]


@pytest.mark.asyncio
async def test_local_verifier_gets_the_shorter_deadline_and_the_agent_answer(monkeypatch, persisted):
    captured: Dict[str, Any] = {}

    async def finalize(**kwargs):
        captured.update(kwargs)
        return _provisional()

    monkeypatch.setattr(async_finalizer, "finalize_agent_task_result", finalize)
    await _run(finalize)

    assert captured["evaluator_timeout_seconds"] == evaluation_module.LOCAL_EVALUATOR_TIMEOUT_SECONDS
    assert captured["agent_final_answer"] == AGENT_ANSWER


@pytest.mark.asyncio
async def test_canceled_run_is_not_persisted_or_broadcast(monkeypatch, persisted):
    class _Set:
        @staticmethod
        def is_set() -> bool:
            return True

    async def finalize(**kwargs):
        raise AssertionError("a canceled run must not be verified")

    monkeypatch.setattr(async_finalizer, "finalize_agent_task_result", finalize)
    broadcaster = await _run(finalize, cancel_event=_Set())

    assert broadcaster.events == []
    assert persisted == []


@pytest.mark.asyncio
async def test_new_local_run_cancels_only_local_verifications(monkeypatch, persisted):
    started = asyncio.Event()

    async def hang(**kwargs):
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(async_finalizer, "finalize_agent_task_result", hang)
    broadcaster = _Broadcaster()
    kwargs = dict(
        llm_model=object(),
        ws_manager=broadcaster,
        agent_task_id="task-1",
        root_task_id="root-1",
        previous_task_id=None,
        cancel_event=None,
        provisional_envelope=_provisional(),
    )
    async_finalizer.schedule_outcome_verification(inputs=_inputs(local=True), **kwargs)
    await started.wait()
    cloud_started = asyncio.Event()

    async def cloud_hang(**kw):
        cloud_started.set()
        await asyncio.sleep(0.5)
        return _provisional()

    monkeypatch.setattr(async_finalizer, "finalize_agent_task_result", cloud_hang)
    async_finalizer.schedule_outcome_verification(inputs=_inputs(local=False), **kwargs)
    await cloud_started.wait()

    assert async_finalizer.cancel_pending_verifications() == 1
    await asyncio.sleep(0.05)
    assert any(e["result_payload"]["verification_status"] == "resolved" for e in broadcaster.outcome_updates())
    await asyncio.gather(*list(async_finalizer._PENDING_VERIFICATIONS), return_exceptions=True)


def test_thinking_history_orders_post_loop_passes_after_loop_steps():
    segments = [
        {"iteration": VERIFIER_THINKING_ITERATION, "text": "verify", "is_complete": True},
        {"iteration": -1, "text": "synth", "is_complete": True},
        {"iteration": 2, "text": "step two", "is_complete": True},
        {"iteration": 1, "text": "step one", "is_complete": True},
    ]
    assert [s["iteration"] for s in normalize_thinking_history(segments)] == [1, 2, -1, -2]
