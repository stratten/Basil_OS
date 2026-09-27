"""Tests for the shared terminal-finalization handling used by both the initial run
rail and the checkpoint-resume rail (Resume Terminal Finalization, Option A).

Covers:
- finalize parity: finalize_workflow_output normalizes + broadcasts once.
- resume genuine completion: finalize_resumed_workflow persists completed + broadcasts.
- negative (no envelope): resume without a final_envelope persists failed (no false completed).
- negative (missing record / empty state): finalize_resumed_workflow is a safe no-op.
- negative (another checkpoint): a resume that re-raises CheckpointRequest never finalizes.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from api.services.agent_processing.lifecycle.runtime import resume_terminal_finalizer
from api.services.agent_processing.lifecycle.runtime.resume_terminal_finalizer import (
    finalize_resumed_workflow,
)
from api.services.agent_processing.lifecycle.runtime.checkpoint_workflow_service import (
    WorkflowCheckpointWorkflowService,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_processing_service import (
    AgentTaskProcessingService,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_workflow_result_service import (
    AgentTaskWorkflowResultService,
)
from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import (
    CheckpointRequest,
)


class _WebsocketRecorder:
    def __init__(self):
        self.messages = []

    async def broadcast(self, message):
        self.messages.append(message)


class _DbService:
    def __init__(self, record=None):
        self.record = record
        self.updates = []

    async def get_agent_task(self, agent_task_id):
        if self.record is not None and getattr(self.record, "id", None) == agent_task_id:
            return self.record
        return None

    async def update_agent_task_status(self, **kwargs):
        self.updates.append(kwargs)


class _StatusNotifier:
    def __init__(self):
        self.resumed = []

    async def send_checkpoint_resumed_status(self, **kwargs):
        self.resumed.append(kwargs)


class _CancellationRegistry:
    def register_active_task(self, *_args):
        pass

    def deregister_active_task(self, *_args):
        pass

    def is_cancelled(self, *_args):
        return False

    def get_cancellation_event(self, *_args):
        return None


def _result_messages(ws):
    return [m for m in ws.messages if m.get("event_type") == "agent_task_result"]


def _completed_record(**overrides):
    base = dict(
        id="task-1",
        original_prompt="do it",
        transcribed_prompt="do it",
        root_task_id="root-1",
        previous_task_id="prev-1",
        result_data={},
        execution_timeline=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_finalize_workflow_output_success_emits_single_result_and_sets_envelope():
    ws = _WebsocketRecorder()
    service = AgentTaskWorkflowResultService(db_service=_DbService(), websocket_manager=ws)
    curated = {
        "tool_execution_results": [{"success": True}],
        "final_envelope": {"success": True, "summary_text": "Done", "result_payload": {"files": []}},
        "overall_success": True,
        "todos_completed": 1,
        "total_todos": 1,
        "workflow_result": "Done",
    }
    request = SimpleNamespace(
        agent_task="do it",
        agent_task_id="task-1",
        root_task_id="root-1",
        previous_task_id="prev-1",
    )

    op = await service.finalize_workflow_output(curated, request)

    assert op.success is True
    assert op.data["final_envelope"]["summary_text"] == "Done"
    assert op.widget_content_delivered is True
    result_messages = _result_messages(ws)
    assert len(result_messages) == 1
    assert result_messages[0]["success"] is True
    assert result_messages[0]["result"] == "Done"
    assert result_messages[0]["root_task_id"] == "root-1"
    assert result_messages[0]["previous_task_id"] == "prev-1"


@pytest.mark.asyncio
async def test_exception_failure_persists_reasoning_at_top_level():
    db = _DbService(_completed_record())
    service = AgentTaskWorkflowResultService(db_service=db)
    request = SimpleNamespace(
        agent_task="do it",
        agent_task_id="task-1",
        root_task_id="root-1",
        previous_task_id="prev-1",
    )
    workflow_result = {
        "thinking_history": [{"iteration": 1, "text": "The tool failed.", "is_complete": True}],
        "tool_execution_results": [{"status": "failed", "error": "Tool failed"}],
    }

    operation_result = await service.finalize_workflow_output(workflow_result, request)
    await service.commit_terminal_outcome(
        agent_task_id="task-1",
        agent_task_record=_completed_record(),
        operation="multi_step_workflow",
        operation_result=operation_result,
    )

    persisted = db.updates[-1]["result_data"]
    assert db.updates[-1]["status"] == "failed"
    assert persisted["thinking_history"] == workflow_result["thinking_history"]
    assert "thinking_history" not in persisted.get("data", {})


@pytest.mark.asyncio
async def test_exception_recovery_hoists_reasoning_from_success_data():
    db = _DbService(_completed_record())
    service = AgentTaskWorkflowResultService(db_service=db)
    request = SimpleNamespace(
        agent_task="do it",
        agent_task_id="task-1",
        root_task_id="root-1",
        previous_task_id="prev-1",
    )
    workflow_result = {
        "thinking_history": [{"iteration": 1, "text": "Recover the result.", "is_complete": True}],
        "tool_execution_results": [{"status": "completed_with_post_error"}],
        "final_envelope": {"success": True, "summary_text": "Recovered", "result_payload": {}},
    }

    operation_result = await service.finalize_workflow_output(workflow_result, request)
    await service.commit_terminal_outcome(
        agent_task_id="task-1",
        agent_task_record=_completed_record(),
        operation="multi_step_workflow",
        operation_result=operation_result,
    )

    persisted = db.updates[-1]["result_data"]
    assert db.updates[-1]["status"] == "completed"
    assert persisted["thinking_history"] == workflow_result["thinking_history"]
    assert "thinking_history" not in persisted["data"]


@pytest.mark.asyncio
async def test_finalize_resumed_workflow_genuine_completion_persists_completed_and_broadcasts(monkeypatch):
    ws = _WebsocketRecorder()
    db = _DbService(_completed_record())
    import api.dependencies as deps

    monkeypatch.setattr(deps, "get_sqlite_knowledge_service", lambda: db)

    final_state = {
        "tool_execution_results": [{"success": True}],
        "final_envelope": {"success": True, "summary_text": "Resumed done", "result_payload": {}},
    }

    await finalize_resumed_workflow("task-1", final_state, ws)

    assert len(db.updates) == 1
    assert db.updates[0]["status"] == "completed"
    assert db.updates[0]["result_data"]["message"] == "Resumed done"
    # single terminal broadcast (finalizer_broadcasted skips the legacy fallback send)
    result_messages = _result_messages(ws)
    assert len(result_messages) == 1
    assert result_messages[0]["success"] is True
    assert result_messages[0]["result"] == "Resumed done"


@pytest.mark.asyncio
async def test_finalize_resumed_workflow_without_envelope_persists_failed(monkeypatch):
    ws = _WebsocketRecorder()
    db = _DbService(_completed_record(root_task_id=None, previous_task_id=None))
    import api.dependencies as deps

    monkeypatch.setattr(deps, "get_sqlite_knowledge_service", lambda: db)

    final_state = {"tool_execution_results": [{"success": True}]}  # no final_envelope

    await finalize_resumed_workflow("task-1", final_state, ws)

    assert len(db.updates) == 1
    assert db.updates[0]["status"] == "failed"
    result_messages = _result_messages(ws)
    assert len(result_messages) == 1
    assert result_messages[0]["success"] is False


@pytest.mark.asyncio
async def test_finalize_resumed_workflow_missing_record_is_noop(monkeypatch):
    ws = _WebsocketRecorder()
    db = _DbService(record=None)
    import api.dependencies as deps

    monkeypatch.setattr(deps, "get_sqlite_knowledge_service", lambda: db)

    await finalize_resumed_workflow(
        "missing",
        {"final_envelope": {"success": True, "summary_text": "x"}},
        ws,
    )

    assert db.updates == []
    assert _result_messages(ws) == []


@pytest.mark.asyncio
async def test_finalize_resumed_workflow_does_not_overwrite_parent_cancellation(monkeypatch):
    ws = _WebsocketRecorder()
    db = _DbService(_completed_record(status="cancelled"))
    import api.dependencies as deps

    monkeypatch.setattr(deps, "get_sqlite_knowledge_service", lambda: db)

    await finalize_resumed_workflow(
        "task-1",
        {
            "tool_execution_results": [{"success": True}],
            "final_envelope": {"success": True, "summary_text": "Late result"},
        },
        ws,
    )

    assert db.updates == []
    assert _result_messages(ws) == []


@pytest.mark.asyncio
async def test_finalize_resumed_workflow_empty_state_is_noop(monkeypatch):
    ws = _WebsocketRecorder()
    db = _DbService(record=_completed_record())
    import api.dependencies as deps

    monkeypatch.setattr(deps, "get_sqlite_knowledge_service", lambda: db)

    await finalize_resumed_workflow("task-1", None, ws)
    await finalize_resumed_workflow("task-1", {}, ws)

    assert db.updates == []
    assert _result_messages(ws) == []


@pytest.mark.asyncio
async def test_resume_another_checkpoint_does_not_finalize(monkeypatch):
    from api.services.agent_processing.lifecycle.execution_graph import agent_graph_runtime
    import api.dependencies as deps

    class _FakeApp:
        async def aget_state(self, _config):
            return SimpleNamespace(values={"user_agent_task": "orig", "tool_execution_results": []})

        async def ainvoke(self, _state, config=None):
            raise CheckpointRequest({"prompt": "Need more input"})

    @asynccontextmanager
    async def _fake_open():
        yield _FakeApp()

    monkeypatch.setattr(agent_graph_runtime, "_open_tool_enhanced_graph", _fake_open)
    monkeypatch.setattr(agent_graph_runtime, "_derive_thread_id", lambda *_a, **_k: "thread-1")
    monkeypatch.setattr(deps, "get_sqlite_knowledge_service", lambda: _DbService())

    finalize_calls = []

    async def _spy_finalize(agent_task_id, final_state, websocket_manager):
        finalize_calls.append(agent_task_id)

    monkeypatch.setattr(resume_terminal_finalizer, "finalize_resumed_workflow", _spy_finalize)

    ws = _WebsocketRecorder()
    handler = WorkflowCheckpointWorkflowService(websocket_manager=ws, status_notifier=None)

    result = await handler.resume_workflow("task-1", "some response")

    assert finalize_calls == []
    assert result.execution_results == [{"status": "awaiting_user_input", "needs_user_input": True}]
    # The re-raised checkpoint is surfaced to the frontend, not a terminal result.
    assert _result_messages(ws) == []
    assert any(m.get("event_type") == "collaborative_checkpoint_request" for m in ws.messages)


@pytest.mark.asyncio
async def test_resume_persists_processing_before_notifying_or_invoking_graph(monkeypatch):
    from api.services.agent_processing.lifecycle.execution_graph import agent_graph_runtime
    import api.dependencies as deps

    call_order = []

    class _FakeApp:
        async def aget_state(self, _config):
            return SimpleNamespace(values={"user_agent_task": "orig", "tool_execution_results": []})

        async def ainvoke(self, _state, config=None):
            call_order.append("invoke")
            return {"tool_execution_results": [], "final_envelope": {"summary_text": "Done"}}

    class _OrderedDbService(_DbService):
        async def update_agent_task_status(self, **kwargs):
            call_order.append("persist")
            await super().update_agent_task_status(**kwargs)

    @asynccontextmanager
    async def _fake_open():
        yield _FakeApp()

    async def _fake_finalize(*_args):
        call_order.append("finalize")

    db = _OrderedDbService()
    notifier = _StatusNotifier()
    monkeypatch.setattr(agent_graph_runtime, "_open_tool_enhanced_graph", _fake_open)
    monkeypatch.setattr(agent_graph_runtime, "_derive_thread_id", lambda *_a, **_k: "thread-1")
    monkeypatch.setattr(deps, "get_sqlite_knowledge_service", lambda: db)
    monkeypatch.setattr(resume_terminal_finalizer, "finalize_resumed_workflow", _fake_finalize)

    handler = WorkflowCheckpointWorkflowService(status_notifier=notifier)
    await handler.resume_workflow("task-1", "continue")

    assert db.updates == [{"agent_task_id": "task-1", "status": "processing"}]
    assert notifier.resumed == [{"agent_task_id": "task-1", "user_response": "continue"}]
    assert call_order == ["persist", "invoke", "finalize"]


@pytest.mark.asyncio
async def test_resume_rehydrates_live_coordinator_with_delegation_owner(monkeypatch):
    from api.services.agent_processing.lifecycle.execution_graph.agent_graph_nodes import (
        _get_run_coordinator,
    )
    from api.services.agent_processing.lifecycle.execution_graph.agent_progress_system import (
        PlanningState,
    )
    from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import (
        WorkflowCoordinator,
    )
    from api.services.agent_processing.lifecycle.execution_graph import agent_graph_runtime
    import api.dependencies as deps

    captured_states = []
    checkpoint_context = {
        "preserved_context_key": "preserved",
        "_workflow_coordinator": "<WorkflowCoordinator serialized placeholder>",
    }

    class _FakeApp:
        async def aget_state(self, _config):
            return SimpleNamespace(
                values={
                    "user_agent_task": "Delegate the approved inspection.",
                    "tool_execution_results": [],
                    "context": checkpoint_context,
                }
            )

        async def ainvoke(self, state, config=None):
            captured_states.append(state)
            return {
                "tool_execution_results": [],
                "final_envelope": {"success": True, "summary_text": "Done"},
            }

    @asynccontextmanager
    async def _fake_open():
        yield _FakeApp()

    async def _fake_finalize(*_args):
        return None

    delegation_owner = object()
    route_coordinator = WorkflowCoordinator(
        agent_task_submission_service=delegation_owner,
    )
    handler = WorkflowCheckpointWorkflowService()
    handler.workflow_coordinator = route_coordinator
    monkeypatch.setattr(agent_graph_runtime, "_open_tool_enhanced_graph", _fake_open)
    monkeypatch.setattr(agent_graph_runtime, "_derive_thread_id", lambda *_a, **_k: "thread-1")
    monkeypatch.setattr(deps, "get_sqlite_knowledge_service", lambda: _DbService())
    monkeypatch.setattr(resume_terminal_finalizer, "finalize_resumed_workflow", _fake_finalize)

    await handler.resume_workflow("task-1", "target-choice-1")

    resumed_context = captured_states[0]["context"]
    assert resumed_context["preserved_context_key"] == "preserved"
    assert resumed_context["agent_task_id"] == "task-1"
    assert resumed_context["_workflow_coordinator"] is route_coordinator
    assert checkpoint_context["_workflow_coordinator"] == "<WorkflowCoordinator serialized placeholder>"
    resumed_coordinator = _get_run_coordinator(
        PlanningState(user_agent_task="Continue the task", context=resumed_context)
    )
    assert resumed_coordinator is route_coordinator
    assert resumed_coordinator._agent_task_submission_service is delegation_owner


@pytest.mark.asyncio
async def test_resume_resolves_pending_provider_target_before_graph_invocation(monkeypatch):
    from api.services.agent_processing.lifecycle.execution_graph import agent_graph_runtime
    from api.services.agent_processing.lifecycle.runtime import checkpoint_workflow_service
    import api.dependencies as deps

    captured_states = []
    captured_resolution = {}

    class _FakeApp:
        async def aget_state(self, _config):
            return SimpleNamespace(
                values={
                    "user_agent_task": "Delegate the approved inspection.",
                    "tool_execution_results": [],
                }
            )

        async def ainvoke(self, state, config=None):
            captured_states.append(state)
            return {
                "tool_execution_results": [],
                "final_envelope": {"success": True, "summary_text": "Done"},
            }

    class _AgentTaskService:
        async def get_agent_task(self, agent_task_id):
            return SimpleNamespace(
                id=agent_task_id,
                root_task_id="root-1",
                result_data={},
            )

    class _AuthorizationRepository:
        async def get_single_pending_initial_authorization_for_task(self, **kwargs):
            assert kwargs == {
                "agent_task_id": "task-1",
                "root_task_id": "root-1",
            }
            return {"id": "pending-authorization-1"}

    class _ResolutionDbService(_DbService):
        def __init__(self):
            super().__init__()
            self.agent_task_service = _AgentTaskService()
            self.provider_discovery_proposal_repository = object()
            self.provider_target_authorization_repository = _AuthorizationRepository()
            self.provider_profile_repository = object()

    class _AuthorizationService:
        async def resolve_checkpoint_response(self, **kwargs):
            captured_resolution.update(kwargs)
            return {
                "id": "authorized-response-1",
                "status": "authorized",
                "reason_code": "user_selected_verified_target",
            }

    @asynccontextmanager
    async def _fake_open():
        yield _FakeApp()

    async def _fake_finalize(*_args):
        return None

    monkeypatch.setattr(agent_graph_runtime, "_open_tool_enhanced_graph", _fake_open)
    monkeypatch.setattr(agent_graph_runtime, "_derive_thread_id", lambda *_a, **_k: "thread-1")
    monkeypatch.setattr(deps, "get_sqlite_knowledge_service", _ResolutionDbService)
    monkeypatch.setattr(
        checkpoint_workflow_service,
        "_create_provider_target_authorization_service",
        lambda _knowledge_service: _AuthorizationService(),
    )
    monkeypatch.setattr(resume_terminal_finalizer, "finalize_resumed_workflow", _fake_finalize)

    await WorkflowCheckpointWorkflowService().resume_workflow(
        "task-1",
        "target-choice-1",
    )

    assert captured_resolution == {
        "agent_task_id": "task-1",
        "root_task_id": "root-1",
        "authorization_id": "pending-authorization-1",
        "response": "target-choice-1",
    }
    continuation = captured_states[0]["user_agent_task"]
    assert "authorization_id: authorized-response-1" in continuation
    assert "Call provider_catalog action='delegate' exactly once" in continuation
    assert "Do not list, describe, propose, authorize, or request another provider target." in continuation


def test_dismissed_checkpoint_continuation_requires_finalization_without_more_tools():
    from api.services.agent_processing.lifecycle.runtime.checkpoint_workflow_service import (
        USER_DISMISSED_CHECKPOINT_RESPONSE,
    )

    continuation = WorkflowCheckpointWorkflowService()._build_continuation_agent_task(
        original_prompt="Collect the report.",
        checkpoint_prompt="Should I send it?",
        tool_results=[],
        user_response=USER_DISMISSED_CHECKPOINT_RESPONSE,
        agent_task_id="task-1",
    )

    assert "[USER DISMISSED CHECKPOINT]" in continuation
    assert "Do NOT call any more tools." in continuation
    assert "Do NOT ask the user another question." in continuation
    assert "Emit your final_envelope now." in continuation


def test_provider_target_resolution_context_includes_only_authorization_id_and_source():
    continuation = WorkflowCheckpointWorkflowService()._build_continuation_agent_task(
        original_prompt="Open the approved target.",
        checkpoint_prompt="Choose a provider target.",
        tool_results=[{
            "checkpoint_data": {
                "metadata": {
                    "source": "provider_target_authorization",
                    "authorization_id": "authorization-123",
                    "provider_profile_id": "provider-should-not-leak",
                    "workspace_path": "/private/should-not-leak",
                }
            }
        }],
        user_response="Approve it.",
        agent_task_id="task-1",
    )

    assert "[CHECKPOINT RESOLUTION CONTEXT]" in continuation
    assert "authorization_id: authorization-123" in continuation
    assert "source: provider_target_authorization" in continuation
    assert "provider-should-not-leak" not in continuation
    assert "/private/should-not-leak" not in continuation


@pytest.mark.asyncio
async def test_provider_delegation_resume_marks_the_context_as_single_provider_continuation(
    monkeypatch,
):
    from api.services.agent_processing.lifecycle.execution_graph import agent_graph_runtime
    import api.dependencies as deps

    observed_states = []

    class _FakeApp:
        async def aget_state(self, _config):
            return SimpleNamespace(
                values={
                    "user_agent_task": "Read the project README.",
                    "context": {"existing_context": "preserved"},
                }
            )

        async def ainvoke(self, state, config=None):
            observed_states.append(state)
            return {
                "tool_execution_results": [{"success": True}],
                "final_envelope": {"success": True, "summary_text": "Done"},
            }

    @asynccontextmanager
    async def _fake_open():
        yield _FakeApp()

    async def _fake_finalize(*_args):
        return None

    db = _DbService(_completed_record(status="awaiting_provider_delegation"))
    monkeypatch.setattr(agent_graph_runtime, "_open_tool_enhanced_graph", _fake_open)
    monkeypatch.setattr(agent_graph_runtime, "_derive_thread_id", lambda *_a, **_k: "thread-1")
    monkeypatch.setattr(deps, "get_sqlite_knowledge_service", lambda: db)
    monkeypatch.setattr(resume_terminal_finalizer, "finalize_resumed_workflow", _fake_finalize)

    handler = WorkflowCheckpointWorkflowService()
    await handler.resume_workflow_after_provider_delegation(
        parent_agent_task_id="task-1",
        child_outcomes=[
            {
                "delegated_agent_run_id": "delegation-1",
                "executor_kind": "acp_provider",
                "terminal_status": "settled",
                "evidence_state": "provider_reported",
                "summary": "README was read.",
            }
        ],
    )

    assert observed_states[0]["context"] == {
        "existing_context": "preserved",
        "agent_task_id": "task-1",
        "websocket_manager": None,
        "provider_delegation_continuation": True,
    }
    assert "Every delegated child above is terminal" in observed_states[0]["user_agent_task"]


@pytest.mark.asyncio
async def test_clarification_execution_persists_processing_before_workflow():
    call_order = []
    record = _completed_record(
        transcribed_prompt="orig",
        app_name=None,
        screen_text=None,
        accumulated_artifacts={},
        clarifications=[{"text": "Use Path A"}],
    )

    class _OrderedDbService(_DbService):
        async def update_agent_task_status(self, **kwargs):
            call_order.append("persist")
            await super().update_agent_task_status(**kwargs)

    class _WorkflowResultService:
        async def execute_multi_step_workflow(self, _parameters, _request):
            call_order.append("execute")
            return SimpleNamespace(success=True, data={"needs_user_input": True})

    db = _OrderedDbService(record)
    service = AgentTaskProcessingService(
        db_service=db,
        cancellation_registry=_CancellationRegistry(),
        routing_service=SimpleNamespace(),
        workflow_result_service=_WorkflowResultService(),
    )

    await service.perform_clarification_routing("task-1")

    assert db.updates == [{"agent_task_id": "task-1", "status": "processing"}]
    assert call_order == ["persist", "execute"]


@pytest.mark.asyncio
async def test_provider_delegation_resume_defers_finalization_while_still_awaiting_delegated_agents(
    monkeypatch,
):
    from api.services.agent_processing.lifecycle.execution_graph import agent_graph_runtime
    import api.dependencies as deps

    class _FakeApp:
        async def aget_state(self, _config):
            return SimpleNamespace(
                values={"user_agent_task": "Read the project README.", "context": {}}
            )

        async def ainvoke(self, state, config=None):
            return {
                "tool_execution_results": [
                    {
                        "status": "awaiting_delegated_agents",
                        "needs_provider_delegation": True,
                        "delegation_id": "delegation-2",
                        "child_agent_task_id": "child-2",
                    }
                ],
            }

    @asynccontextmanager
    async def _fake_open():
        yield _FakeApp()

    finalize_calls = []

    async def _spy_finalize(*_args):
        finalize_calls.append(True)

    db = _DbService(_completed_record(status="awaiting_delegated_agents"))
    monkeypatch.setattr(agent_graph_runtime, "_open_tool_enhanced_graph", _fake_open)
    monkeypatch.setattr(agent_graph_runtime, "_derive_thread_id", lambda *_a, **_k: "thread-1")
    monkeypatch.setattr(deps, "get_sqlite_knowledge_service", lambda: db)
    monkeypatch.setattr(resume_terminal_finalizer, "finalize_resumed_workflow", _spy_finalize)

    handler = WorkflowCheckpointWorkflowService()
    await handler.resume_workflow_after_provider_delegation(
        parent_agent_task_id="task-1",
        child_outcomes=[
            {
                "delegated_agent_run_id": "delegation-1",
                "executor_kind": "acp_provider",
                "terminal_status": "settled",
                "evidence_state": "provider_reported",
                "summary": "First ACP turn finished; parent re-delegated another turn.",
            }
        ],
    )

    assert finalize_calls == []
    assert db.updates == [
        {"agent_task_id": "task-1", "status": "processing"},
        {"agent_task_id": "task-1", "status": "awaiting_delegated_agents"},
    ]
