"""The model that actually answered a run is persisted as result_data.model_used."""

from types import SimpleNamespace

import pytest

from api.services.agent_processing.lifecycle.runtime import workflow_coordinator as workflow_module
from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_workflow_result_service import (
    AgentTaskWorkflowResultService,
)


def _service() -> AgentTaskWorkflowResultService:
    return AgentTaskWorkflowResultService(db_service=SimpleNamespace())


def _request() -> SimpleNamespace:
    return SimpleNamespace(agent_task="Summarize the report")


def test_model_used_is_persisted_from_a_workflow_result_object():
    workflow_result = SimpleNamespace(
        execution_results=[],
        todos_completed=1,
        model_used="gpt-5-mini",
    )

    result_data = _service().build_workflow_result_data(workflow_result, _request())

    assert result_data["model_used"] == "gpt-5-mini"
    assert "reasoning_fallback_model_used" not in result_data


def test_model_used_is_persisted_from_a_workflow_result_dict():
    result_data = _service().build_workflow_result_data(
        {"execution_results": [], "todos_completed": 1, "model_used": "local-qwen-3.5"},
        _request(),
    )

    assert result_data["model_used"] == "local-qwen-3.5"


def test_model_used_is_omitted_when_no_model_was_recorded_or_the_value_is_not_text():
    service = _service()

    assert "model_used" not in service.build_workflow_result_data(
        SimpleNamespace(execution_results=[], todos_completed=0), _request()
    )
    assert "model_used" not in service.build_workflow_result_data(
        {"execution_results": [], "model_used": ""}, _request()
    )
    assert "model_used" not in service.build_workflow_result_data(
        {"execution_results": [], "model_used": 42}, _request()
    )


def test_fallback_model_is_recorded_alongside_model_used():
    result_data = _service().build_workflow_result_data(
        SimpleNamespace(
            execution_results=[],
            todos_completed=0,
            reasoning_fallback_model_used="local-qwen-3.5",
            model_used="local-qwen-3.5",
        ),
        _request(),
    )

    assert result_data["reasoning_fallback_model_used"] == "local-qwen-3.5"
    assert result_data["model_used"] == "local-qwen-3.5"


class _NoopCheckpointHandler:
    async def enrich_context_with_session_history(self, _task, context, *, agent_task_id=None):
        return context

    def is_checkpoint_request(self, _exc):
        return False

    def save_agent_task_to_session_context(self, *_args, **_kwargs):
        return None


class _NoopNotifier:
    def set_agent_task_id(self, agent_task_id):
        self.agent_task_id = agent_task_id

    def set_chain_identity(self, *, root_task_id=None, previous_task_id=None):
        return None

    async def send_status_update(self, *_args, **_kwargs):
        return None


async def _run_coordinator(monkeypatch, *, llm_model, context):
    async def fake_execute_tool_enhanced_workflow(_agent_task, _context):
        return {"execution_results": [], "success": True, "total_todos": 0, "todos_completed": 0}

    monkeypatch.setattr(workflow_module, "LANGGRAPH_AVAILABLE", True)
    monkeypatch.setattr(workflow_module, "execute_tool_enhanced_workflow", fake_execute_tool_enhanced_workflow)

    coordinator = WorkflowCoordinator(llm_model=llm_model)
    coordinator.session_context_service = _NoopCheckpointHandler()
    coordinator.status_notifier = _NoopNotifier()
    coordinator._llm_model = llm_model
    monkeypatch.setattr(
        coordinator,
        "_convert_tool_results_to_workflow_result",
        lambda _tool_results, _task: SimpleNamespace(
            execution_results=[],
            todos_completed=0,
            total_todos=0,
            execution_time=0,
        ),
    )
    return await coordinator._execute_with_tools("do the task", context, "task-1")


@pytest.mark.asyncio
async def test_coordinator_attaches_the_configured_reasoning_model(monkeypatch):
    result = await _run_coordinator(
        monkeypatch,
        llm_model=SimpleNamespace(model_name="gpt-5-mini"),
        context={},
    )

    assert result.model_used == "gpt-5-mini"
    assert not hasattr(result, "reasoning_fallback_model_used")


@pytest.mark.asyncio
async def test_coordinator_prefers_the_fallback_model_that_took_over(monkeypatch):
    result = await _run_coordinator(
        monkeypatch,
        llm_model=SimpleNamespace(model_name="gpt-5-mini"),
        context={"reasoning_fallback_model_used": "local-qwen-3.5"},
    )

    assert result.model_used == "local-qwen-3.5"
    assert result.reasoning_fallback_model_used == "local-qwen-3.5"


@pytest.mark.asyncio
async def test_coordinator_omits_model_used_when_no_model_name_is_known(monkeypatch):
    result = await _run_coordinator(
        monkeypatch,
        llm_model=SimpleNamespace(),
        context={},
    )

    assert not hasattr(result, "model_used")


async def _run_fast_lane(monkeypatch, *, model, answer):
    from api.services.agent_processing.lifecycle.submission import agent_task_submission_service as submission_module

    updates = []
    broadcasts = []

    class _Db:
        agent_conversation_thread_repository = None

        async def store_agent_task(self, **_kwargs):
            return None

        async def update_agent_task_status(self, **kwargs):
            updates.append(kwargs)

    async def fake_synthesis(**_kwargs):
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(text=answer)

    class _Service(submission_module.AgentTaskSubmissionService):
        def __init__(self):
            self.db_service = _Db()
            self.agent_task_orchestrator = SimpleNamespace(websocket_manager=None)

        async def _build_chain_context(self, _root_task_id, previous_task_id=None):
            return None

        async def _resolve_fast_lane_model(self, _model_id=None):
            return model

        async def broadcast(self, message):
            broadcasts.append(message)

    monkeypatch.setattr(submission_module, "stream_synthesized_final_answer", fake_synthesis)
    await _Service().handle_discussion_followup("What changed?", "root-1", agent_task_id="task-fast")
    return updates[0]["result_data"], broadcasts[0]


@pytest.mark.asyncio
async def test_fast_lane_records_the_model_that_answered(monkeypatch):
    result_data, broadcast = await _run_fast_lane(
        monkeypatch,
        model=SimpleNamespace(model_name="gpt-5-mini"),
        answer="Here is what changed.",
    )

    assert result_data["model_used"] == "gpt-5-mini"
    assert result_data["success"] is True
    assert broadcast["model_used"] == "gpt-5-mini"


@pytest.mark.asyncio
async def test_fast_lane_omits_model_used_when_generation_fails(monkeypatch):
    result_data, broadcast = await _run_fast_lane(
        monkeypatch,
        model=SimpleNamespace(model_name="gpt-5-mini"),
        answer=RuntimeError("model unavailable"),
    )

    assert "model_used" not in result_data
    assert "model_used" not in broadcast
    assert result_data["success"] is False


class _RecordingWebsocket:
    def __init__(self):
        self.messages = []

    async def broadcast(self, message):
        self.messages.append(message)


@pytest.mark.asyncio
async def test_finalizer_broadcast_carries_model_used_so_the_live_ui_can_label_the_run():
    websocket = _RecordingWebsocket()
    service = AgentTaskWorkflowResultService(db_service=SimpleNamespace(), websocket_manager=websocket)
    result_data = {
        "success": True,
        "model_used": "gpt-5-mini",
        "final_envelope": {"success": True, "summary_text": "Done.", "result_payload": {"files": []}},
    }

    await service.broadcast_final_envelope_if_present(
        result_data,
        SimpleNamespace(agent_task_id="task-1", root_task_id="task-1", previous_task_id=None),
    )

    assert websocket.messages[0]["event_type"] == "agent_task_result"
    assert websocket.messages[0]["model_used"] == "gpt-5-mini"


@pytest.mark.asyncio
async def test_result_message_omits_model_used_when_none_was_recorded():
    websocket = _RecordingWebsocket()
    service = AgentTaskWorkflowResultService(db_service=SimpleNamespace(), websocket_manager=websocket)

    await service.send_result_message(success=True, result="Done.", operation="multi_step_workflow", agent_task_id="task-1")
    await service.send_result_message(
        success=True, result="Done.", operation="multi_step_workflow", agent_task_id="task-1", model_used=""
    )

    assert all("model_used" not in message for message in websocket.messages)


class _RecordingAgentTaskService:
    def __init__(self):
        self.updates = []

    async def update_agent_task_status_if_active(self, agent_task_id, status, result_data):
        self.updates.append({"agent_task_id": agent_task_id, "status": status, "result_data": result_data})
        return True


async def _store_context(monkeypatch, **overrides):
    from api import dependencies
    from api.services.agent_processing.lifecycle.finalization import task_state_persistence

    agent_task_service = _RecordingAgentTaskService()
    knowledge_service = SimpleNamespace(agent_task_service=agent_task_service)
    monkeypatch.setattr(dependencies, "get_sqlite_knowledge_service", lambda: knowledge_service)

    await task_state_persistence._store_execution_context(
        agent_task_id="task-1",
        agent_output="OK",
        enhanced_output="OK",
        full_content="OK",
        intermediate_steps=[],
        dynamic_steps=[],
        final_envelope={"success": True, "summary_text": "OK"},
        **overrides,
    )
    return agent_task_service.updates


@pytest.mark.asyncio
async def test_terminal_execution_context_records_the_model_that_answered(monkeypatch):
    updates = await _store_context(monkeypatch, model_used="claude-sonnet-5-5")

    assert updates[0]["status"] == "completed"
    assert updates[0]["result_data"]["model_used"] == "claude-sonnet-5-5"


@pytest.mark.asyncio
async def test_terminal_execution_context_omits_model_used_when_unknown(monkeypatch):
    for value in (None, ""):
        updates = await _store_context(monkeypatch, model_used=value)
        assert "model_used" not in updates[-1]["result_data"]
