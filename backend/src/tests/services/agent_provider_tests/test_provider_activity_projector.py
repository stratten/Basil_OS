"""Focused unit coverage for ProviderActivityProjector (Package 3B)."""

from __future__ import annotations

import json

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.submission.agent_task_processing.agent_task_routing_service import (
    AgentTaskRoutingService,
)
from api.services.agent_processing.lifecycle.submission.agent_task_processing.provider_activity_projector import (
    MAX_ACTIVITY_TEXT_BYTES,
    ProviderActivityProjector,
)


class _WebsocketRecorder:
    def __init__(self):
        self.messages = []

    async def broadcast(self, message):
        self.messages.append(message)


async def _make_projector(
    tmp_path,
    *,
    agent_task_id: str = "task-1",
    status: str = "processing",
    safe_activity_observer=None,
    workspace_root: str | None = None,
):
    db_service = SQLiteKnowledgeService(tmp_path / "activity.db")
    await db_service.store_agent_task(
        agent_task_id=agent_task_id,
        original_prompt="run provider",
        transcribed_prompt="run provider",
        status=status,
        root_task_id=agent_task_id,
    )
    websocket = _WebsocketRecorder()
    routing_service = AgentTaskRoutingService(db_service=db_service, websocket_manager=websocket)
    projector = ProviderActivityProjector(
        routing_service=routing_service,
        agent_task_id=agent_task_id,
        root_task_id=agent_task_id,
        previous_task_id=None,
        provider_run_id="run-1",
        safe_activity_observer=safe_activity_observer,
        workspace_root=workspace_root,
    )
    return db_service, websocket, projector


_ALLOWED_METADATA_KEYS = {
    "provider_activity_kind",
    "provider_run_id",
    "provider_session_id",
    "message_id",
    "raw_detail",
    "tool_call_id",
    "tool_kind",
    "tool_status",
    "location_count",
    "provider_locations",
    "terminal_id",
    "provider_state",
    "provider_stop_reason",
    "plan_step_count",
    "progress_step",
    "progress_phase",
    "progress_status",
}


@pytest.mark.asyncio
async def test_ordered_projection_persists_and_broadcasts_every_distinct_update(tmp_path):
    db_service, websocket, projector = await _make_projector(tmp_path)
    projector.bind_session("session-1")

    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {
            "sessionUpdate": "agent_thought_chunk",
            "messageId": "thought-1",
            "content": {"type": "text", "text": "Thinking it over."},
        },
    })
    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {
            "sessionUpdate": "agent_message_chunk",
            "messageId": "message-1",
            "content": {"type": "text", "text": "I inspected the workspace."},
        },
    })
    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {
            "sessionUpdate": "tool_call",
            "toolCallId": "tool-1",
            "title": "Inspect files",
            "kind": "read",
            "status": "pending",
        },
    })
    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "tool-1",
            "title": "Inspect files",
            "kind": "read",
            "status": "in_progress",
        },
    })
    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {
            "sessionUpdate": "tool_call_update",
            "toolCallId": "tool-1",
            "title": "Inspect files",
            "kind": "read",
            "status": "completed",
        },
    })
    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {
            "sessionUpdate": "terminal_output_chunk",
            "terminalId": "terminal-1",
            "output": "pytest passed",
        },
    })
    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {"sessionUpdate": "state_update", "state": "idle", "stopReason": "end_turn"},
    })
    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {"sessionUpdate": "plan", "entries": [{"content": "Step one"}, {"content": "Step two"}]},
    })

    record = await db_service.get_agent_task("task-1")
    timeline = record.execution_timeline or []
    ids = [entry.get("id") for entry in timeline]
    assert len(ids) == 6
    assert len(set(ids)) == 6

    tool_entries = [entry for entry in timeline if entry["id"].startswith("provider-tool-")]
    assert len(tool_entries) == 1
    assert tool_entries[0]["type"] == "tool_complete"
    assert tool_entries[0]["metadata"]["provider_activity_kind"] == "tool_call_update"

    assert len(websocket.messages) == 8
    for message in websocket.messages:
        assert message["event_type"] == "agent_task_progress"
        assert message["timeline_entry"]["id"] in ids

    for entry in timeline:
        assert set(entry["metadata"]) <= _ALLOWED_METADATA_KEYS


@pytest.mark.asyncio
async def test_v1_tool_call_creation_projects_a_standard_pending_tool_entry(tmp_path):
    db_service, websocket, projector = await _make_projector(tmp_path)
    projector.bind_session("session-1")

    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {
            "sessionUpdate": "tool_call",
            "toolCallId": "tool-v1",
            "title": "Read README",
            "kind": "read",
            "status": "pending",
        },
    })

    record = await db_service.get_agent_task("task-1")
    timeline = record.execution_timeline or []
    assert len(timeline) == 1
    assert timeline[0]["type"] == "tool_start"
    assert timeline[0]["metadata"]["provider_activity_kind"] == "tool_call"
    assert len(websocket.messages) == 1


@pytest.mark.asyncio
async def test_exact_replay_is_deduplicated_to_one_persisted_entry_and_broadcast(tmp_path):
    db_service, websocket, projector = await _make_projector(tmp_path)
    projector.bind_session("session-1")
    update = {
        "sessionId": "session-1",
        "update": {
            "sessionUpdate": "agent_message_chunk",
            "messageId": "message-1",
            "content": {"type": "text", "text": "duplicate content"},
        },
    }

    await projector.handle_session_update(update)
    await projector.handle_session_update({"sessionId": update["sessionId"], "update": dict(update["update"])})

    record = await db_service.get_agent_task("task-1")
    timeline = record.execution_timeline or []
    matching = [entry for entry in timeline if entry["id"].startswith("provider-message-chunk-")]
    assert len(matching) == 1
    assert len(websocket.messages) == 1


@pytest.mark.asyncio
async def test_text_is_sanitized_and_bounded(tmp_path):
    db_service, websocket, projector = await _make_projector(tmp_path)
    projector.bind_session("session-1")
    dirty_text = "line one\x00\x07\r\nline two" + ("z" * 9_000)

    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {
            "sessionUpdate": "agent_message_chunk",
            "messageId": "message-1",
            "content": {"type": "text", "text": dirty_text},
        },
    })

    record = await db_service.get_agent_task("task-1")
    entry = record.execution_timeline[0]
    assert "\x00" not in entry["body"]
    assert "\r" not in entry["body"]
    assert entry["body"].endswith("…[truncated]")
    assert len(entry["body"].encode("utf-8")) <= MAX_ACTIVITY_TEXT_BYTES


@pytest.mark.asyncio
async def test_isolation_and_malformed_input_never_raises_and_leaves_task_processing(tmp_path):
    db_service, websocket, projector = await _make_projector(tmp_path)

    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {"sessionUpdate": "agent_message_chunk", "content": "unbound"},
    })
    assert websocket.messages == []

    projector.bind_session("session-1")
    await projector.handle_session_update({
        "sessionId": "foreign-session",
        "update": {"sessionUpdate": "agent_message_chunk", "content": "foreign"},
    })
    assert websocket.messages == []

    await projector.handle_session_update({"sessionId": "session-1", "update": []})
    assert websocket.messages == []

    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {"sessionUpdate": "tool_call_update", "toolCallId": "", "status": "completed"},
    })
    assert len(websocket.messages) == 1
    assert websocket.messages[0]["timeline_entry"]["metadata"]["provider_activity_kind"] == "malformed_update"

    record = await db_service.get_agent_task("task-1")
    assert record.status == "processing"


@pytest.mark.asyncio
async def test_terminal_task_guard_blocks_further_persistence_and_broadcast(tmp_path):
    db_service, websocket, projector = await _make_projector(tmp_path, status="completed")
    projector.bind_session("session-1")

    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {
            "sessionUpdate": "agent_message_chunk",
            "messageId": "message-1",
            "content": {"type": "text", "text": "late activity"},
        },
    })

    record = await db_service.get_agent_task("task-1")
    assert not record.execution_timeline
    assert websocket.messages == []


@pytest.mark.asyncio
async def test_unknown_updates_redact_nested_sensitive_and_non_text_fields(tmp_path):
    db_service, websocket, projector = await _make_projector(tmp_path)
    projector.bind_session("session-1")

    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {
            "sessionUpdate": "future_update",
            "input": {"token": "input-secret"},
            "output": "output-secret",
            "_meta": {"token": "meta-secret"},
            "content": b"binary-secret",
            "nested": {"input": "nested-secret", "keep": "visible"},
        },
    })

    assert len(websocket.messages) == 1
    entry = websocket.messages[0]["timeline_entry"]
    serialized = json.dumps(entry, ensure_ascii=False)
    assert "input-secret" not in serialized
    assert "output-secret" not in serialized
    assert "meta-secret" not in serialized
    assert "binary-secret" not in serialized
    assert "nested-secret" not in serialized
    assert "visible" in entry["body"]


@pytest.mark.asyncio
async def test_atomic_terminal_guard_blocks_a_status_change_after_initial_read(tmp_path, monkeypatch):
    db_service, websocket, projector = await _make_projector(tmp_path)
    projector.bind_session("session-1")
    stale_record = await db_service.get_agent_task("task-1")
    original_get_agent_task = db_service.get_agent_task

    async def get_stale_record_after_terminal_transition(agent_task_id: str):
        await db_service.update_agent_task_status(agent_task_id=agent_task_id, status="completed")
        return stale_record

    monkeypatch.setattr(db_service, "get_agent_task", get_stale_record_after_terminal_transition)
    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {
            "sessionUpdate": "agent_message_chunk",
            "messageId": "message-1",
            "content": {"type": "text", "text": "late activity"},
        },
    })

    monkeypatch.setattr(db_service, "get_agent_task", original_get_agent_task)
    record = await db_service.get_agent_task("task-1")
    assert record.status == "completed"
    assert not record.execution_timeline
    assert websocket.messages == []


@pytest.mark.asyncio
async def test_safe_activity_observer_receives_bounded_message_once(tmp_path):
    observed: list[dict] = []

    async def observe(entry):
        observed.append(entry)

    _, _, projector = await _make_projector(
        tmp_path, safe_activity_observer=observe
    )
    projector.bind_session("session-1")

    update = {
        "sessionId": "session-1",
        "update": {
            "sessionUpdate": "agent_message",
            "messageId": "message-1",
            "content": {"type": "text", "text": "Supervisor-visible conclusion"},
        },
    }
    await projector.handle_session_update(update)
    await projector.handle_session_update(update)

    assert len(observed) == 1
    entry = observed[0]
    assert entry["body"] == "Supervisor-visible conclusion"
    assert entry["metadata"]["provider_run_id"] == "run-1"
    assert "_meta" not in entry
    assert "input" not in entry
    assert "output" not in entry


@pytest.mark.asyncio
async def test_safe_activity_observer_runs_before_timeline_publication_even_when_publish_returns_false(tmp_path):
    observed: list[dict] = []

    async def observe(entry):
        observed.append(entry)

    class _RejectingRoutingService:
        async def publish_activity_entry(self, **kwargs):
            return False

    db_service = SQLiteKnowledgeService(tmp_path / "activity-reject.db")
    await db_service.store_agent_task(
        agent_task_id="task-1",
        original_prompt="run provider",
        transcribed_prompt="run provider",
        status="processing",
        root_task_id="task-1",
    )
    projector = ProviderActivityProjector(
        routing_service=_RejectingRoutingService(),
        agent_task_id="task-1",
        root_task_id="task-1",
        previous_task_id=None,
        provider_run_id="run-1",
        safe_activity_observer=observe,
    )
    projector.bind_session("session-1")
    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {
            "sessionUpdate": "agent_message",
            "messageId": "message-1",
            "content": {"type": "text", "text": "Captured before publish rejection"},
        },
    })

    assert len(observed) == 1
    assert observed[0]["body"] == "Captured before publish rejection"


@pytest.mark.asyncio
async def test_tool_locations_normalize_only_paths_within_the_granted_root(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _, _, projector = await _make_projector(tmp_path, workspace_root=str(workspace))
    projector.bind_session("session-1")
    await projector.handle_session_update({
        "sessionId": "session-1",
        "update": {
            "sessionUpdate": "tool_call",
            "toolCallId": "tool-1",
            "status": "completed",
            "kind": "write",
            "title": "Write probe file",
            "locations": [
                str(workspace / "parent_graph_e2e_probe.txt"),
                {"path": str(workspace / "line_qualified.txt"), "line": 7},
                "/etc/passwd",
                "safe/../escape.txt",
                "file:///tmp/secret.txt",
                r"C:\outside\secret.txt",
            ],
        },
    })

    record = await SQLiteKnowledgeService(tmp_path / "activity.db").get_agent_task("task-1")
    entry = record.execution_timeline[-1]
    assert entry["metadata"]["provider_locations"] == [
        "parent_graph_e2e_probe.txt",
        "line_qualified.txt",
    ]
    assert "line_qualified.txt:7" in entry["body"]
