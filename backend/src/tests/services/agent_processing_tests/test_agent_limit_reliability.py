from types import SimpleNamespace

import pytest

from api.core.models.reasoning.streaming_contract import (
    StreamEvent,
    resolve_generation_budget,
    terminal_from_provider_reason,
)
from api.services.agent_processing.lifecycle.execution_graph.agent_result_synthesis import (
    run_final_synthesis_for_state,
)
from api.services.agent_processing.lifecycle.finalization.result_finalizer_tool import (
    finalize_agent_task_result,
)


class _Claude46LikeModel:
    model_name = "claude-sonnet-4-6"
    max_tokens_to_sample = 4000
    max_output_tokens = 64000
    max_context_length = 1000000

    def __init__(self, terminal_reason="completed"):
        self.terminal_reason = terminal_reason
        self.received_budget = None

    async def stream_chat_completion(self, _messages, budget=None):
        self.received_budget = budget
        yield StreamEvent(text="partial final answer")
        yield StreamEvent(terminal=terminal_from_provider_reason(self.terminal_reason))


def test_claude_46_budget_uses_registry_output_not_initialized_sample_cap():
    model = _Claude46LikeModel()

    budget = resolve_generation_budget(
        model,
        purpose="final_synthesis",
        input_token_estimate=1000,
    )

    assert budget.model_id == "claude-sonnet-4-6"
    assert budget.model_max_output_tokens == 128000
    assert budget.effective_output_tokens == 128000
    assert budget.effective_output_tokens != model.max_tokens_to_sample


def test_local_coder_final_synthesis_uses_profile_budget_not_capability_ceiling():
    model = type(
        "LocalCoder",
        (),
        {
            "model_name": "Qwen-qwen3-coder-30b-a3b-instruct-q4km",
            "max_tokens_to_sample": 65536,
            "max_output_tokens": 65536,
            "max_context_length": 32768,
            "model_path": type("P", (), {"stem": "qwen3-coder-30b-a3b-instruct-q4km"})(),
        },
    )()

    budget = resolve_generation_budget(
        model,
        purpose="final_synthesis",
        input_token_estimate=1000,
    )

    assert budget.model_id == "Qwen-qwen3-coder-30b-a3b-instruct-q4km"
    assert budget.model_max_output_tokens == 65536
    assert budget.effective_output_tokens == 16384
    assert budget.effective_output_tokens != budget.model_max_output_tokens


@pytest.mark.asyncio
async def test_final_synthesis_preserves_max_token_terminal_state():
    model = _Claude46LikeModel(terminal_reason="max_tokens")
    state = SimpleNamespace(
        user_agent_task="Draft 15 emails",
        context={},
    )

    result = await run_final_synthesis_for_state(
        state=state,
        final_input="Draft 15 emails",
        agent_output="Tool agent gathered the required contacts.",
        intermediate_steps=[],
        llm_model=model,
        stream_notifier=None,
    )

    assert result.text == "partial final answer"
    assert result.terminal.reason == "max_tokens"
    assert result.terminal.truncated is True
    assert model.received_budget.effective_output_tokens == 128000


@pytest.mark.asyncio
async def test_finalizer_marks_missing_numbered_deliverables_partial():
    twelve_items = "\n\n".join(
        f"## {index}. Draft {index}\n\nBody {index}"
        for index in range(1, 13)
    )

    envelope = await finalize_agent_task_result(
        original_prompt="Draft 15 emails for these contacts.",
        agent_task_id="task-1",
        active_app="Basil",
        steps=[],
        self_assessment="I drafted all 15 emails.",
        standardized_messages=[twelve_items],
        metrics={"steps_completed": 1, "steps_total": 1},
        success=True,
        llm_model=None,
        synthesis_evidence={
            "terminal": {"reason": "completed", "truncated": False},
            "completed_cleanly": True,
        },
    )

    assert envelope["success"] is False
    assert envelope["outcome"] == "partial"
    assert envelope["result_payload"]["coverage"] == {
        "requested_item_count": 15,
        "delivered_item_count": 12,
        "coverage_status": "incomplete",
    }
