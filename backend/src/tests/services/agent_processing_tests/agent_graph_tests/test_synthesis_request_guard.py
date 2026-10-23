"""The final synthesis call must never run on a prompt that lost the user's request."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.services.agent_processing.lifecycle.execution_graph import agent_result_synthesis
from api.services.agent_processing.lifecycle.execution_graph.agent_result_synthesis import (
    run_final_synthesis_for_state,
    synthesis_prompt_contains_request,
)
from api.services.agent_processing.lifecycle.execution_graph.synthesis_budget import (
    SynthesisInput,
    build_budgeted_synthesis_input,
)

REQUEST = "Take a look at the attached folder and give me a summary of the BasilAuthService project."


def _local_window_model() -> SimpleNamespace:
    return SimpleNamespace(max_context_length=32_768, max_output_tokens=16_384)


def test_prompt_contains_request_detects_presence_and_absence():
    present = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": f"User request:\n{REQUEST}\n\nAgent handoff"},
    ]
    absent = [{"role": "system", "content": "System prompt"}]

    assert synthesis_prompt_contains_request(present, REQUEST) is True
    assert synthesis_prompt_contains_request(absent, REQUEST) is False
    assert synthesis_prompt_contains_request(absent, "") is True


def test_system_message_does_not_count_as_containing_the_request():
    messages = [{"role": "system", "content": f"System prompt {REQUEST}"}]

    assert synthesis_prompt_contains_request(messages, REQUEST) is False


def test_synthesis_output_reserve_is_capped_to_a_quarter_of_the_window():
    synthesis_input = build_budgeted_synthesis_input(
        llm_model=_local_window_model(),
        system_prompt="System prompt",
        user_agent_task=REQUEST,
        final_input="",
        agent_output="The project is an auth service.",
        intermediate_steps=[],
        context={},
    )

    assert synthesis_input.budget.effective_output_tokens <= 32_768 // 4
    assert synthesis_input.budget.input_budget_tokens >= 32_768 - 32_768 // 4


def test_large_tool_trace_keeps_request_and_handoff_within_budget():
    steps = [
        (
            SimpleNamespace(tool="files.read", tool_input={"path": f"/tmp/file{index}.swift"}),
            "let value = 1\n" * 4000,
        )
        for index in range(30)
    ]

    synthesis_input = build_budgeted_synthesis_input(
        llm_model=_local_window_model(),
        system_prompt="System prompt",
        user_agent_task=REQUEST,
        final_input="",
        agent_output="The project is an auth service with 30 source files.",
        intermediate_steps=steps,
        context={},
    )

    content = synthesis_input.messages[1]["content"]
    assert REQUEST in content
    assert "The project is an auth service with 30 source files." in content
    assert len(content) <= int(32_768 * 3.0)


def test_per_observation_truncation_does_not_claim_coverage_loss():
    steps = [
        (SimpleNamespace(tool="files.read", tool_input={}), "line of text\n" * 3000),
    ]

    synthesis_input = build_budgeted_synthesis_input(
        llm_model=_local_window_model(),
        system_prompt="System prompt",
        user_agent_task=REQUEST,
        final_input="",
        agent_output="Read the file.",
        intermediate_steps=steps,
        context={},
    )

    observation_evidence = [
        item
        for item in synthesis_input.truncation_evidence
        if item["source"].startswith("synthesis.tool_observation")
    ]
    assert observation_evidence
    assert all(item["affects_coverage"] is False for item in observation_evidence)


@pytest.mark.asyncio
async def test_synthesis_falls_back_to_agent_answer_when_prompt_lost_the_request(monkeypatch):
    streamed = []

    async def _fail_if_called(**kwargs):
        streamed.append(kwargs)
        raise AssertionError("the model must not be called with a prompt that lost the request")

    broken_input = SynthesisInput(
        messages=[{"role": "system", "content": "System prompt"}],
        budget=SimpleNamespace(),
        truncation_evidence=[],
        input_token_estimate=10,
    )
    monkeypatch.setattr(
        "api.services.agent_processing.lifecycle.execution_graph.synthesis_budget.build_budgeted_synthesis_input",
        lambda **kwargs: broken_input,
    )
    monkeypatch.setattr(agent_result_synthesis, "stream_synthesized_final_answer", _fail_if_called)

    result = await run_final_synthesis_for_state(
        state=SimpleNamespace(user_agent_task=REQUEST, context={}),
        final_input=REQUEST,
        agent_output="Here is the real answer from the agent loop.",
        intermediate_steps=[],
        llm_model=SimpleNamespace(),
        stream_notifier=None,
    )

    assert streamed == []
    assert result.text == "Here is the real answer from the agent loop."
    assert result.terminal.completed_cleanly is True
    assert any(
        item["reason"] == "request_missing_from_prompt" and item["affects_coverage"] is False
        for item in result.truncation_evidence
    )
