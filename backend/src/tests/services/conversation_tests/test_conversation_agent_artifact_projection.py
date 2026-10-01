import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.conversation.conversation_agent_turn_lifecycle import (
    ConversationAgentTurnLifecycle,
    ConversationAgentTurnLink,
)
from api.services.conversation.conversation_turn_contract import ConversationTurnRoute


def direct_write_entry(lifecycle: str = "verified") -> dict:
    artifact_id = "file-0123456789abcdef01234567"
    entry_id = f"artifact_{artifact_id}"
    return {
        "id": entry_id,
        "type": "artifact",
        "metadata": {
            "event_type": "agent_task_artifact",
            "raw_detail": True,
            "artifact": {
                "artifact_id": artifact_id,
                "display_name": "report.md",
                "local_path": "/private/fixture/report.md",
                "artifact_kind": "file",
                "operation": "create",
                "lifecycle": lifecycle,
                "preview": {"capability": "unknown"},
                "verification": {
                    "status": lifecycle,
                    "summary": "Selected verification evidence.",
                },
                "source_timeline_entry_id": entry_id,
                "source_step_id": "step-1",
                "content": "private direct-write content",
                "command": "private command",
                "receipt": {"digest": "private digest"},
            },
        },
    }


def link() -> ConversationAgentTurnLink:
    return ConversationAgentTurnLink(
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        agent_task_id="task-1",
        route=ConversationTurnRoute.AGENT_TASK,
        model_id="model-1",
    )


def metadata(lifecycle: str) -> dict:
    return {
        "conversation_turn": {
            "route": "agent_task",
            "lifecycle": lifecycle,
            "agent_task_id": "task-1",
            "terminal_outcome": None,
            "user_message_id": "user-1",
            "narration": {"lifecycle": "pending", "attempt_count": 0},
        }
    }


def task(lifecycle: str, timeline: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        id="task-1",
        status=lifecycle,
        result_data={},
        accumulated_artifacts=None,
        execution_timeline=timeline,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("artifact_lifecycle", ["verified", "failed"])
async def test_persisted_direct_write_projects_selected_activity_without_status_mutation(
    artifact_lifecycle: str,
) -> None:
    durable_metadata = metadata("running")

    async def merge_metadata(_: str, patch: dict) -> None:
        durable_metadata["conversation_turn"].update(patch["conversation_turn"])

    repository = SimpleNamespace(
        find_conversation_turn_by_agent_task_id=AsyncMock(return_value={
            "conversation_id": "conversation-1",
            "assistant_message_id": "assistant-1",
            "assistant_model_id": "model-1",
            "metadata": durable_metadata,
        }),
        merge_message_metadata=AsyncMock(side_effect=merge_metadata),
    )
    status_broadcast = AsyncMock()
    activity_broadcast = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(
            return_value=task("processing", [direct_write_entry(artifact_lifecycle)])
        ),
        broadcast_status=status_broadcast,
        broadcast_activity=activity_broadcast,
    )
    lifecycle.register_link(link())

    projected = await lifecycle.handle_agent_task_artifact(
        "task-1",
        "file-0123456789abcdef01234567",
    )

    assert projected is True
    status_broadcast.assert_not_awaited()
    persisted_summary = durable_metadata["conversation_turn"]["activity_summary"]
    assert persisted_summary["verification_status"] == "resolved"
    assert persisted_summary["artifacts"] == [{
        "artifact_id": "file-0123456789abcdef01234567",
        "display_name": "report.md",
        "artifact_kind": "file",
        "lifecycle": artifact_lifecycle,
        "verification": {"status": artifact_lifecycle},
    }]
    payload = activity_broadcast.await_args.args[0]
    assert payload["summary"] == persisted_summary
    serialized = json.dumps(payload)
    assert "private direct-write content" not in serialized
    assert "private command" not in serialized
    assert "private digest" not in serialized
    assert "local_path" not in serialized
    assert "operation" not in serialized


@pytest.mark.asyncio
async def test_missing_durable_artifact_never_writes_or_broadcasts_activity() -> None:
    durable_metadata = metadata("running")
    invalid_entry = direct_write_entry()
    invalid_entry["metadata"]["artifact"]["source_timeline_entry_id"] = "artifact-other"
    repository = SimpleNamespace(
        find_conversation_turn_by_agent_task_id=AsyncMock(return_value={
            "conversation_id": "conversation-1",
            "assistant_message_id": "assistant-1",
            "assistant_model_id": "model-1",
            "metadata": durable_metadata,
        }),
        merge_message_metadata=AsyncMock(),
    )
    activity_broadcast = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(return_value=task("processing", [invalid_entry])),
        broadcast_status=AsyncMock(),
        broadcast_activity=activity_broadcast,
    )
    lifecycle.register_link(link())

    projected = await lifecycle.handle_agent_task_artifact(
        "task-1",
        "file-0123456789abcdef01234567",
    )

    assert projected is False
    repository.merge_message_metadata.assert_not_awaited()
    activity_broadcast.assert_not_awaited()


@pytest.mark.asyncio
async def test_canceled_placeholder_accepts_durable_artifact_once_without_lifecycle_regression() -> None:
    durable_metadata = metadata("canceled")

    async def merge_metadata(_: str, patch: dict) -> None:
        durable_metadata["conversation_turn"].update(patch["conversation_turn"])

    repository = SimpleNamespace(
        find_conversation_turn_by_agent_task_id=AsyncMock(return_value={
            "conversation_id": "conversation-1",
            "assistant_message_id": "assistant-1",
            "assistant_model_id": "model-1",
            "metadata": durable_metadata,
        }),
        merge_message_metadata=AsyncMock(side_effect=merge_metadata),
    )
    activity_broadcast = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(return_value=task("canceled", [direct_write_entry()])),
        broadcast_status=AsyncMock(),
        broadcast_activity=activity_broadcast,
    )
    lifecycle.register_link(link())

    assert await lifecycle.handle_agent_task_artifact(
        "task-1",
        "file-0123456789abcdef01234567",
    ) is True
    assert await lifecycle.handle_agent_task_artifact(
        "task-1",
        "file-0123456789abcdef01234567",
    ) is False

    assert durable_metadata["conversation_turn"]["lifecycle"] == "canceled"
    assert durable_metadata["conversation_turn"]["activity_summary"]["lifecycle"] == "canceled"
    assert activity_broadcast.await_count == 1
