from typing import Any
from unittest.mock import AsyncMock

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.runtime import (
    artifact_activity_publication,
    conversation_progress_projection,
)
from api.services.agent_processing.lifecycle.runtime.workflow_status_notifier import (
    WorkflowStatusNotifier,
)


def artifact() -> dict[str, Any]:
    return {
        "artifact_id": "file-0123456789abcdef01234567",
        "display_name": "report.md",
        "local_path": "/private/fixture/report.md",
        "artifact_kind": "file",
        "operation": "create",
        "lifecycle": "verified",
        "preview": {"capability": "unknown"},
        "verification": {
            "status": "verified",
            "summary": "Selected verification evidence.",
        },
    }


async def store_processing_task(service: SQLiteKnowledgeService) -> None:
    await service.store_agent_task(
        agent_task_id="task-1",
        original_prompt="Create a report",
        transcribed_prompt="Create a report",
        status="processing",
    )


@pytest.mark.asyncio
async def test_artifact_persists_before_conversation_projection_and_agent_task_broadcast(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "artifact-conversation-projection.db")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    await store_processing_task(service)
    order: list[str] = []

    async def project(agent_task_id: str, artifact_id: str) -> None:
        record = await service.get_agent_task(agent_task_id)
        assert record is not None
        assert record.execution_timeline[0]["metadata"]["artifact"]["artifact_id"] == artifact_id
        order.append("conversation")

    class Websocket:
        async def broadcast(self, message: dict[str, Any]) -> None:
            assert message["event_type"] == "agent_task_artifact"
            order.append("agent-task")

    monkeypatch.setattr(
        conversation_progress_projection,
        "_project_conversation_agent_task_artifact",
        project,
    )
    notifier = WorkflowStatusNotifier(websocket_manager=Websocket(), agent_task_id="task-1")

    assert await notifier.publish_agent_task_artifact(
        output={"agent_task_artifact": artifact()},
        source_step_id="step-1",
    ) is True
    assert order == ["conversation", "agent-task"]


@pytest.mark.asyncio
async def test_malformed_artifact_notification_skips_conversation_projection_but_preserves_agent_task_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projected = AsyncMock()
    broadcast = AsyncMock()
    monkeypatch.setattr(
        conversation_progress_projection,
        "_project_conversation_agent_task_artifact",
        projected,
    )
    payload = {
        "event_type": "agent_task_artifact",
        "agent_task_id": "task-1",
        "agent_task_artifact": artifact(),
        "timeline_entry": {
            "id": "artifact-other",
            "metadata": {"artifact": artifact()},
        },
    }

    await conversation_progress_projection.broadcast_workflow_notification(
        type("Websocket", (), {"broadcast": broadcast})(),
        payload,
    )

    projected.assert_not_awaited()
    broadcast.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_persistence_failure_never_attempts_conversation_projection(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = SQLiteKnowledgeService(tmp_path / "artifact-conversation-failure.db")
    monkeypatch.setattr("api.dependencies.get_sqlite_knowledge_service", lambda: service)
    await store_processing_task(service)
    projected = AsyncMock()

    async def fail_persistence(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("fixture persistence failure")

    monkeypatch.setattr(
        conversation_progress_projection,
        "_project_conversation_agent_task_artifact",
        projected,
    )
    monkeypatch.setattr(
        artifact_activity_publication,
        "persist_artifact_timeline_entry",
        fail_persistence,
    )
    notifier = WorkflowStatusNotifier(
        websocket_manager=type("Websocket", (), {"broadcast": AsyncMock()})(),
        agent_task_id="task-1",
    )

    assert await notifier.publish_agent_task_artifact(
        output={"agent_task_artifact": artifact()},
        source_step_id="step-1",
    ) is False
    projected.assert_not_awaited()
