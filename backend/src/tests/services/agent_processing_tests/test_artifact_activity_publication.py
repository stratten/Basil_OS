from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.execution_graph.activity_progress_callback import (
    ActivityProgressCallbackHandler,
)
from api.services.agent_processing.lifecycle.execution_graph.agent_execution_core import (
    setup_live_callbacks,
)
from api.services.agent_processing.lifecycle.runtime import artifact_activity_publication
from api.services.agent_processing.lifecycle.runtime.workflow_status_notifier import (
    WorkflowStatusNotifier,
)


class RecordingWebsocket:
    def __init__(self, service: SQLiteKnowledgeService) -> None:
        self.service = service
        self.messages: list[dict[str, Any]] = []
        self.timelines_at_broadcast: list[list[dict[str, Any]]] = []

    async def broadcast(self, message: dict[str, Any]) -> None:
        record = await self.service.get_agent_task(message["agent_task_id"])
        self.timelines_at_broadcast.append(list(record.execution_timeline or []))
        self.messages.append(message)


class CallbackNotifier:
    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []
        self.progress: list[dict[str, Any]] = []
        self.details: list[dict[str, Any]] = []
        self.artifacts: list[dict[str, Any]] = []

    async def send_dynamic_step_added(self, **kwargs: Any) -> str:
        self.added.append(kwargs)
        return "step-direct-write"

    async def send_dynamic_step_updated(self, **kwargs: Any) -> None:
        self.updated.append(kwargs)

    async def send_agent_progress_update(self, **kwargs: Any) -> None:
        self.progress.append(kwargs)

    async def send_step_detail_update(self, **kwargs: Any) -> None:
        self.details.append(kwargs)

    async def publish_agent_task_artifact(self, **kwargs: Any) -> bool:
        self.artifacts.append(kwargs)
        return True


def artifact(
    *,
    lifecycle: str = "verified",
    artifact_id: str = "file-0123456789abcdef01234567",
) -> dict[str, Any]:
    summary = (
        "Verified 13 bytes; SHA-256 " + "a" * 64 + "."
        if lifecycle == "verified"
        else "Verification failed: postcondition_verification_failed."
    )
    return {
        "artifact_id": artifact_id,
        "display_name": "report.md",
        "local_path": "/tmp/report.md",
        "artifact_kind": "file",
        "operation": "create",
        "lifecycle": lifecycle,
        "preview": {"capability": "unknown"},
        "verification": {"status": lifecycle, "summary": summary},
    }


async def store_processing_task(service: SQLiteKnowledgeService, task_id: str) -> None:
    await service.store_agent_task(
        agent_task_id=task_id,
        original_prompt="Create a report",
        transcribed_prompt="Create a report",
        status="processing",
    )


@pytest.mark.asyncio
async def test_persists_selected_artifact_before_broadcast_and_discards_raw_output(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "artifact-publication.db")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    await store_processing_task(service, "task-1")
    websocket = RecordingWebsocket(service)
    notifier = WorkflowStatusNotifier(
        websocket_manager=websocket,
        agent_task_id="task-1",
        root_task_id="root-1",
        previous_task_id="previous-1",
    )

    if os.path.exists("/tmp/report.md"):
        os.remove("/tmp/report.md")
    published = await notifier.publish_agent_task_artifact(
        output=json.dumps(
            {
                "truncated": True,
                "content_preview": "private direct-write content",
                "agent_task_artifact": {
                    **artifact(),
                    "content": "private direct-write content",
                },
            }
        ),
        source_step_id="step-1",
    )

    assert published is True
    record = await service.get_agent_task("task-1")
    persisted = record.execution_timeline
    assert len(persisted) == 1
    assert persisted[0]["id"] == "artifact_file-0123456789abcdef01234567"
    persisted_artifact = persisted[0]["metadata"]["artifact"]
    assert persisted_artifact == {
        **artifact(),
        "source_timeline_entry_id": "artifact_file-0123456789abcdef01234567",
        "source_step_id": "step-1",
        "review": {
            "revision": None,
            "revision_count": 0,
            "snapshot_status": "unavailable",
            "unavailable_reason": "Snapshot unavailable: file could not be read.",
        },
        "lineage": {
            "origin_path": "/tmp/report.md",
            "current_path": "/tmp/report.md",
            "state": "current",
            "transitions": [{
                "operation": "create",
                "target_path": "/tmp/report.md",
                "timestamp": persisted_artifact["lineage"]["transitions"][0]["timestamp"],
            }],
        },
    }
    assert websocket.timelines_at_broadcast == [persisted]
    assert websocket.messages == [
        {
            "event_type": "agent_task_artifact",
            "agent_task_id": "task-1",
            "agent_task_artifact": persisted[0]["metadata"]["artifact"],
            "timeline_entry": persisted[0],
            "timestamp": websocket.messages[0]["timestamp"],
            "root_task_id": "root-1",
            "previous_task_id": "previous-1",
        }
    ]
    assert "private direct-write content" not in json.dumps(websocket.messages)
    assert "content" not in persisted[0]["metadata"]["artifact"]


@pytest.mark.asyncio
async def test_replay_replaces_matching_artifact_and_preserves_one_durable_entry(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "artifact-replay.db")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    await store_processing_task(service, "task-2")
    websocket = RecordingWebsocket(service)
    notifier = WorkflowStatusNotifier(websocket_manager=websocket, agent_task_id="task-2")

    assert await notifier.publish_agent_task_artifact(
        output={"agent_task_artifact": artifact()},
        source_step_id="step-1",
    )
    assert await notifier.publish_agent_task_artifact(
        output={"agent_task_artifact": artifact(lifecycle="failed")},
        source_step_id="step-2",
    )

    record = await service.get_agent_task("task-2")
    assert len(record.execution_timeline) == 1
    persisted_artifact = record.execution_timeline[0]["metadata"]["artifact"]
    assert persisted_artifact["lifecycle"] == "failed"
    assert persisted_artifact["source_step_id"] == "step-2"
    assert len(websocket.messages) == 2


@pytest.mark.asyncio
async def test_stale_full_timeline_writes_preserve_durable_artifact_entries(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "artifact-stale-timeline.db")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    await store_processing_task(service, "task-stale-timeline")
    notifier = WorkflowStatusNotifier(agent_task_id="task-stale-timeline")

    stale_timeline = [{
        "id": "stale-progress-entry",
        "type": "step",
        "timestamp": "2026-08-10T00:00:00Z",
        "content": "Stale writer progress",
    }]
    assert await notifier.publish_agent_task_artifact(
        output={"agent_task_artifact": artifact()},
        source_step_id="step-1",
    )

    await service.agent_task_service._mutations.update_execution_timeline(
        "task-stale-timeline",
        stale_timeline,
    )
    active_stale_timeline = [{
        "id": "active-stale-progress-entry",
        "type": "step",
        "timestamp": "2026-08-10T00:00:01Z",
        "content": "Active stale writer progress",
    }]
    assert await service.agent_task_service._mutations.update_execution_timeline_if_active(
        "task-stale-timeline",
        active_stale_timeline,
    )

    record = await service.get_agent_task("task-stale-timeline")
    assert [
        entry["metadata"]["artifact"]["artifact_id"]
        for entry in record.execution_timeline
        if isinstance(entry.get("metadata"), dict)
        and isinstance(entry["metadata"].get("artifact"), dict)
    ] == ["file-0123456789abcdef01234567"]


@pytest.mark.asyncio
async def test_terminal_task_malformed_output_and_persistence_failure_publish_nothing(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "artifact-failures.db")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    await store_processing_task(service, "task-3")
    websocket = RecordingWebsocket(service)
    notifier = WorkflowStatusNotifier(websocket_manager=websocket, agent_task_id="task-3")

    assert not await notifier.publish_agent_task_artifact(
        output={"result": {"agent_task_artifact": artifact()}},
        source_step_id="step-1",
    )
    await service.agent_task_service._mutations.update_agent_task_status(
        "task-3",
        "cancelled",
    )
    assert not await notifier.publish_agent_task_artifact(
        output={"agent_task_artifact": artifact()},
        source_step_id="step-1",
    )
    await store_processing_task(service, "task-4")
    notifier.set_agent_task_id("task-4")

    async def fail_persistence(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("fixture persistence failure")

    monkeypatch.setattr(
        artifact_activity_publication,
        "persist_artifact_timeline_entry",
        fail_persistence,
    )
    assert not await notifier.publish_agent_task_artifact(
        output={"agent_task_artifact": artifact()},
        source_step_id="step-1",
    )
    assert websocket.messages == []
    assert (await service.get_agent_task("task-3")).execution_timeline is None
    assert (await service.get_agent_task("task-4")).execution_timeline is None


@pytest.mark.asyncio
async def test_missing_task_is_ignored_and_disconnected_publication_is_durable(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "artifact-no-websocket.db")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    notifier = WorkflowStatusNotifier(agent_task_id="missing-task")

    assert not await notifier.publish_agent_task_artifact(
        output={"agent_task_artifact": artifact()},
        source_step_id="step-1",
    )

    await store_processing_task(service, "task-no-websocket")
    notifier.set_agent_task_id("task-no-websocket")
    assert await notifier.publish_agent_task_artifact(
        output={"agent_task_artifact": artifact()},
        source_step_id="step-1",
    )
    record = await service.get_agent_task("task-no-websocket")
    assert record.execution_timeline[0]["metadata"]["artifact"]["artifact_id"] == artifact()[
        "artifact_id"
    ]


@pytest.mark.asyncio
async def test_broadcast_failure_leaves_durable_artifact_available_for_recovery(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "artifact-broadcast-failure.db")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    await store_processing_task(service, "task-broadcast-failure")

    class FailingWebsocket:
        async def broadcast(self, _message: dict[str, Any]) -> None:
            raise RuntimeError("fixture broadcast failure")

    notifier = WorkflowStatusNotifier(
        websocket_manager=FailingWebsocket(),
        agent_task_id="task-broadcast-failure",
    )

    assert await notifier.publish_agent_task_artifact(
        output={"agent_task_artifact": artifact()},
        source_step_id="step-1",
    )
    record = await service.get_agent_task("task-broadcast-failure")
    assert record.execution_timeline[0]["metadata"]["artifact"]["artifact_id"] == artifact()[
        "artifact_id"
    ]


@pytest.mark.asyncio
async def test_callback_forwards_only_correlated_tool_completion_output() -> None:
    notifier = CallbackNotifier()
    callback = ActivityProgressCallbackHandler(
        notifier=notifier,
        todo_id="task-callback",
    )
    output = json.dumps({"agent_task_artifact": artifact()})

    await callback.on_tool_end(
        output=output,
        run_id="unknown-run",
        name="file_service_write_text_file",
    )
    await callback.on_tool_start(
        {"name": "file_service_write_text_file"},
        run_id="run-1",
        inputs={
            "path": "/tmp/report.md",
            "content": "private direct-write content",
            "mode": "create",
        },
    )
    await callback.on_tool_end(
        output=output,
        run_id="run-1",
        name="file_service_write_text_file",
    )

    assert notifier.artifacts == [
        {
            "output": output,
            "source_step_id": "step-direct-write",
        }
    ]


def test_callback_setup_retains_durable_artifact_path_without_websocket() -> None:
    state = type(
        "State",
        (),
        {
            "context": {"agent_task_id": "task-no-websocket"},
            "available_tools": None,
        },
    )()
    coordinator = type("Coordinator", (), {"_websocket_manager": None})()

    callbacks = setup_live_callbacks(state, coordinator)

    assert len(callbacks) == 1
    assert isinstance(callbacks[0], ActivityProgressCallbackHandler)


@pytest.mark.asyncio
async def test_verified_write_captures_a_durable_revision_and_embeds_review(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verified direct text write persists one durable revision row and

    embeds matching, task-owned ``review`` presentation metadata into the
    broadcast and persisted timeline artifact.
    """
    service = SQLiteKnowledgeService(tmp_path / "artifact-revision-capture.db")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    await store_processing_task(service, "task-revision-capture")
    websocket = RecordingWebsocket(service)
    notifier = WorkflowStatusNotifier(
        websocket_manager=websocket,
        agent_task_id="task-revision-capture",
    )

    target = tmp_path / "report.md"
    content = b"# Report\n"
    target.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()

    published = await notifier.publish_agent_task_artifact(
        output={
            "agent_task_artifact": {
                **artifact(),
                "local_path": str(target),
                "verification": {
                    "status": "verified",
                    "summary": f"Verified {len(content)} bytes; SHA-256 {digest}.",
                },
            }
        },
        source_step_id="step-1",
    )

    assert published is True
    record = await service.get_agent_task("task-revision-capture")
    persisted_artifact = record.execution_timeline[0]["metadata"]["artifact"]
    assert persisted_artifact["review"] == {
        "revision": 1,
        "revision_count": 1,
        "kind": "markdown",
        "snapshot_status": "available",
    }
    broadcast_review = websocket.messages[0]["agent_task_artifact"]["review"]
    assert broadcast_review == persisted_artifact["review"]

    revisions = await service.agent_task_service.list_artifact_revisions(
        "task-revision-capture",
        artifact()["artifact_id"],
    )
    assert len(revisions) == 1
    assert revisions[0]["revision"] == 1
    assert "content" not in revisions[0]

    snapshot = await service.agent_task_service.get_artifact_revision(
        "task-revision-capture",
        artifact()["artifact_id"],
        1,
    )
    assert snapshot is not None
    assert snapshot["content"] == "# Report\n"
    assert snapshot["content_sha256"] == digest


@pytest.mark.asyncio
async def test_unsupported_extension_publishes_without_a_revision(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verified write to an unsupported extension still publishes, with a

    review payload reporting ``unavailable`` rather than failing publication.
    """
    service = SQLiteKnowledgeService(tmp_path / "artifact-unsupported-kind.db")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    await store_processing_task(service, "task-unsupported-kind")
    notifier = WorkflowStatusNotifier(agent_task_id="task-unsupported-kind")

    target = tmp_path / "diagram.drawio"
    content = b"<diagram/>"
    target.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()

    published = await notifier.publish_agent_task_artifact(
        output={
            "agent_task_artifact": {
                **artifact(),
                "local_path": str(target),
                "verification": {
                    "status": "verified",
                    "summary": f"Verified {len(content)} bytes; SHA-256 {digest}.",
                },
            }
        },
        source_step_id="step-1",
    )

    assert published is True
    record = await service.get_agent_task("task-unsupported-kind")
    review = record.execution_timeline[0]["metadata"]["artifact"]["review"]
    assert review == {
        "revision": None,
        "revision_count": 0,
        "snapshot_status": "unavailable",
        "unavailable_reason": "Snapshot unavailable: unsupported file type.",
    }
