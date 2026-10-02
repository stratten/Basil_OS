"""Multi-select checkpoint contract: tool data, both broadcast whitelists, and agent guidance."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.services.agent_processing.lifecycle.execution_graph.system_prompts import (
    AGENT_SYSTEM_PROMPT_TEMPLATE,
)
from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import (
    SLIM_DESCRIPTION,
    CheckpointRequest,
    request_user_input,
)


class _RecordingWebSocket:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def broadcast(self, event: dict) -> None:
        self.events.append(event)


def _raise_checkpoint(**arguments) -> dict:
    with pytest.raises(CheckpointRequest) as exc_info:
        request_user_input.invoke({"prompt": "Pick", **arguments})
    return exc_info.value.checkpoint_data


def test_selection_can_request_multiple_answers():
    data = _raise_checkpoint(input_type="selection", options=["Sales", "Support"], allow_multiple=True)
    assert data["allow_multiple"] is True


def test_multiple_answers_are_ignored_for_non_choice_inputs():
    assert _raise_checkpoint(input_type="yes_no", allow_multiple=True)["allow_multiple"] is False
    assert _raise_checkpoint(input_type="text", allow_multiple=True)["allow_multiple"] is False


def test_single_answer_is_the_default():
    assert _raise_checkpoint(input_type="selection", options=["A", "B"])["allow_multiple"] is False


def test_descriptions_document_the_reply_format():
    full_description = request_user_input.description or ""
    assert "allow_multiple" in SLIM_DESCRIPTION
    assert "Other: <text>" in SLIM_DESCRIPTION
    assert "do not use for state that tools can inspect" in SLIM_DESCRIPTION
    assert "allow_multiple" in full_description
    assert "Selected: A; B" in full_description


def test_system_prompt_teaches_multi_select_and_multi_day_reviews():
    prompt = AGENT_SYSTEM_PROMPT_TEMPLATE
    assert "allow_multiple=True" in prompt
    assert "`Selected: A; B`" in prompt
    assert 'do not add an "Other" or "Something else" option yourself' in prompt
    assert "group_by='day' first" in prompt
    assert "cursor=next_cursor until next_cursor is null" in prompt
    assert "Never treat a checkpoint response as authorization until resolve_target_authorization returns authorized." in prompt


@pytest.mark.asyncio
async def test_workflow_checkpoint_broadcast_carries_allow_multiple():
    from api.services.agent_processing.lifecycle.runtime.checkpoint_workflow_service import (
        WorkflowCheckpointWorkflowService,
    )

    websocket = _RecordingWebSocket()
    service = WorkflowCheckpointWorkflowService(websocket_manager=websocket)
    await service.handle_checkpoint_request(
        CheckpointRequest(
            {"prompt": "Pick", "input_type": "selection", "options": ["A", "B"], "allow_multiple": True}
        ),
        "task-1",
        "Compile the report",
    )
    assert websocket.events[0]["checkpoint_data"]["allow_multiple"] is True


@pytest.mark.asyncio
async def test_workflow_checkpoint_broadcast_defaults_allow_multiple_to_false():
    from api.services.agent_processing.lifecycle.runtime.checkpoint_workflow_service import (
        WorkflowCheckpointWorkflowService,
    )

    websocket = _RecordingWebSocket()
    service = WorkflowCheckpointWorkflowService(websocket_manager=websocket)
    await service.handle_checkpoint_request(
        CheckpointRequest({"prompt": "Proceed?", "input_type": "yes_no"}),
        "task-1",
        "Compile the report",
    )
    assert websocket.events[0]["checkpoint_data"]["allow_multiple"] is False


@pytest.mark.asyncio
async def test_state_persistence_broadcast_carries_allow_multiple(monkeypatch):
    from api.services.agent_processing.lifecycle.finalization import task_state_persistence
    import api.dependencies as dependencies

    def unavailable():
        raise RuntimeError("database unavailable in this test")

    monkeypatch.setattr(dependencies, "get_sqlite_knowledge_service", unavailable)
    websocket = _RecordingWebSocket()
    state = SimpleNamespace(
        context={"agent_task_id": "task-1"},
        user_agent_task="Compile the report",
        available_tools=None,
    )
    coordinator = SimpleNamespace(_websocket_manager=websocket)
    result = await task_state_persistence.handle_checkpoint_request(
        CheckpointRequest(
            {"prompt": "Pick", "input_type": "selection", "options": ["A"], "allow_multiple": True}
        ),
        state,
        coordinator,
    )
    assert websocket.events[0]["checkpoint_data"]["allow_multiple"] is True
    assert result["tool_execution_results"][0]["checkpoint_data"]["allow_multiple"] is True
