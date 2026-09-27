"""Unit tests for backend final synthesis helpers."""

from __future__ import annotations

import json
import pytest
from types import SimpleNamespace
from langchain_classic.schema import AgentAction

from api.services.agent_processing.lifecycle.execution_graph.agent_result_synthesis import (
    build_final_synthesis_messages,
    infer_success_flag_for_direct_finalize,
    intermediate_steps_to_finalizer_steps,
    normalize_agent_executor_output,
    stream_synthesized_final_answer,
)
from api.services.agent_processing.lifecycle.execution_graph.synthesis_budget import (
    build_budgeted_synthesis_input,
)
from api.services.agent_processing.lifecycle import execution_graph
from api.services.agent_processing.lifecycle.execution_graph import staged_execution_loop
from api.services.agent_processing.lifecycle.execution_graph.agent_graph_nodes import (
    _collect_emitted_thinking_history,
)
from api.services.agent_processing.lifecycle.finalization import task_state_persistence


def test_normalize_agent_executor_output_anthropic_blocks():
    blocks = [{"text": "Hello", "type": "text", "index": 0}, {"text": " world", "type": "text", "index": 1}]
    assert normalize_agent_executor_output(blocks) == "Hello\n world"


@pytest.mark.asyncio
async def test_store_execution_context_persists_normalized_thinking_history(monkeypatch):
    persisted = {}

    class AgentTaskService:
        async def update_agent_task_status_if_active(self, **kwargs):
            persisted.update(kwargs)
            return True

    class KnowledgeService:
        agent_task_service = AgentTaskService()

    import api.dependencies as dependencies

    monkeypatch.setattr(dependencies, "get_sqlite_knowledge_service", KnowledgeService)

    await task_state_persistence._store_execution_context(
        agent_task_id="task-reasoning",
        agent_output="Done",
        enhanced_output="Done",
        full_content="Done",
        intermediate_steps=[],
        dynamic_steps=[],
        final_envelope={"success": True},
        thinking_history=[
            {"iteration": 2, "text": "First update", "is_complete": False},
            {"iteration": 1, "text": "Earlier step", "is_complete": True},
            {"iteration": 2, "text": "Final update", "is_complete": True},
            {"iteration": "bad", "text": "Ignore me", "is_complete": True},
            {"iteration": 3, "text": "", "is_complete": True},
        ],
    )

    assert persisted["result_data"]["thinking_history"] == [
        {"iteration": 1, "text": "Earlier step", "is_complete": True},
        {"iteration": 2, "text": "Final update", "is_complete": True},
    ]


def test_collect_emitted_thinking_history_combines_all_ui_sources():
    callback = SimpleNamespace(
        get_thinking_history=lambda: [
            {"iteration": 1, "text": "Provider reasoning", "is_complete": True},
        ]
    )
    llm = SimpleNamespace(
        _basil_heartbeat=SimpleNamespace(
            thinking_segments=[
                {"iteration": 2, "text": "Local reasoning", "is_complete": True},
            ]
        )
    )

    assert _collect_emitted_thinking_history(
        [callback],
        llm,
        [{"iteration": -1, "text": "Synthesis reasoning", "is_complete": True}],
    ) == [
        {"iteration": 1, "text": "Provider reasoning", "is_complete": True},
        {"iteration": 2, "text": "Local reasoning", "is_complete": True},
        {"iteration": -1, "text": "Synthesis reasoning", "is_complete": True},
    ]


def test_build_final_synthesis_messages_accepts_list_handoff():
    msgs = build_final_synthesis_messages(
        user_agent_task="x",
        final_input="",
        agent_output=[{"text": "handoff text", "type": "text"}],
        intermediate_steps=[],
        context={},
    )
    user = next(m["content"] for m in msgs if m["role"] == "user")
    assert "handoff text" in user


def test_build_final_synthesis_messages_includes_staged_tool_diagnostics():
    msgs = build_final_synthesis_messages(
        user_agent_task="Check Speakeasy status",
        final_input="",
        agent_output="handoff",
        intermediate_steps=[],
        context={
            "staged_tool_loading_diagnostics": [
                {
                    "invalid_loader_requests": ["not_a_family"],
                    "mapped_family_inputs": {"external_catalog": ["external"]},
                    "new_families": ["external"],
                }
            ]
        },
    )
    user = next(m["content"] for m in msgs if m["role"] == "user")

    assert "Staged tool loading diagnostics" in user
    assert "external_catalog" in user
    assert "Do not infer that an external service connection is missing" in user


def test_intermediate_steps_to_finalizer_steps_skips_finalizer_and_parses_json():
    a1 = AgentAction(
        tool="file_service.create",
        tool_input={"path": "/tmp/x.txt"},
        log="t",
    )
    fin = AgentAction(tool="finalize_agent_task_result", tool_input={}, log="f")
    steps = intermediate_steps_to_finalizer_steps(
        [
            (a1, json.dumps({"success": True, "file": "x.txt"})),
            (fin, '{"summary_text": "nope"}'),
        ]
    )
    assert len(steps) == 1
    assert steps[0]["service"] == "file_service"
    assert steps[0]["method"] == "create"
    assert steps[0]["success"] is True
    assert isinstance(steps[0]["result"], dict)


def test_intermediate_steps_mark_validation_failure_observation_as_failed():
    validation_observation = (
        "Tool input validation failed for field(s): command. "
        "Pass each argument as a native JSON value (for object arguments send a "
        "JSON object, not a quoted JSON string), then call the tool again."
    )
    action = AgentAction(
        tool="shell_service_execute_command",
        tool_input={"color": "green"},
        log="",
    )

    steps = intermediate_steps_to_finalizer_steps([(action, validation_observation)])

    assert len(steps) == 1
    assert steps[0]["success"] is False


def test_infer_success_does_not_veto_on_tool_error_log():
    out = infer_success_flag_for_direct_finalize(
        [],
        {"tool_errors": [{"type": "wiring", "tool": "t", "error": "e"}]},
    )
    assert out is None


@pytest.mark.asyncio
async def test_stream_synthesized_final_answer_coalesces_and_completes():
    calls: list[dict] = []

    class _FakeStream:
        def __init__(self):
            self._s = "a" * 500

        async def chat_completion_streaming(self, messages: list) -> "async iterator":
            # Yield in small token-sized pieces
            for i in range(0, len(self._s), 50):
                piece = self._s[i : i + 50]
                yield piece

    class N:
        async def send_agent_progress_update(self, **kwargs):
            calls.append({"k": "progress", **kwargs})

        async def send_agent_result_streaming_chunk(
            self, **kwargs
        ):
            calls.append({"k": "chunk", **kwargs})

        async def send_agent_result_streaming_complete(self, **kwargs):
            calls.append({"k": "complete", **kwargs})

    result = await stream_synthesized_final_answer(
        llm_model=_FakeStream(),
        messages=[{"role": "user", "content": "u"}],
        stream_notifier=N(),
    )
    assert result.text == "a" * 500
    assert any(c["k"] == "complete" for c in calls)
    assert calls[-1]["final_result"] == "a" * 500
    # At least one chunk with cumulative partial
    ch = [c for c in calls if c["k"] == "chunk"]
    assert ch and ch[-1]["source"] == "final_synthesis"
    # Chunk deliveries occur before streaming_complete; second progress sits before complete.
    indices_complete = [i for i, c in enumerate(calls) if c["k"] == "complete"]
    indices_chunk = [i for i, c in enumerate(calls) if c["k"] == "chunk"]
    assert indices_chunk and indices_complete
    assert max(indices_chunk) < min(indices_complete)
    prog_review = [
        i for i, c in enumerate(calls)
        if c["k"] == "progress" and "Reviewing the result" in str(c.get("message", ""))
    ]
    assert prog_review and prog_review[-1] < indices_complete[-1]


@pytest.mark.asyncio
async def test_stream_synthesized_final_answer_strips_leaked_reasoning_block():
    """Regression for the 73DC32E9-style incident: a reasoning-capable local model's
    <think> block streamed through llama.cpp with no adapter-level stripping (unlike
    the non-streaming generate_response path), so the raw chain-of-thought reached
    the user verbatim as the final answer. The synthesis result and the final
    streamed payload must both contain only the text after </think>."""
    calls: list[dict] = []
    raw = "<think>Let me reason about this privately.\nSelf-Correction: still thinking.</think>Here is the actual answer."

    class _FakeStream:
        async def chat_completion_streaming(self, messages: list):
            for i in range(0, len(raw), 20):
                yield raw[i : i + 20]

    class N:
        async def send_agent_progress_update(self, **kwargs):
            calls.append({"k": "progress", **kwargs})

        async def send_agent_result_streaming_chunk(self, **kwargs):
            calls.append({"k": "chunk", **kwargs})

        async def send_agent_result_streaming_complete(self, **kwargs):
            calls.append({"k": "complete", **kwargs})

    result = await stream_synthesized_final_answer(
        llm_model=_FakeStream(),
        messages=[{"role": "user", "content": "u"}],
        stream_notifier=N(),
    )
    assert result.text == "Here is the actual answer."
    assert "<think>" not in result.text
    complete = next(c for c in calls if c["k"] == "complete")
    assert complete["final_result"] == "Here is the actual answer."
    assert result.thinking_history == [{
        "iteration": -1,
        "text": "Let me reason about this privately.\nSelf-Correction: still thinking.",
        "is_complete": True,
    }]


@pytest.mark.asyncio
async def test_stream_synthesized_final_answer_flags_unterminated_reasoning_as_truncated():
    """A cut-off <think> block (no closing tag) means the model never emitted an
    answer at all; that must surface as truncation evidence, not silently as ""."""
    calls: list[dict] = []
    raw = "<think>Still reasoning and the generation stopped here"

    class _FakeStream:
        async def chat_completion_streaming(self, messages: list):
            yield raw

    class N:
        async def send_agent_progress_update(self, **kwargs):
            pass

        async def send_agent_result_streaming_chunk(self, **kwargs):
            pass

        async def send_agent_result_streaming_complete(self, **kwargs):
            calls.append(kwargs)

    result = await stream_synthesized_final_answer(
        llm_model=_FakeStream(),
        messages=[{"role": "user", "content": "u"}],
        stream_notifier=N(),
    )
    assert result.text == ""
    assert any(e.get("reason") == "unterminated_reasoning_block" for e in result.truncation_evidence)
    assert calls[-1]["final_result"] == ""


@pytest.mark.asyncio
async def test_stream_synthesized_final_answer_broadcasts_reasoning_as_thinking_entry():
    """A leaked <think> block must be routed to the same agent_progress_update
    thinking/thinking_complete/thinking_iteration channel the agent-loop's
    LiveProgressCallbackHandler already uses for reasoning, not silently stripped.
    The frontend's ThinkingSegments UI keys segments by thinking_iteration, so the
    final-synthesis phase must use a reserved iteration value distinct from the
    agent loop's (which starts at 1)."""
    broadcasts: list[dict] = []
    raw = "<think>Let me reason about this privately.</think>Here is the actual answer."

    class _FakeStream:
        async def chat_completion_streaming(self, messages: list):
            for i in range(0, len(raw), 15):
                yield raw[i : i + 15]

    class _FakeWsManager:
        async def broadcast(self, event):
            broadcasts.append(event)

    class N:
        def __init__(self):
            self._websocket_manager = _FakeWsManager()
            self._agent_task_id = "task-123"

        async def send_agent_progress_update(self, **kwargs):
            pass

        async def send_agent_result_streaming_chunk(self, **kwargs):
            pass

        async def send_agent_result_streaming_complete(self, **kwargs):
            pass

    result = await stream_synthesized_final_answer(
        llm_model=_FakeStream(),
        messages=[{"role": "user", "content": "u"}],
        stream_notifier=N(),
    )

    assert result.text == "Here is the actual answer."
    assert "<think>" not in result.text
    thinking_events = [e for e in broadcasts if e.get("event_type") == "agent_progress_update"]
    assert thinking_events
    assert all(e["thinking_iteration"] == -1 for e in thinking_events)
    assert all(e["agent_task_id"] == "task-123" for e in thinking_events)
    final_event = thinking_events[-1]
    assert final_event["thinking_complete"] is True
    assert final_event["thinking"] == "Let me reason about this privately."
    assert not any(e["thinking_complete"] and "Here is the actual answer" in e["thinking"] for e in thinking_events)


@pytest.mark.asyncio
async def test_stream_synthesized_final_answer_passes_operation_to_notifier():
    calls: list[dict] = []

    class _FakeModel:
        async def chat_completion(self, messages):
            return {"content": "fast lane answer"}

    class N:
        async def send_agent_progress_update(self, **kwargs):
            pass

        async def send_agent_result_streaming_chunk(self, **kwargs):
            calls.append({"k": "chunk", **kwargs})

        async def send_agent_result_streaming_complete(self, **kwargs):
            calls.append({"k": "complete", **kwargs})

    result = await stream_synthesized_final_answer(
        llm_model=_FakeModel(),
        messages=[{"role": "user", "content": "u"}],
        stream_notifier=N(),
        operation="discussion",
        stream_source="fast_lane",
    )

    assert result.text == "fast lane answer"
    chunk_calls = [c for c in calls if c["k"] == "chunk"]
    complete_calls = [c for c in calls if c["k"] == "complete"]
    assert chunk_calls and chunk_calls[0]["operation"] == "discussion"
    assert complete_calls and complete_calls[0]["operation"] == "discussion"


@pytest.mark.asyncio
async def test_stream_synthesized_final_answer_defaults_operation_to_multi_step_workflow():
    calls: list[dict] = []

    class _FakeModel:
        async def chat_completion(self, messages):
            return {"content": "answer"}

    class N:
        async def send_agent_progress_update(self, **kwargs):
            pass

        async def send_agent_result_streaming_chunk(self, **kwargs):
            calls.append({"k": "chunk", **kwargs})

        async def send_agent_result_streaming_complete(self, **kwargs):
            calls.append({"k": "complete", **kwargs})

    await stream_synthesized_final_answer(
        llm_model=_FakeModel(),
        messages=[{"role": "user", "content": "u"}],
        stream_notifier=N(),
    )

    assert calls[0]["operation"] == "multi_step_workflow"
    assert calls[-1]["operation"] == "multi_step_workflow"


def test_build_final_synthesis_messages_includes_instruction():
    st = SimpleNamespace(
        user_instruction="Do a thing",
        context={"active_app": "Xcode", "app_context": {}, "agent_task_id": "tid"},
    )
    msgs = build_final_synthesis_messages(
        user_agent_task=st.user_instruction,
        final_input="",
        agent_output="handoff",
        intermediate_steps=[],
        context=st.context,
    )
    assert any("Do a thing" in m["content"] for m in msgs if m["role"] == "user")
    assert any("Xcode" in m["content"] for m in msgs if m["role"] == "user")


def _material_operation_observation(verification_status: str) -> str:
    return json.dumps(
        {
            "material_operation": {
                "contract_version": 1,
                "material_write": True,
                "receipts": [
                    {
                        "entity": {
                            "entity_type": "message",
                            "source_system": "mail",
                            "source_scope": {"account": "primary"},
                            "external_id": "message-1",
                        },
                        "requested_effect": {
                            "operation": "move",
                            "folder": "Archive",
                        },
                        "execution_state": "succeeded",
                        "observed_postcondition": (
                            {"folder": "Archive"}
                            if verification_status == "verified"
                            else {}
                        ),
                        "verification_status": verification_status,
                        "evidence": (
                            {"readback": "matched"}
                            if verification_status == "verified"
                            else {}
                        ),
                        "discrepancy": {},
                    }
                ],
            }
        }
    )


def _synthesis_budget_model() -> SimpleNamespace:
    return SimpleNamespace(
        max_context_length=16_000,
        max_output_tokens=1_024,
    )


def test_budgeted_synthesis_injects_material_claim_constraints():
    synthesis_input = build_budgeted_synthesis_input(
        llm_model=_synthesis_budget_model(),
        system_prompt="System prompt",
        user_agent_task="Archive these messages.",
        final_input="",
        agent_output="The messages were handled.",
        intermediate_steps=[
            (
                SimpleNamespace(tool="mail.move"),
                _material_operation_observation("unverified"),
            )
        ],
        context={},
    )

    content = synthesis_input.messages[1]["content"]
    assert "Material change evidence" in content
    assert "do not state these as completed" in content


def test_budgeted_synthesis_omits_material_constraints_without_receipts():
    synthesis_input = build_budgeted_synthesis_input(
        llm_model=_synthesis_budget_model(),
        system_prompt="System prompt",
        user_agent_task="Summarize these messages.",
        final_input="",
        agent_output="The messages were summarized.",
        intermediate_steps=[],
        context={},
    )

    assert "Material change evidence" not in synthesis_input.messages[1]["content"]


def test_primary_path_uses_staged_tools_without_finalizer_for_main_executor():
    import inspect

    staged_source = inspect.getsource(staged_execution_loop.run_staged_tool_loading)
    node_source = inspect.getsource(
        execution_graph.agent_graph_nodes._node_execute_todos_with_tools
    )
    assert "core_tools = select_core_tools(all_tools, family_loader_tool)" in staged_source
    assert "select_tools_for_families(" in staged_source
    # Main path must not pass a finalizer tool; recovery executor may still add it.
    main_start = staged_source.index("agent_executor = create_agent_executor(")
    main_executor_call = staged_source[main_start:]
    assert "active_tools" in main_executor_call
    assert "finalize_tool" not in main_executor_call
    assert "run_staged_tool_loading(" in node_source
    assert "recovery_agent_executor = create_agent_executor" in node_source
    recovery_start = node_source.index("recovery_agent_executor = create_agent_executor")
    recovery_executor_call = node_source[recovery_start:]
    assert "custom_instructions_section=custom_instructions_section" in recovery_executor_call
