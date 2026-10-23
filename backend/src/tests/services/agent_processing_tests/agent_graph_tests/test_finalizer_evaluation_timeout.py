"""Tests for the finalizer LLM evaluator: bounded timeout and the local-model gate removal.

These cover the fix for the reported incident: local-model tasks must run the
same JSON-contract evaluator as cloud tasks (no unconditional bypass), and a
hung/slow model must fall back to the mechanical check instead of blocking the
detached off-critical-path verification task forever.
"""

from __future__ import annotations

import asyncio

import pytest

from api.core.models.reasoning.streaming_contract import GenerationBudget
from api.services.agent_processing.lifecycle.finalization import evaluation as evaluation_module
from api.services.agent_processing.lifecycle.finalization.evaluation import (
    EVALUATOR_TIMEOUT_SECONDS,
    evaluate_finalizer_with_llm,
)


def _fixed_budget(*, effective_output_tokens: int, model_max_output_tokens: int) -> GenerationBudget:
    """Bypass real registry/profile resolution so budget-retry tests control
    the initial effective budget and ceiling directly, independent of
    resolve_generation_budget's unrelated registry-lookup behavior."""
    return GenerationBudget(
        purpose="structured",
        requested_output_tokens=effective_output_tokens,
        effective_output_tokens=effective_output_tokens,
        input_budget_tokens=None,
        reserved_output_tokens=effective_output_tokens,
        model_id="fake-reasoning-model",
        context_window=None,
        model_max_output_tokens=model_max_output_tokens,
    )
from api.services.agent_processing.lifecycle.finalization.result_finalizer_tool import (
    finalize_agent_task_result,
)


class _HangingModel:
    """Simulates a local model whose generate_response never returns."""

    async def generate_response(self, prompt: str, max_tokens: int = 1024) -> str:
        await asyncio.sleep(3600)
        return "unreachable"


class _RespondingModel:
    def __init__(self, payload: str):
        self.payload = payload
        self.prompts: list[str] = []
        self.max_tokens_seen: list[int] = []

    async def generate_response(self, prompt: str, max_tokens: int = 1024) -> str:
        self.prompts.append(prompt)
        self.max_tokens_seen.append(max_tokens)
        return self.payload


class _ReasoningModel:
    """Simulates a llama.cpp-family adapter: accepts preserve_thinking, and its
    response can carry a leading <think> block ahead of the JSON verdict.

    responses_by_budget maps a max_tokens value to the raw text the model
    would have produced at that budget, so tests can simulate "the model's
    thinking got cut off at the first budget but finished at the second"
    without needing a real model.
    """

    def __init__(self, responses_by_budget: dict[int, str]):
        self.responses_by_budget = responses_by_budget
        self.calls: list[dict] = []

    async def generate_response(
        self, prompt: str, max_tokens: int = 1024, preserve_thinking: bool = False
    ) -> str:
        self.calls.append({"max_tokens": max_tokens, "preserve_thinking": preserve_thinking})
        if max_tokens in self.responses_by_budget:
            return self.responses_by_budget[max_tokens]
        # Fall back to the response registered at the highest budget not
        # exceeding max_tokens, matching how a real model would behave.
        eligible = [b for b in self.responses_by_budget if b <= max_tokens]
        return self.responses_by_budget[max(eligible)]


@pytest.mark.asyncio
async def test_evaluator_falls_back_to_none_on_timeout(monkeypatch):
    """A hung model must time out and return None (mechanical fallback), not hang forever."""
    monkeypatch.setattr(
        "api.services.agent_processing.lifecycle.finalization.evaluation.EVALUATOR_TIMEOUT_SECONDS",
        0.05,
    )
    result = await evaluate_finalizer_with_llm(
        llm_model=_HangingModel(),
        original_prompt="Investigate the build script.",
        self_assessment=None,
        full_agent_output="Some output.",
        steps=[],
        tool_error_history=None,
        evaluation_context=None,
    )
    assert result is None


@pytest.mark.asyncio
async def test_evaluator_returns_result_when_model_responds_in_time():
    import json

    model = _RespondingModel(json.dumps({
        "outcome": "success",
        "success": True,
        "failure_basis": "none",
        "user_reason": "",
        "technical_reason": "Clean result.",
        "should_retry": False,
    }))
    result = await evaluate_finalizer_with_llm(
        llm_model=model,
        original_prompt="Investigate the build script.",
        self_assessment=None,
        full_agent_output="Some output.",
        steps=[],
        tool_error_history=None,
        evaluation_context=None,
    )
    assert result is not None
    assert result.outcome == "success"
    assert result.success is True
    # Regression: the evaluator call must request a resolved output budget rather than
    # relying on generate_response's bare default, which starves reasoning models that
    # need room to think before emitting the required JSON (the FDCB.../73DC32E9-style
    # incident where the evaluator's response was empty after stripping <think> content).
    assert model.max_tokens_seen[0] > 1024


@pytest.mark.asyncio
async def test_finalizer_runs_evaluator_for_local_models_too():
    """Regression: local-model tasks must no longer bypass evaluate_finalizer_with_llm
    just because is_local_model=True (the exact defect in the reported incident)."""
    import json

    model = _RespondingModel(json.dumps({
        "outcome": "partial",
        "success": False,
        "failure_basis": "content_missing",
        "user_reason": "The requested change was not fully verified.",
        "technical_reason": "Evaluator ran for a local model and found a gap.",
        "should_retry": True,
    }))
    result = await finalize_agent_task_result(
        original_prompt="Investigate the build script and add offline python support.",
        agent_task_id="agent-local-eval-1",
        active_app=None,
        steps=[{"service": "shell_service", "method": "execute_command", "success": True, "result": {"exit_code": 0}}],
        standardized_messages=["I looked into the script but could not verify the change took effect."],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=None,
        llm_model=model,
        is_local_model=True,
    )

    assert len(model.prompts) == 1
    assert result["success"] is False
    assert result["outcome"] == "partial"


@pytest.mark.asyncio
async def test_evaluator_strips_a_complete_think_block_ahead_of_the_json_verdict():
    """A reasoning model that finished thinking within budget returns
    <think>...</think> followed by the JSON verdict (preserve_thinking=True
    keeps the tags instead of raising). The evaluator must still parse the
    trailing JSON on the first attempt, with no retry needed."""
    import json

    payload = (
        "<think>The tool trace shows a clean run, so this is success.</think>"
        + json.dumps(
            {
                "outcome": "success",
                "success": True,
                "failure_basis": "none",
                "user_reason": "",
                "technical_reason": "Clean result after reasoning.",
                "should_retry": False,
            }
        )
    )
    model = _ReasoningModel({1024: payload})

    result = await evaluate_finalizer_with_llm(
        llm_model=model,
        original_prompt="Investigate the build script.",
        self_assessment=None,
        full_agent_output="Some output.",
        steps=[],
        tool_error_history=None,
        evaluation_context=None,
    )

    assert result is not None
    assert result.outcome == "success"
    assert result.technical_reason == "Clean result after reasoning."
    assert len(model.calls) == 1
    assert model.calls[0]["preserve_thinking"] is True


@pytest.mark.asyncio
async def test_evaluator_retries_once_with_a_larger_budget_when_reasoning_is_cut_off(monkeypatch):
    """Regression for the 73DC32E9 retry incident: the model's <think> block
    consumed the entire first budget with no closing tag and no JSON, which
    must trigger exactly one retry at double the budget rather than an
    immediate mechanical fallback."""
    import json

    monkeypatch.setattr(
        evaluation_module,
        "resolve_generation_budget",
        lambda *args, **kwargs: _fixed_budget(effective_output_tokens=1024, model_max_output_tokens=4096),
    )

    first_budget_response = "<think>Still reasoning and never got to close the thought"
    second_budget_response = (
        "<think>Still reasoning and got there this time.</think>"
        + json.dumps(
            {
                "outcome": "success",
                "success": True,
                "failure_basis": "none",
                "user_reason": "",
                "technical_reason": "Finished reasoning on the second attempt.",
                "should_retry": False,
            }
        )
    )
    model = _ReasoningModel({})
    model.responses_by_budget = {
        1024: first_budget_response,
        2048: second_budget_response,
    }

    result = await evaluate_finalizer_with_llm(
        llm_model=model,
        original_prompt="Investigate the build script.",
        self_assessment=None,
        full_agent_output="Some output.",
        steps=[],
        tool_error_history=None,
        evaluation_context=None,
    )

    assert result is not None
    assert result.outcome == "success"
    assert result.technical_reason == "Finished reasoning on the second attempt."
    assert [c["max_tokens"] for c in model.calls] == [1024, 2048]


@pytest.mark.asyncio
async def test_evaluator_falls_back_to_none_when_reasoning_never_closes_even_after_retry(monkeypatch):
    """If the retry also never closes its <think> block, the evaluator must
    give up cleanly (mechanical fallback) instead of retrying forever."""
    monkeypatch.setattr(
        evaluation_module,
        "resolve_generation_budget",
        lambda *args, **kwargs: _fixed_budget(effective_output_tokens=1024, model_max_output_tokens=4096),
    )
    always_unterminated = "<think>Never gets around to answering, no matter the budget"
    model = _ReasoningModel({1024: always_unterminated, 2048: always_unterminated})

    result = await evaluate_finalizer_with_llm(
        llm_model=model,
        original_prompt="Investigate the build script.",
        self_assessment=None,
        full_agent_output="Some output.",
        steps=[],
        tool_error_history=None,
        evaluation_context=None,
    )

    assert result is None
    assert [c["max_tokens"] for c in model.calls] == [1024, 2048]


@pytest.mark.asyncio
async def test_evaluator_does_not_request_preserve_thinking_when_model_does_not_support_it():
    """Cloud models (and any adapter without a preserve_thinking parameter)
    must never be called with that kwarg, matching the same guard used in
    base_reasoning.generate_from_messages."""
    import json

    model = _RespondingModel(
        json.dumps(
            {
                "outcome": "success",
                "success": True,
                "failure_basis": "none",
                "user_reason": "",
                "technical_reason": "Clean result.",
                "should_retry": False,
            }
        )
    )

    result = await evaluate_finalizer_with_llm(
        llm_model=model,
        original_prompt="Investigate the build script.",
        self_assessment=None,
        full_agent_output="Some output.",
        steps=[],
        tool_error_history=None,
        evaluation_context=None,
    )

    assert result is not None
    assert result.outcome == "success"
