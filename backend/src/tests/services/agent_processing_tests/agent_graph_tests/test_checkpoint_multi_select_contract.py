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


def test_details_markdown_is_carried_trimmed_for_any_input_type():
    details = "**To:** mariam@example.com\n**Subject:** Re: Storage limits\n\nHi Mariam"
    assert _raise_checkpoint(input_type="yes_no", details_markdown=f"  {details}\n ")["details_markdown"] == details
    assert _raise_checkpoint(input_type="text", details_markdown=details)["details_markdown"] == details


def test_details_markdown_defaults_to_empty_and_ignores_blank_values():
    assert _raise_checkpoint(input_type="yes_no")["details_markdown"] == ""
    assert _raise_checkpoint(input_type="yes_no", details_markdown="  \n ")["details_markdown"] == ""


def test_overlong_details_are_cut_with_a_visible_marker_instead_of_failing():
    from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import (
        MAX_CHECKPOINT_DETAILS_CHARS,
    )

    data = _raise_checkpoint(input_type="yes_no", details_markdown="x" * (MAX_CHECKPOINT_DETAILS_CHARS + 500))
    assert data["details_markdown"].startswith("x" * MAX_CHECKPOINT_DETAILS_CHARS)
    assert "Cut here" in data["details_markdown"]
    assert len(data["details_markdown"]) < MAX_CHECKPOINT_DETAILS_CHARS + 200


def test_details_survive_alongside_a_metadata_payload_at_its_size_cap():
    data = _raise_checkpoint(
        input_type="yes_no",
        details_markdown="Full body",
        metadata={"note": "y" * 1_500},
    )
    assert data["details_markdown"] == "Full body"


def test_descriptions_and_prompt_require_showing_what_is_being_approved():
    full_description = request_user_input.description or ""
    assert "details_markdown" in SLIM_DESCRIPTION
    assert "details_markdown" in full_description
    assert "recipients" in full_description
    prompt = AGENT_SYSTEM_PROMPT_TEMPLATE
    assert "SHOW WHAT THE USER IS APPROVING" in prompt
    assert "`details_markdown`" in prompt
    assert "Should I send this draft email?" not in prompt


@pytest.mark.asyncio
async def test_workflow_checkpoint_broadcast_carries_details_markdown():
    from api.services.agent_processing.lifecycle.runtime.checkpoint_workflow_service import (
        WorkflowCheckpointWorkflowService,
    )

    websocket = _RecordingWebSocket()
    service = WorkflowCheckpointWorkflowService(websocket_manager=websocket)
    await service.handle_checkpoint_request(
        CheckpointRequest({"prompt": "Send it?", "input_type": "yes_no", "details_markdown": "Hi Mariam"}),
        "task-1",
        "Reply to Mariam",
    )
    assert websocket.events[0]["checkpoint_data"]["details_markdown"] == "Hi Mariam"


@pytest.mark.asyncio
async def test_workflow_checkpoint_broadcast_defaults_details_markdown_to_empty():
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
    assert websocket.events[0]["checkpoint_data"]["details_markdown"] == ""


@pytest.mark.asyncio
async def test_state_persistence_broadcast_carries_details_markdown(monkeypatch):
    from api.services.agent_processing.lifecycle.finalization import task_state_persistence
    import api.dependencies as dependencies

    def unavailable():
        raise RuntimeError("database unavailable in this test")

    monkeypatch.setattr(dependencies, "get_sqlite_knowledge_service", unavailable)
    websocket = _RecordingWebSocket()
    state = SimpleNamespace(
        context={"agent_task_id": "task-1"},
        user_agent_task="Reply to Mariam",
        available_tools=None,
    )
    coordinator = SimpleNamespace(_websocket_manager=websocket)
    result = await task_state_persistence.handle_checkpoint_request(
        CheckpointRequest({"prompt": "Send it?", "input_type": "yes_no", "details_markdown": "Hi Mariam"}),
        state,
        coordinator,
    )
    assert websocket.events[0]["checkpoint_data"]["details_markdown"] == "Hi Mariam"
    assert result["tool_execution_results"][0]["checkpoint_data"]["details_markdown"] == "Hi Mariam"
