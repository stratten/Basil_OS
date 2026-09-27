"""Structural verification that _node_execute_todos_with_tools retries once with a
local fallback model when the staged execution loop raises
ModelUnavailableBeforeFirstResponse, per the reasoning-fallback plan.

_node_execute_todos_with_tools is deeply integrated with WorkflowCoordinator,
personalization, streaming synthesis, and finalization -- invoking it end-to-end
would require simulating the entire agent task pipeline. Following this file's
existing precedent (test_primary_path_uses_staged_tools_without_finalizer_for_main_executor
in test_agent_result_synthesis.py), this test verifies the exact fallback wiring
structurally from source rather than through a full functional invocation.
"""

from __future__ import annotations

import inspect

from api.services.agent_processing.lifecycle.execution_graph import agent_graph_nodes


def test_execute_todos_with_tools_retries_with_local_fallback_on_unreachable_model():
    source = inspect.getsource(agent_graph_nodes._node_execute_todos_with_tools)

    # The first staged run is wrapped so a ModelUnavailableBeforeFirstResponse
    # (zero LLM calls succeeded yet) is caught rather than propagated.
    assert "try:\n            staged = await run_staged_tool_loading(staged_request)" in source
    assert "except ModelUnavailableBeforeFirstResponse as unavailable_err:" in source

    except_start = source.index("except ModelUnavailableBeforeFirstResponse as unavailable_err:")
    except_block = source[except_start:]

    # Original error surfaces unchanged when no fallback model is designated/available.
    assert "if fallback_model is None:" in except_block
    assert "raise unavailable_err.original_error from unavailable_err" in except_block

    # Otherwise: load the fallback model, build a new LangChain LLM from it, swap
    # it into a *new* StagedExecutionRequest (never mutating the original), record
    # which model answered, and retry the staged run exactly once more.
    assert "get_designated_local_fallback_model(" in except_block
    assert "create_langchain_llm_from_model(" in except_block
    assert "dataclasses.replace(staged_request, langchain_llm=fallback_langchain_llm)" in except_block
    assert 'state.context["reasoning_fallback_model_used"] = fallback_model.model_name' in except_block
    assert except_block.count("run_staged_tool_loading(staged_request)") == 1

    # The retried result must be what feeds the rest of the node (no separate
    # unreachable second result variable left unused).
    assert "result = staged.result" in source
