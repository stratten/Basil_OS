import asyncio
import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.agent_processing.lifecycle.runtime import workflow_coordinator as workflow_module
from api.services.agent_processing.lifecycle.runtime.workflow_coordinator import WorkflowCoordinator
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_cancellation import (
    AgentTaskCancellationRegistry,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_orchestrator import (
    AgentTaskOrchestrator,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_processing_service import (
    AgentTaskProcessingService,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_routing_service import (
    AgentTaskRoutingService,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_workflow_result_service import (
    AgentTaskWorkflowResultService,
)
from api.services.agent_processing.lifecycle.submission.agent_task_submission_service import (
    AgentTaskSubmissionService as PublicAgentTaskSubmissionService,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_submission_service import (
    AgentTaskSubmissionService as LifecycleAgentTaskSubmissionService,
)
import api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_workflow_result_service as workflow_result_module


class _NoopNotifier:
    def set_agent_task_id(self, agent_task_id):
        self.agent_task_id = agent_task_id

    def set_chain_identity(self, *, root_task_id=None, previous_task_id=None):
        self.root_task_id = root_task_id
        self.previous_task_id = previous_task_id

    async def send_status_update(self, *_args, **_kwargs):
        return None


class _NoopCheckpointHandler:
    async def enrich_context_with_session_history(self, _task, context, *, agent_task_id=None):
        return context

    def is_checkpoint_request(self, _exc):
        return False

    def save_agent_task_to_session_context(self, *_args, **_kwargs):
        return None


class _WebsocketRecorder:
    def __init__(self):
        self.messages = []

    async def broadcast(self, message):
        self.messages.append(message)


class _TimelineMutations:
    def __init__(self, db_service):
        self._db_service = db_service
        self.timelines = []

    async def update_execution_timeline(self, agent_task_id, timeline):
        self.timelines.append((agent_task_id, timeline))
        record = self._db_service.record
        if record is not None and record.id == agent_task_id:
            record.execution_timeline = timeline

    async def update_execution_timeline_if_active(self, agent_task_id, timeline):
        record = self._db_service.record
        if (
            record is None
            or record.id != agent_task_id
            or record.status in {"completed", "failed", "cancelled"}
        ):
            return False
        await self.update_execution_timeline(agent_task_id, timeline)
        return True


class _AgentTaskService:
    def __init__(self, db_service):
        self._mutations = _TimelineMutations(db_service)


class _DbService:
    def __init__(self, record=None):
        self.record = record
        self.updates = []
        self.callbacks = []
        self.agent_task_service = _AgentTaskService(self)
        self.provider_profile_repository = SimpleNamespace()
        self.provider_run_repository = SimpleNamespace()
        self.provider_interaction_repository = SimpleNamespace()
        self.provider_target_delegation_repository = SimpleNamespace()

    def register_agent_task_callback(self, callback):
        self.callbacks.append(callback)

    async def get_agent_task(self, agent_task_id):
        if self.record and self.record.id == agent_task_id:
            return self.record
        return None

    async def update_agent_task_status(self, **kwargs):
        self.updates.append(kwargs)

    async def get_agent_task_chain(self, _root_task_id):
        return []


class _FakeSubmissionService:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def process_agent_task(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class _FakeWorkflowResultService:
    def __init__(self, result, after_execute=None):
        self.result = result
        self.after_execute = after_execute
        self.sent_results = []
        self.commit_calls = []
        self.requests = []

    async def execute_multi_step_workflow(self, _parameters, _request):
        self.requests.append(_request)
        if self.after_execute:
            self.after_execute()
        return self.result

    async def commit_terminal_outcome(self, *, agent_task_id, agent_task_record, operation, operation_result):
        # Records the delegation from AgentTaskProcessingService._persist_success/_persist_failure.
        # The real committer performs the persist/broadcast; this stand-in only records the handoff,
        # so tests asserting no terminal persistence (e.g. awaiting-input) remain valid.
        self.commit_calls.append({
            "agent_task_id": agent_task_id,
            "operation": operation,
            "operation_result": operation_result,
        })

    def sanitize_for_json(self, obj):
        return obj

    async def send_result_message(self, **kwargs):
        self.sent_results.append(kwargs)

    def derive_failure_error_message(self, operation_result):
        return getattr(operation_result, "error_message", None) or "Operation failed"

    def merge_result_data(self, existing_data, new_data):
        merged = dict(existing_data or {})
        merged.update(new_data or {})
        return merged

    def has_successful_finalizer_result(self, _result_data):
        return False


@pytest.mark.asyncio
async def test_workflow_coordinator_seeds_itself_into_graph_context(monkeypatch):
    captured = {}

    async def fake_execute_tool_enhanced_workflow(agent_task, context):
        captured["agent_task"] = agent_task
        captured["context"] = context
        return {"execution_results": [], "success": True, "total_todos": 0, "todos_completed": 0}

    monkeypatch.setattr(workflow_module, "LANGGRAPH_AVAILABLE", True)
    monkeypatch.setattr(workflow_module, "execute_tool_enhanced_workflow", fake_execute_tool_enhanced_workflow)

    coordinator = WorkflowCoordinator()
    coordinator.session_context_service = _NoopCheckpointHandler()
    coordinator.status_notifier = _NoopNotifier()
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

    context = {"root_task_id": "root-1", "previous_task_id": "prev-1"}
    await coordinator._execute_with_tools("do the task", context, "task-1")

    assert captured["agent_task"] == "do the task"
    assert captured["context"]["_workflow_coordinator"] is coordinator
    assert captured["context"]["agent_task_id"] == "task-1"


@pytest.mark.asyncio
async def test_orchestrator_process_agent_task_delegates_to_submission_service():
    db_service = _DbService()
    orchestrator = AgentTaskOrchestrator(db_service=db_service, websocket_manager=None)
    response = {"success": True, "agent_task_id": "task-1", "status": "routing"}
    fake_submission = _FakeSubmissionService(response)
    orchestrator.submission_service = fake_submission

    result = await orchestrator.process_agent_task(
        "summarize this",
        agent_task_id="task-1",
        synchronous=True,
        reference_paths=["/tmp/example.txt"],
        model_id="model-1",
        conversation_id="conversation-1",
        origin_type="conversation",
        origin_id="conversation-1",
    )

    assert result == response
    assert fake_submission.calls == [{
        "agent_task": "summarize this",
        "display_prompt_markdown": None,
        "pre_captured_screenshot": None,
        "agent_task_id": "task-1",
        "synchronous": True,
        "chain_context": None,
        "reference_paths": ["/tmp/example.txt"],
        "model_id": "model-1",
        "conversation_id": "conversation-1",
        "provider_target": None,
        "origin_type": "conversation",
        "origin_id": "conversation-1",
        "todo_workspace_context": None,
        "todo_worker_context": None,
    }]


@pytest.mark.asyncio
async def test_lifecycle_submission_persists_todo_worker_context_in_durable_artifacts():
    stored_rows = []

    class FakeDb:
        async def store_agent_task(self, **kwargs):
            stored_rows.append(kwargs)

        async def update_agent_task_status(self, **_kwargs):
            return None

        async def update_agent_task_screen_context(self, **_kwargs):
            return None

    class FakeScreenContextService:
        async def capture_screen_context(self, _pre_captured_screenshot):
            return {}

    class FakeRoutingService:
        async def generate_agent_task_title(self, *_args):
            return None

    service = LifecycleAgentTaskSubmissionService(
        db_service=FakeDb(),
        screen_context_service=FakeScreenContextService(),
        routing_service=FakeRoutingService(),
        processing_service=SimpleNamespace(),
    )
    worker_context = {
        "source_agent_task_ids": ["source-1"],
        "source_excerpts": {"source-1": "Original research result."},
        "reference_paths": ["/tmp/research.md"],
    }

    result = await service.process_agent_task(
        "Complete the To-Do",
        agent_task_id="worker-1",
        origin_type="todo",
        origin_id="todo-1",
        reference_paths=["/tmp/research.md"],
        todo_worker_context=worker_context,
    )
    await asyncio.sleep(0)

    assert result["success"] is True
    assert stored_rows[0]["accumulated_artifacts"] == {
        "reference_paths": ["/tmp/research.md"],
        "todo_worker_context": worker_context,
    }
    assert stored_rows[0]["root_task_id"] is None
    assert stored_rows[0]["previous_task_id"] is None


@pytest.mark.asyncio
async def test_public_submission_facade_forwards_conversation_id_to_orchestrator():
    orchestrator = SimpleNamespace(
        process_agent_task=AsyncMock(return_value={"success": True, "status": "routing"})
    )
    submission = PublicAgentTaskSubmissionService(
        agent_task_orchestrator=orchestrator,
        db_service=_DbService(),
    )
    submission.broadcast = AsyncMock()

    await submission.process_agent_task_direct(
        "summarize this",
        agent_task_id="task-1",
        conversation_id="conversation-1",
        origin_type="conversation",
        origin_id="conversation-1",
        todo_worker_context={"source_agent_task_ids": ["source-1"]},
    )

    assert orchestrator.process_agent_task.await_args.kwargs["conversation_id"] == "conversation-1"
    assert orchestrator.process_agent_task.await_args.kwargs["origin_type"] == "conversation"
    assert orchestrator.process_agent_task.await_args.kwargs["origin_id"] == "conversation-1"
    assert orchestrator.process_agent_task.await_args.kwargs["todo_worker_context"] == {
        "source_agent_task_ids": ["source-1"]
    }
    submission.broadcast.assert_awaited_once_with(
        {
            "event_type": "agent_task_origin",
            "agent_task_id": "task-1",
            "root_task_id": None,
            "previous_task_id": None,
            "origin_type": "conversation",
            "origin_id": "conversation-1",
        }
    )


@pytest.mark.asyncio
async def test_store_agent_task_persists_origin_type_and_id(tmp_path) -> None:
    from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService

    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    await service.store_agent_task(
        agent_task_id="task-origin-1",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        origin_type="conversation",
        origin_id="conversation-1",
    )

    record = await service.get_agent_task("task-origin-1")

    assert record.origin_type == "conversation"
    assert record.origin_id == "conversation-1"
    summaries = await service.agent_task_service.list_recent_agent_task_summaries()
    assert summaries[0]["origin_type"] == "conversation"
    assert summaries[0]["origin_id"] == "conversation-1"
    search_summaries = await service.agent_task_service.search_agent_task_summaries(query="Prompt")
    assert search_summaries[0]["origin_type"] == "conversation"
    assert search_summaries[0]["origin_id"] == "conversation-1"


@pytest.mark.asyncio
async def test_search_agent_task_summaries_ranks_title_match_over_recent_incidental_match(tmp_path) -> None:
    """A title/prompt match must outrank a newer task where the query text
    only appears in a deep field (screen_text), even though the deep-field
    task is more recent. Regression test for the sidebar search
    deprioritization of direct string matches (relevance tiering)."""
    import sqlite3

    from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService

    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")

    await service.store_agent_task(
        agent_task_id="task-tier1-reykjavik",
        original_prompt="Plan the Reykjavik trip itinerary",
        transcribed_prompt="Plan the Reykjavik trip itinerary",
        title="Reykjavik trip planning",
    )
    await service.store_agent_task(
        agent_task_id="task-tier3-incidental",
        original_prompt="Summarize the open tabs",
        transcribed_prompt="Summarize the open tabs",
        title="Summarize the open tabs",
        screen_text="Browser tab titles: Flights to Reykjavik - booking.example.com",
    )

    raw_conn = sqlite3.connect(service.db_path)
    try:
        raw_conn.execute(
            "UPDATE agent_tasks SET timestamp = ?, last_turn_timestamp = ? WHERE id = ?",
            ("2020-01-01T00:00:00", "2020-01-01T00:00:00", "task-tier1-reykjavik"),
        )
        raw_conn.commit()
    finally:
        raw_conn.close()

    results = await service.agent_task_service.search_agent_task_summaries(query="Reykjavik")

    assert [row["id"] for row in results] == [
        "task-tier1-reykjavik",
        "task-tier3-incidental",
    ]


@pytest.mark.asyncio
async def test_store_agent_task_defaults_origin_to_none(tmp_path) -> None:
    from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService

    service = SQLiteKnowledgeService(tmp_path / "db.sqlite3")
    await service.store_agent_task(
        agent_task_id="task-origin-2",
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
    )

    record = await service.get_agent_task("task-origin-2")

    assert record.origin_type is None
    assert record.origin_id is None


def test_origin_migration_preserves_existing_summary_rows_without_backfill(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
    from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_tasks import (
        migrations as agent_task_migrations,
    )

    db_path = tmp_path / "db.sqlite3"
    SQLiteKnowledgeService(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP INDEX IF EXISTS idx_agent_tasks_conversation_roots")
        connection.execute("ALTER TABLE agent_tasks DROP COLUMN origin_type")
        connection.execute("ALTER TABLE agent_tasks DROP COLUMN origin_id")

    summary_backfill = AsyncMock()
    monkeypatch.setattr(agent_task_migrations, "backfill_agent_task_summaries", summary_backfill)

    migrated_service = SQLiteKnowledgeService(db_path)

    assert "origin_type" in migrated_service.schema["agent_tasks"]
    assert "origin_id" in migrated_service.schema["agent_tasks"]
    summary_backfill.assert_not_called()


@pytest.mark.asyncio
async def test_submission_broadcast_projects_correlated_progress_to_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.services.conversation.conversation_agent_turn_lifecycle as lifecycle_module
    import api.services.websocket_connection_manager as connection_module

    class _Connection:
        send_json = AsyncMock()

    projected_progress = AsyncMock()
    monkeypatch.setattr(
        lifecycle_module,
        "project_conversation_agent_task_progress",
        projected_progress,
    )
    monkeypatch.setattr(connection_module, "active_connections", {_Connection()})
    submission = PublicAgentTaskSubmissionService(
        agent_task_orchestrator=SimpleNamespace(),
        db_service=_DbService(),
    )

    await submission.broadcast(
        {
            "event_type": "agent_task_progress",
            "agent_task_id": "task-1",
            "timeline_entry": {"summary": "Inspecting active project files"},
        }
    )

    projected_progress.assert_awaited_once_with("task-1", "Inspecting active project files")


@pytest.mark.asyncio
async def test_wake_word_broadcast_projects_correlated_progress_to_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.services.conversation.conversation_agent_turn_lifecycle as lifecycle_module
    import api.services.wake_word.agent_task_orchestration.feedback_and_broadcast as broadcast_module
    import api.services.websocket_connection_manager as connection_module

    class _Connection:
        send_json = AsyncMock()

    projected_progress = AsyncMock()
    monkeypatch.setattr(
        lifecycle_module,
        "project_conversation_agent_task_progress",
        projected_progress,
    )
    monkeypatch.setattr(connection_module, "active_connections", {_Connection()})

    await broadcast_module.broadcast(
        SimpleNamespace(),
        {
            "event_type": "agent_task_progress",
            "agent_task_id": "task-1",
            "timeline_entry": {"summary": "Executing approved tool"},
        },
    )

    projected_progress.assert_awaited_once_with("task-1", "Executing approved tool")


@pytest.mark.asyncio
async def test_routing_service_preserves_chain_identity_in_progress_broadcasts():
    record = SimpleNamespace(id="task-1", execution_timeline=[])
    websocket = _WebsocketRecorder()
    db_service = _DbService(record)
    service = AgentTaskRoutingService(
        db_service=db_service,
        websocket_manager=websocket,
        is_cancelled=lambda _agent_task_id: False,
    )

    await service.send_progress_update(
        "Processing request",
        "started",
        agent_task_id="task-1",
        root_task_id="root-1",
        previous_task_id="prev-1",
    )

    message = websocket.messages[0]
    assert message["event_type"] == "agent_task_progress"
    assert message["step"] == "Processing request"
    assert message["status"] == "started"
    assert message["details"] is None
    assert message["agent_task_id"] == "task-1"
    assert message["root_task_id"] == "root-1"
    assert message["previous_task_id"] == "prev-1"
    assert message["timeline_entry"]["id"]
    assert message["timeline_entry"]["phase"] == "routing"
    assert message["timeline_entry"]["correlation_id"] == "task-1"


@pytest.mark.asyncio
async def test_publish_activity_entry_persists_before_broadcasting_with_chain_identity():
    record = SimpleNamespace(id="task-1", status="processing", execution_timeline=[])
    websocket = _WebsocketRecorder()
    db_service = _DbService(record)
    service = AgentTaskRoutingService(
        db_service=db_service,
        websocket_manager=websocket,
        is_cancelled=lambda _agent_task_id: False,
    )

    published = await service.publish_activity_entry(
        agent_task_id="task-1",
        root_task_id="root-1",
        previous_task_id="prev-1",
        entry={
            "id": "provider-tool-run-1-tool-1",
            "type": "tool_start",
            "content": "Inspect project files",
            "summary": "Inspect project files",
            "body": "Inspect project files",
            "detail_kind": "tool_input",
            "metadata": {"tool_status": "in_progress"},
            "streaming": False,
        },
    )

    assert published is True
    assert record.execution_timeline[0]["id"] == "provider-tool-run-1-tool-1"
    assert record.execution_timeline[0]["phase"] == "provider"
    assert record.execution_timeline[0]["correlation_id"] == "task-1"

    message = websocket.messages[0]
    assert message["event_type"] == "agent_task_progress"
    assert message["agent_task_id"] == "task-1"
    assert message["root_task_id"] == "root-1"
    assert message["previous_task_id"] == "prev-1"
    assert message["timeline_entry"]["id"] == "provider-tool-run-1-tool-1"


@pytest.mark.asyncio
async def test_publish_activity_entry_replaces_same_id_entry_and_rejects_terminal_task():
    record = SimpleNamespace(id="task-1", status="processing", execution_timeline=[])
    websocket = _WebsocketRecorder()
    db_service = _DbService(record)
    service = AgentTaskRoutingService(
        db_service=db_service,
        websocket_manager=websocket,
        is_cancelled=lambda _agent_task_id: False,
    )

    await service.publish_activity_entry(
        agent_task_id="task-1",
        root_task_id=None,
        previous_task_id=None,
        entry={
            "id": "provider-tool-run-1-tool-1",
            "type": "tool_start",
            "content": "Inspect project files",
            "summary": "Inspect project files",
            "body": "Inspect project files",
            "detail_kind": "tool_input",
            "metadata": {"tool_status": "in_progress"},
            "streaming": False,
        },
    )
    await service.publish_activity_entry(
        agent_task_id="task-1",
        root_task_id=None,
        previous_task_id=None,
        entry={
            "id": "provider-tool-run-1-tool-1",
            "type": "tool_complete",
            "content": "Inspect project files",
            "summary": "Inspect project files",
            "body": "Inspect project files",
            "detail_kind": "tool_result",
            "metadata": {"tool_status": "completed"},
            "streaming": False,
        },
    )

    assert len(record.execution_timeline) == 1
    assert record.execution_timeline[0]["type"] == "tool_complete"
    assert len(websocket.messages) == 2

    record.status = "completed"
    published = await service.publish_activity_entry(
        agent_task_id="task-1",
        root_task_id=None,
        previous_task_id=None,
        entry={
            "id": "provider-message-run-1-message-1",
            "type": "step",
            "content": "late update",
            "summary": "Provider message",
            "body": "late update",
            "detail_kind": "step_note",
            "metadata": {},
            "streaming": False,
        },
    )

    assert published is False
    assert len(record.execution_timeline) == 1
    assert len(websocket.messages) == 2


@pytest.mark.asyncio
async def test_processing_service_preserves_awaiting_input_status():
    record = SimpleNamespace(
        id="task-1",
        operation_parameters={"operation": "multi_step_workflow", "parameters": {}},
        root_task_id="root-1",
        previous_task_id="prev-1",
        transcribed_prompt="Need input",
        app_name="Basil",
        screen_text="",
        accumulated_artifacts={"conversation_id": "conversation-1"},
        result_data={},
        execution_timeline=[],
    )
    db_service = _DbService(record)
    cancellation = AgentTaskCancellationRegistry()
    routing_service = AgentTaskRoutingService(db_service=db_service)
    workflow_service = _FakeWorkflowResultService(
        SimpleNamespace(success=True, data={"needs_user_input": True}, widget_content_delivered=False)
    )
    service = AgentTaskProcessingService(
        db_service=db_service,
        cancellation_registry=cancellation,
        routing_service=routing_service,
        workflow_result_service=workflow_service,
    )

    await service.perform_processing("task-1")

    assert db_service.updates == []
    assert workflow_service.sent_results == []
    # perform_processing delegates terminal handling to the shared committer; the committer
    # (real implementation) no-ops for needs_user_input, preserving awaiting_user_input status.
    assert len(workflow_service.commit_calls) == 1
    assert workflow_service.commit_calls[0]["operation"] == "multi_step_workflow"
    assert workflow_service.requests[0].conversation_id == "conversation-1"


@pytest.mark.asyncio
async def test_workflow_result_service_broadcasts_final_envelope_with_chain_identity():
    websocket = _WebsocketRecorder()
    service = AgentTaskWorkflowResultService(
        db_service=_DbService(),
        websocket_manager=websocket,
        is_cancelled=lambda _agent_task_id: False,
    )
    result_data = {
        "success": True,
        "final_envelope": {
            "success": True,
            "summary_text": "Done",
            "result_payload": {"files": []},
        },
    }
    request = SimpleNamespace(
        agent_task_id="task-1",
        root_task_id="root-1",
        previous_task_id="prev-1",
    )

    await service.broadcast_final_envelope_if_present(result_data, request)

    assert result_data["finalizer_broadcasted"] is True
    assert websocket.messages == [{
        "event_type": "agent_task_result",
        "success": True,
        "result": "Done",
        "error": None,
        "operation": "multi_step_workflow",
        "agent_task_id": "task-1",
        "result_payload": {"files": []},
        "root_task_id": "root-1",
        "previous_task_id": "prev-1",
    }]


@pytest.mark.asyncio
async def test_cancellation_during_processing_skips_final_persistence():
    record = SimpleNamespace(
        id="task-1",
        operation_parameters={"operation": "multi_step_workflow", "parameters": {}},
        root_task_id="root-1",
        previous_task_id="prev-1",
        transcribed_prompt="Cancel me",
        app_name="Basil",
        screen_text="",
        accumulated_artifacts={},
        result_data={},
        execution_timeline=[],
    )
    db_service = _DbService(record)
    cancellation = AgentTaskCancellationRegistry()
    routing_service = AgentTaskRoutingService(db_service=db_service)

    def cancel_during_workflow():
        cancellation.mark_cancelled(["task-1"])

    workflow_service = _FakeWorkflowResultService(
        SimpleNamespace(success=True, data={"final_envelope": {"success": True}}, widget_content_delivered=True),
        after_execute=cancel_during_workflow,
    )
    service = AgentTaskProcessingService(
        db_service=db_service,
        cancellation_registry=cancellation,
        routing_service=routing_service,
        workflow_result_service=workflow_service,
    )

    await service.perform_processing("task-1")

    assert db_service.updates == []
    assert workflow_service.sent_results == []


@pytest.mark.asyncio
async def test_cancellation_tombstone_cancels_task_registered_later():
    cancellation = AgentTaskCancellationRegistry()
    cancellation.mark_cancelled(["task-late"])
    started = asyncio.Event()

    async def wait_forever():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(wait_forever())
    await started.wait()
    cancellation.register_active_task("task-late", task)
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_root_alias_cancels_only_matching_active_turn():
    cancellation = AgentTaskCancellationRegistry()
    turn_started = asyncio.Event()
    unrelated_started = asyncio.Event()

    async def wait_forever(started):
        started.set()
        await asyncio.Event().wait()

    turn_task = asyncio.create_task(wait_forever(turn_started))
    unrelated_task = asyncio.create_task(wait_forever(unrelated_started))
    await asyncio.gather(turn_started.wait(), unrelated_started.wait())
    cancellation.register_active_task("turn-2", turn_task, aliases=("root-1",))
    cancellation.register_active_task("other-turn", unrelated_task, aliases=("other-root",))
    cancellation.mark_cancelled(["root-1"])

    assert cancellation.cancel_active_task("root-1") is True
    with pytest.raises(asyncio.CancelledError):
        await turn_task
    assert unrelated_task.done() is False
    unrelated_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await unrelated_task


def test_cross_thread_cancellation_schedules_on_owner_loop():
    cancellation = AgentTaskCancellationRegistry()
    registered = threading.Event()
    finished = threading.Event()

    def run_loop():
        async def worker():
            task = asyncio.current_task()
            cancellation.register_active_task("thread-task", task)
            registered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancellation.deregister_active_task("thread-task", task)
                finished.set()

        try:
            asyncio.run(worker())
        except asyncio.CancelledError:
            pass

    thread = threading.Thread(target=run_loop)
    thread.start()
    assert registered.wait(timeout=2)
    cancellation.mark_cancelled(["thread-task"])
    assert cancellation.cancel_active_task("thread-task") is True
    assert finished.wait(timeout=2)
    thread.join(timeout=2)
    assert thread.is_alive() is False


@pytest.mark.asyncio
async def test_terminal_committer_does_not_broadcast_when_cancelled_status_wins():
    class _RejectingTerminalDb(_DbService):
        async def update_agent_task_status_if_active(self, **kwargs):
            self.updates.append(kwargs)
            return False

    db_service = _RejectingTerminalDb()
    websocket = _WebsocketRecorder()
    service = AgentTaskWorkflowResultService(
        db_service=db_service,
        websocket_manager=websocket,
    )
    service.send_result_message = AsyncMock()
    operation_result = SimpleNamespace(
        success=True,
        data={},
        user_feedback="Late success",
        widget_content_delivered=False,
    )

    await service.commit_terminal_outcome(
        agent_task_id="task-cancelled",
        agent_task_record=SimpleNamespace(root_task_id=None, previous_task_id=None),
        operation="direct",
        operation_result=operation_result,
    )

    assert db_service.updates[0]["status"] == "completed"
    service.send_result_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_atomic_chain_cancellation_updates_only_active_members(tmp_path):
    from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService

    service = SQLiteKnowledgeService(tmp_path / "atomic-cancellation.db")
    await service.store_agent_task(
        agent_task_id="root-active",
        original_prompt="Root",
        transcribed_prompt="Root",
        status="processing",
    )
    await service.store_agent_task(
        agent_task_id="child-active",
        original_prompt="Child",
        transcribed_prompt="Child",
        status="paused",
        root_task_id="root-active",
        previous_task_id="root-active",
        chain_sequence_number=1,
    )
    await service.store_agent_task(
        agent_task_id="child-completed",
        original_prompt="Completed",
        transcribed_prompt="Completed",
        status="completed",
        root_task_id="root-active",
        previous_task_id="child-active",
        chain_sequence_number=2,
    )

    changed_ids = await service.cancel_agent_tasks_if_active(
        ["root-active", "child-active", "child-completed"],
        {"cancelled": True, "cancellation_reason": "test"},
    )

    assert set(changed_ids) == {"root-active", "child-active"}
    assert (await service.get_agent_task("root-active")).status == "cancelled"
    assert (await service.get_agent_task("child-active")).status == "cancelled"
    assert (await service.get_agent_task("child-completed")).status == "completed"


@pytest.mark.asyncio
async def test_durable_cancellation_preempts_before_first_database_read():
    from api.services.agent_processing.lifecycle.submission.agent_task_submission_service import (
        AgentTaskSubmissionService,
    )

    stages = []

    class _Orchestrator:
        def request_agent_task_preemption(self, agent_task_id):
            stages.append(("preempt", agent_task_id))
            return True

        async def cancel_agent_task(self, agent_task_id):
            stages.append(("cleanup", agent_task_id))
            return True

    class _Db:
        async def get_agent_task(self, agent_task_id):
            assert stages == [("preempt", agent_task_id)]
            stages.append(("db_read", agent_task_id))
            return None

    service = AgentTaskSubmissionService(
        agent_task_orchestrator=_Orchestrator(),
        db_service=_Db(),
    )

    await service.cancel_agent_task_durably("provisional-task", "test")

    assert stages == [
        ("preempt", "provisional-task"),
        ("db_read", "provisional-task"),
        ("cleanup", "provisional-task"),
    ]


def test_clear_cancelled_is_scoped_to_exact_inactive_turn():
    cancellation = AgentTaskCancellationRegistry()
    cancellation.mark_cancelled(["turn-1", "turn-2"])

    cancellation.clear_cancelled("turn-1")

    assert cancellation.is_cancelled("turn-1") is False
    assert cancellation.is_cancelled("turn-2") is True
    assert cancellation.get_cancellation_event("turn-1").is_set() is False


@pytest.mark.asyncio
async def test_provider_run_processing_exception_preserves_provider_operation_identity():
    record = SimpleNamespace(
        id="provider-task-1",
        operation_parameters={
            "operation": "provider_run",
            "parameters": {"provider_target": {"provider_profile_id": "profile-1"}},
        },
        root_task_id="provider-task-1",
        previous_task_id=None,
        transcribed_prompt="Run the provider",
        app_name="Basil",
        screen_text="",
        accumulated_artifacts={},
        result_data={},
        execution_timeline=[],
    )
    db_service = _DbService(record)
    cancellation = AgentTaskCancellationRegistry()
    routing_service = AgentTaskRoutingService(db_service=db_service)
    workflow_service = _FakeWorkflowResultService(None)

    class _FailingProviderRunService:
        async def run_provider_task(self, **_kwargs):
            raise RuntimeError("provider service failed")

    service = AgentTaskProcessingService(
        db_service=db_service,
        cancellation_registry=cancellation,
        routing_service=routing_service,
        workflow_result_service=workflow_service,
        provider_run_service=_FailingProviderRunService(),
    )

    await service.perform_processing("provider-task-1")

    assert db_service.updates[-1]["result_data"]["failure_info"]["operation_type"] == "provider_run"
    assert workflow_service.sent_results[-1]["operation"] == "provider_run"


def test_routing_request_restores_conversation_id_from_durable_artifacts():
    record = SimpleNamespace(
        id="task-1",
        transcribed_prompt="Delegated task",
        app_name=None,
        screen_text="",
        root_task_id=None,
        previous_task_id=None,
        accumulated_artifacts={"conversation_id": "conversation-1"},
        result_data=None,
    )
    request = AgentTaskRoutingService(db_service=_DbService()).build_routing_request(record)

    assert request.conversation_id == "conversation-1"


def test_routing_request_restores_todo_worker_context_from_durable_artifacts():
    worker_context = {
        "source_agent_task_ids": ["source-1"],
        "source_excerpts": {"source-1": "Original research result."},
        "reference_paths": ["/tmp/research.md"],
    }
    record = SimpleNamespace(
        id="worker-1",
        transcribed_prompt="Complete the To-Do",
        app_name=None,
        screen_text="",
        root_task_id=None,
        previous_task_id=None,
        accumulated_artifacts={
            "todo_worker_context": worker_context,
            "reference_paths": ["/tmp/research.md"],
        },
        result_data=None,
    )

    request = AgentTaskRoutingService(db_service=_DbService()).build_routing_request(record)

    assert request.todo_worker_context == worker_context
    assert request.reference_paths == ["/tmp/research.md"]
    assert request.root_task_id is None
    assert request.previous_task_id is None


@pytest.mark.asyncio
async def test_workflow_context_forwards_conversation_id_to_graph(monkeypatch):
    captured = {}

    class FakeCoordinator:
        def __init__(self, websocket_manager=None, agent_task_submission_service=None):
            assert websocket_manager is None
            assert agent_task_submission_service is None

        async def _execute_with_tools(self, agent_task, context, agent_task_id):
            captured["agent_task"] = agent_task
            captured["context"] = context
            captured["agent_task_id"] = agent_task_id
            return {"success": True}

    service = AgentTaskWorkflowResultService(
        db_service=_DbService(),
        websocket_manager=None,
    )
    service.finalize_workflow_output = AsyncMock(return_value=SimpleNamespace(success=True))
    monkeypatch.setattr(workflow_result_module, "WorkflowCoordinator", FakeCoordinator)

    result = await service.execute_multi_step_workflow(
        {},
        SimpleNamespace(
            agent_task="Delegated task",
            active_app="Basil",
            screen_text="",
            full_screen_text="",
            clarification_agent_task=None,
            root_task_id=None,
            previous_task_id=None,
            reference_paths=None,
            model_id=None,
            conversation_id="conversation-1",
            cancel_event=None,
            agent_task_id="task-1",
        ),
    )

    assert result.success is True
    assert captured["agent_task"] == "Delegated task"
    assert captured["agent_task_id"] == "task-1"
    assert captured["context"]["conversation_id"] == "conversation-1"


@pytest.mark.asyncio
async def test_workflow_context_restores_todo_worker_context_without_source_task_chain(monkeypatch):
    worker_context = {
        "source_agent_task_ids": ["source-1"],
        "source_excerpts": {"source-1": "Original research result."},
        "reference_paths": ["/tmp/research.md"],
    }
    record = SimpleNamespace(
        id="worker-1",
        accumulated_artifacts={"todo_worker_context": worker_context},
        root_task_id=None,
        previous_task_id=None,
        result_data=None,
    )
    captured = {}

    class FakeCoordinator:
        def __init__(self, websocket_manager=None, agent_task_submission_service=None):
            assert websocket_manager is None
            assert agent_task_submission_service is None

        async def _execute_with_tools(self, agent_task, context, agent_task_id):
            captured["context"] = context
            return {"success": True}

    service = AgentTaskWorkflowResultService(
        db_service=_DbService(record),
        websocket_manager=None,
    )
    service.finalize_workflow_output = AsyncMock(return_value=SimpleNamespace(success=True))
    monkeypatch.setattr(workflow_result_module, "WorkflowCoordinator", FakeCoordinator)

    await service.execute_multi_step_workflow(
        {},
        SimpleNamespace(
            agent_task="Complete the To-Do",
            active_app="Basil",
            screen_text="",
            full_screen_text="",
            clarification_agent_task=None,
            root_task_id=None,
            previous_task_id=None,
            reference_paths=["/tmp/research.md"],
            model_id=None,
            conversation_id=None,
            todo_worker_context=None,
            cancel_event=None,
            agent_task_id="worker-1",
        ),
    )

    assert captured["context"]["todo_worker_context"] == worker_context
    assert captured["context"]["chain_context"]["todo_worker_context"] == worker_context
    assert "chain_agentTasks" not in captured["context"]["chain_context"]
    assert captured["context"]["root_task_id"] is None
    assert captured["context"]["previous_task_id"] is None


@pytest.mark.asyncio
async def test_orchestrator_constructs_provider_delegation_result_bridge():
    orchestrator = AgentTaskOrchestrator(db_service=SimpleNamespace(
        provider_target_delegation_repository=SimpleNamespace(),
        agent_task_service=SimpleNamespace(),
        provider_profile_repository=SimpleNamespace(),
        provider_run_repository=SimpleNamespace(),
        provider_interaction_repository=SimpleNamespace(),
        register_agent_task_callback=lambda _cb: None,
        get_agent_task=AsyncMock(return_value=None),
        get_agent_task_chain=AsyncMock(return_value=[]),
    ))
    assert orchestrator.provider_delegation_result_bridge is not None
    assert orchestrator.routing_service._provider_delegation_result_bridge is orchestrator.provider_delegation_result_bridge
    assert (
        orchestrator.workflow_coordinator._agent_task_submission_service.delegated_agent_controller
        is orchestrator.delegated_agent_controller
    )
    assert (
        orchestrator.delegated_agent_controller._evidence_capture
        is orchestrator.delegated_agent_evidence_capture_service
    )
    assert (
        orchestrator.delegated_agent_controller._evidence_service
        is orchestrator.delegated_agent_evidence_service
    )
    assert (
        orchestrator.provider_run_service._evidence_capture
        is orchestrator.delegated_agent_evidence_capture_service
    )
    assert (
        orchestrator.delegated_agent_controller._workspace_verifier
        is orchestrator.delegated_agent_workspace_verifier
    )


@pytest.mark.asyncio
async def test_publish_delegated_provider_state_broadcasts_report_cards(tmp_path):
    from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService

    db_service = SQLiteKnowledgeService(tmp_path / "routing-cards.db")
    websocket = _WebsocketRecorder()
    service = AgentTaskRoutingService(db_service=db_service, websocket_manager=websocket)

    await db_service.store_agent_task(
        agent_task_id="parent-cards",
        original_prompt="Delegate",
        transcribed_prompt="Delegate",
        status="processing",
        root_task_id="parent-cards",
    )
    await db_service.store_agent_task(
        agent_task_id="child-cards",
        original_prompt="Run provider",
        transcribed_prompt="Run provider",
        status="routing",
        root_task_id="parent-cards",
    )
    await db_service.delegated_agent_repository.reserve_child_agent_task(
        parent_agent_task_id="parent-cards",
        root_task_id="parent-cards",
        child_agent_task_id="child-cards",
        executor_kind="acp_provider",
        strategic_assessment={
            "parallelism_reason": "fixture",
            "independence_rationale": "fixture",
            "expected_benefit": "fixture",
            "parent_work_can_continue": False,
            "child_cannot_delegate": True,
        },
    )
    run = await db_service.delegated_agent_repository.admit_reserved_run(
        child_agent_task_id="child-cards",
        admitted_scope={"read_only": False},
        evidence_policy={"required": "provider_reported"},
    )
    await db_service.delegated_agent_evidence_repository.append_evidence(
        delegated_agent_run_id=run["id"],
        delegated_agent_turn_id=None,
        source_event_key="routing-card",
        source="provider_activity",
        kind="message",
        provenance="provider_reported",
        verification_state="not_applicable",
        summary="Provider completed this turn.",
        structured_data={},
        artifact_locator=None,
    )
    websocket = _WebsocketRecorder()
    service = AgentTaskRoutingService(db_service=db_service, websocket_manager=websocket)

    published = await service.publish_delegated_provider_state(
        parent_agent_task_id="parent-cards",
        root_task_id="parent-cards",
        delegation_id="delegation-1",
        state="running",
        message="Provider is running.",
    )

    assert published is True
    card_messages = [message for message in websocket.messages if message["event_type"] == "delegated_provider_report_cards"]
    assert len(card_messages) == 1
    payload = card_messages[0]["delegated_provider_report_cards"]
    assert payload["parent_agent_task_id"] == "parent-cards"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["evidence_count"] == 1


@pytest.mark.asyncio
async def test_report_card_projection_failure_does_not_block_provider_state_publish():
    record = SimpleNamespace(id="parent-cards", status="processing", execution_timeline=[])
    db_service = _DbService(record)
    websocket = _WebsocketRecorder()
    service = AgentTaskRoutingService(db_service=db_service, websocket_manager=websocket)

    published = await service.publish_delegated_provider_state(
        parent_agent_task_id="parent-cards",
        root_task_id="parent-cards",
        delegation_id="delegation-1",
        state="running",
        message="Provider is running.",
    )

    assert published is True
    card_messages = [message for message in websocket.messages if message["event_type"] == "delegated_provider_report_cards"]
    assert len(card_messages) == 1
    assert card_messages[0]["delegated_provider_report_cards"]["items"] == []
