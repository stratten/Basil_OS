import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.conversation import conversation_agent_turn_lifecycle as lifecycle_module
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.events import AgentTaskEvent
from api.services.conversation.conversation_agent_turn_lifecycle import (
    ConversationAgentTurnLifecycle,
    ConversationAgentTurnLink,
)
from api.services.conversation.conversation_turn_contract import (
    ConversationTurnNarrationLifecycle,
    ConversationTurnRoute,
)


def link(route: ConversationTurnRoute = ConversationTurnRoute.AGENT_TASK) -> ConversationAgentTurnLink:
    return ConversationAgentTurnLink(
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        agent_task_id="task-1",
        route=route,
        model_id="model-1",
    )


def routed_metadata(
    *,
    lifecycle: str = "pending",
    terminal_outcome: str | None = None,
    narration_lifecycle: str = "pending",
) -> dict:
    return {
        "conversation_turn": {
            "route": "agent_task",
            "lifecycle": lifecycle,
            "agent_task_id": "task-1",
            "terminal_outcome": terminal_outcome,
            "user_message_id": "user-1",
            "narration": {"lifecycle": narration_lifecycle, "attempt_count": 0},
        }
    }


def activity_task(
    *,
    lifecycle: str = "processing",
    timeline: list[dict] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id="task-1",
        status=lifecycle,
        result_data={
            "finalizer_result": {
                "result_payload": {
                    "files": [
                        {
                            "name": "report.md",
                            "full_path": "/private/fixture/report.md",
                            "operation": "write",
                        }
                    ],
                    "steps": {"completed": 1, "total": 2},
                }
            }
        },
        accumulated_artifacts=None,
        execution_timeline=(
            timeline
            if timeline is not None
            else [
                {
                    "id": "step-1",
                    "content": "Writing the requested report.",
                    "metadata": {},
                }
            ]
        ),
    )


@pytest.fixture
def repository() -> SimpleNamespace:
    return SimpleNamespace(
        find_conversation_turn_by_agent_task_id=AsyncMock(
            return_value={
                "conversation_id": "conversation-1",
                "assistant_message_id": "assistant-1",
                "assistant_model_id": "selected-model",
                "metadata": routed_metadata(),
            }
        ),
        merge_message_metadata=AsyncMock(),
        update_message=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_agent_task_completion_keeps_placeholder_empty_and_emits_status(
    repository: SimpleNamespace,
) -> None:
    broadcast = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=broadcast,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(
            agent_task_id="task-1",
            event_type="status_changed",
            old_status="processing",
            new_status="completed",
            agent_task_data={"status": "completed"},
        )
    )

    repository.update_message.assert_not_awaited()
    lifecycle._get_agent_task.assert_awaited_once_with("task-1")
    assert repository.merge_message_metadata.await_args.args[1]["conversation_turn"] == {
        "lifecycle": "completed",
        "status_text": "Paprika finished the task. Preparing a conversation response.",
        "terminal_outcome": "Paprika finished the task.",
        "requires_user_attention": False,
        "attention_id": None,
        "narration": {"lifecycle": ConversationTurnNarrationLifecycle.READY.value},
    }
    assert broadcast.await_args.args[0] == {
        "event_type": "conversation_agent_status",
        "conversation_id": "conversation-1",
        "placeholder_message_id": "assistant-1",
        "agent_task_id": "task-1",
        "lifecycle": "completed",
        "status_text": "Paprika finished the task. Preparing a conversation response.",
        "terminal_outcome": "Paprika finished the task.",
        "deep_link_id": "task-1",
        "requires_user_attention": False,
        "agent_status": "completed",
        "narration_state": "ready",
    }


@pytest.mark.asyncio
async def test_agent_task_completion_keeps_placeholder_content_empty(
    repository: SimpleNamespace,
) -> None:
    broadcast = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(return_value=SimpleNamespace(status="completed", result_data={}, accumulated_artifacts=None, execution_timeline=[])),
        broadcast_status=broadcast,
    )
    lifecycle.register_link(link(ConversationTurnRoute.AGENT_TASK))

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="completed")
    )

    repository.update_message.assert_not_awaited()
    lifecycle._get_agent_task.assert_awaited_once_with("task-1")
    assert repository.merge_message_metadata.await_args.args[1]["conversation_turn"] == {
        "lifecycle": "completed",
        "status_text": "Paprika finished the task. Preparing a conversation response.",
        "terminal_outcome": "Paprika finished the task.",
        "requires_user_attention": False,
        "attention_id": None,
        "narration": {"lifecycle": ConversationTurnNarrationLifecycle.READY.value},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_lifecycle", "expected_outcome", "expected_status_text"),
    [
        ("failed", "failed", "Paprika's task failed. Preparing a conversation response.", "Paprika's task failed. Preparing a conversation response."),
        ("canceled", "canceled", "Paprika's task was canceled. Preparing a conversation response.", "Paprika's task was canceled. Preparing a conversation response."),
        ("capturing", "running", None, "Paprika is gathering context."),
        ("routing", "running", None, "Paprika is selecting an approach."),
        ("routed", "running", None, "Paprika is ready to begin."),
        ("processing", "running", None, "Paprika is working."),
        ("awaiting_user_input", "running", None, "Paprika needs your input."),
        ("needs_clarification", "running", None, "Paprika needs clarification."),
    ],
)
async def test_status_projection_maps_terminal_and_running_states(
    repository: SimpleNamespace,
    status: str,
    expected_lifecycle: str,
    expected_outcome: str | None,
    expected_status_text: str,
) -> None:
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(return_value=SimpleNamespace(status=status, result_data={}, accumulated_artifacts=None, execution_timeline=[])),
        broadcast_status=AsyncMock(),
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status=status)
    )

    assert repository.merge_message_metadata.await_args.args[1]["conversation_turn"]["lifecycle"] == expected_lifecycle
    assert repository.merge_message_metadata.await_args.args[1]["conversation_turn"]["terminal_outcome"] == expected_outcome
    payload = lifecycle._broadcast_status.await_args.args[0]
    assert payload["agent_status"] == status
    assert payload["status_text"] == expected_status_text
    if expected_lifecycle in {"failed", "canceled"}:
        assert payload["narration_state"] == "ready"


@pytest.mark.asyncio
async def test_duplicate_running_projection_is_ignored_from_durable_metadata(
    repository: SimpleNamespace,
) -> None:
    repository.find_conversation_turn_by_agent_task_id.return_value["metadata"] = routed_metadata(
        lifecycle="running",
    )
    broadcast = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=broadcast,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="routing")
    )

    repository.merge_message_metadata.assert_not_awaited()
    broadcast.assert_not_awaited()


@pytest.mark.asyncio
async def test_clarification_event_projects_specific_running_status(
    repository: SimpleNamespace,
) -> None:
    broadcast = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=broadcast,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="clarification_added")
    )

    assert repository.merge_message_metadata.await_args.args[1]["conversation_turn"] == {
        "lifecycle": "running",
        "status_text": "Paprika received your clarification.",
        "terminal_outcome": None,
        "requires_user_attention": False,
        "attention_id": None,
    }
    assert broadcast.await_args.args[0]["agent_status"] == "clarification_added"
    assert broadcast.await_args.args[0]["status_text"] == "Paprika received your clarification."


@pytest.mark.asyncio
async def test_updated_event_projects_current_agent_status(
    repository: SimpleNamespace,
) -> None:
    broadcast = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=broadcast,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(
            agent_task_id="task-1",
            event_type="updated",
            agent_task_data={"status": "processing"},
        )
    )

    assert repository.merge_message_metadata.await_args.args[1]["conversation_turn"] == {
        "lifecycle": "running",
        "status_text": "Paprika is working.",
        "terminal_outcome": None,
        "requires_user_attention": False,
        "attention_id": None,
    }
    assert broadcast.await_args.args[0]["agent_status"] == "processing"
    assert broadcast.await_args.args[0]["status_text"] == "Paprika is working."


@pytest.mark.asyncio
async def test_submission_failure_marks_narration_ready(
    repository: SimpleNamespace,
) -> None:
    broadcast = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=broadcast,
    )

    await lifecycle.record_submission_failure(link(), "Submission unavailable.")

    assert repository.merge_message_metadata.await_args.args[1]["conversation_turn"] == {
        "lifecycle": "failed",
        "status_text": "Paprika's task failed. Preparing a conversation response.",
        "terminal_outcome": "Submission unavailable.",
        "requires_user_attention": False,
        "attention_id": None,
        "narration": {"lifecycle": "ready"},
    }
    assert broadcast.await_args.args[0]["agent_status"] == "failed"
    assert broadcast.await_args.args[0]["narration_state"] == "ready"


@pytest.mark.asyncio
async def test_submission_failure_starts_narration_after_durable_projection(
    repository: SimpleNamespace,
) -> None:
    started: list[str] = []
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=AsyncMock(),
        start_narration=started.append,
    )

    await lifecycle.record_submission_failure(link(), "Submission unavailable.")

    assert started == ["task-1"]


@pytest.mark.asyncio
async def test_terminal_event_calls_start_narration_exactly_once(
    repository: SimpleNamespace,
) -> None:
    started: list[str] = []
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=AsyncMock(),
        start_narration=started.append,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="completed")
    )

    assert started == ["task-1"]


@pytest.mark.asyncio
async def test_duplicate_terminal_event_does_not_call_start_narration_again(
    repository: SimpleNamespace,
) -> None:
    repository.find_conversation_turn_by_agent_task_id.return_value["metadata"] = routed_metadata(
        lifecycle="completed",
        terminal_outcome="Paprika finished the task.",
        narration_lifecycle="ready",
    )
    started: list[str] = []
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=AsyncMock(),
        start_narration=started.append,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="completed")
    )

    assert started == []


@pytest.mark.asyncio
async def test_stale_terminal_event_does_not_call_start_narration(
    repository: SimpleNamespace,
) -> None:
    repository.find_conversation_turn_by_agent_task_id.return_value["metadata"] = routed_metadata(
        lifecycle="completed",
        terminal_outcome="Paprika finished the task.",
        narration_lifecycle="ready",
    )
    started: list[str] = []
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=AsyncMock(),
        start_narration=started.append,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="failed")
    )

    assert started == []


@pytest.mark.asyncio
async def test_nonterminal_update_does_not_call_start_narration(
    repository: SimpleNamespace,
) -> None:
    started: list[str] = []
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=AsyncMock(),
        start_narration=started.append,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="processing")
    )

    assert started == []


@pytest.mark.asyncio
async def test_live_progress_replaces_the_coarse_agent_status_text(
    repository: SimpleNamespace,
) -> None:
    broadcast = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=broadcast,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_progress(
        "task-1",
        "Inspecting the active project configuration",
    )

    assert repository.merge_message_metadata.await_args.args[1]["conversation_turn"] == {
        "lifecycle": "running",
        "status_text": "Inspecting the active project configuration",
        "terminal_outcome": None,
        "requires_user_attention": False,
        "attention_id": None,
    }
    assert broadcast.await_args.args[0]["status_text"] == "Inspecting the active project configuration"
    assert broadcast.await_args.args[0]["agent_status"] == "processing"


@pytest.mark.asyncio
async def test_progress_event_during_pending_approval_does_not_hide_the_attention_marker(
    repository: SimpleNamespace,
) -> None:
    """A concurrent tool's progress tick must not hide a still-pending approval (Package 2)."""
    repository.find_conversation_turn_by_agent_task_id.return_value["metadata"] = {
        "conversation_turn": {
            "route": "agent_task",
            "lifecycle": "running",
            "agent_task_id": "task-1",
            "terminal_outcome": None,
            "user_message_id": "user-1",
            "narration": {"lifecycle": "pending", "attempt_count": 0},
            "requires_user_attention": True,
            "attention_id": "approval-1",
            "attention_ids": ["approval-1", "approval-2"],
        }
    }
    broadcast = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=broadcast,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_progress(
        "task-1",
        "Running an unrelated approved command",
    )

    patch = repository.merge_message_metadata.await_args.args[1]["conversation_turn"]
    assert patch["requires_user_attention"] is True
    assert patch["attention_id"] == "approval-1"
    assert patch["attention_ids"] == ["approval-1", "approval-2"]
    payload = broadcast.await_args.args[0]
    assert payload["requires_user_attention"] is True
    assert payload["attention_id"] == "approval-1"
    assert payload["attention_ids"] == ["approval-1", "approval-2"]


@pytest.mark.asyncio
async def test_activity_summary_progress_override_preserves_pending_attention() -> None:
    """The Package 0 activity summary must not force requires_user_attention to False
    while the task's own status still reflects a pending approval (Package 2)."""
    metadata = {
        "conversation_turn": {
            "route": "agent_task",
            "lifecycle": "running",
            "agent_task_id": "task-1",
            "terminal_outcome": None,
            "user_message_id": "user-1",
            "narration": {"lifecycle": "pending", "attempt_count": 0},
            "requires_user_attention": True,
            "attention_id": "approval-1",
        }
    }

    async def merge_metadata(_: str, patch: dict) -> None:
        metadata["conversation_turn"].update(patch["conversation_turn"])

    repository = SimpleNamespace(
        find_conversation_turn_by_agent_task_id=AsyncMock(
            return_value={
                "conversation_id": "conversation-1",
                "assistant_message_id": "assistant-1",
                "assistant_model_id": "selected-model",
                "metadata": metadata,
            }
        ),
        merge_message_metadata=AsyncMock(side_effect=merge_metadata),
        update_message=AsyncMock(),
    )
    broadcast_activity = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(return_value=activity_task(lifecycle="awaiting_user_input")),
        broadcast_status=AsyncMock(),
        broadcast_activity=broadcast_activity,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_progress("task-1", "Running an unrelated approved command")

    assert broadcast_activity.await_args.args[0]["summary"]["requires_user_attention"] is True
    assert metadata["conversation_turn"]["activity_summary"]["requires_user_attention"] is True


@pytest.mark.asyncio
async def test_activity_projection_persists_selected_summary_before_broadcast() -> None:
    metadata = routed_metadata()
    order: list[str] = []
    activity_payloads: list[dict] = []

    async def find_turn(_: str) -> dict:
        return {
            "conversation_id": "conversation-1",
            "assistant_message_id": "assistant-1",
            "assistant_model_id": "selected-model",
            "metadata": metadata,
        }

    async def merge_metadata(_: str, patch: dict) -> None:
        order.append("persist")
        metadata["conversation_turn"].update(patch["conversation_turn"])

    async def broadcast_status(_: dict) -> None:
        order.append("status")

    async def broadcast_activity(payload: dict) -> None:
        order.append("activity")
        activity_payloads.append(payload)

    repository = SimpleNamespace(
        find_conversation_turn_by_agent_task_id=AsyncMock(side_effect=find_turn),
        merge_message_metadata=AsyncMock(side_effect=merge_metadata),
        update_message=AsyncMock(),
    )
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(return_value=activity_task()),
        broadcast_status=broadcast_status,
        broadcast_activity=broadcast_activity,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="processing")
    )

    assert order == ["persist", "status", "persist", "activity"]
    activity_patch = repository.merge_message_metadata.await_args_list[1].args[1]["conversation_turn"]
    assert activity_patch["activity_summary"] == {
        "agent_task_id": "task-1",
        "lifecycle": "processing",
        "latest_activity": "Writing the requested report.",
        "workflow": {"completed_steps": 1, "total_steps": 2},
        "artifacts": [
            {
                "artifact_id": activity_patch["activity_summary"]["artifacts"][0]["artifact_id"],
                "display_name": "report.md",
                "artifact_kind": "unknown",
                "lifecycle": "ready",
                "verification": {"status": "unknown"},
            }
        ],
        "artifact_count": 1,
        "verification_status": "unknown",
        "requires_user_attention": False,
    }
    assert len(activity_patch["activity_summary_fingerprint"]) == 64
    activity_payload = activity_payloads[0]
    assert activity_payload["summary"] == activity_patch["activity_summary"]
    assert "local_path" not in activity_payload["summary"]["artifacts"][0]
    assert "operation" not in activity_payload["summary"]["artifacts"][0]


@pytest.mark.asyncio
async def test_activity_projection_uses_live_progress_when_timeline_write_is_not_visible_yet() -> None:
    metadata = routed_metadata()

    async def merge_metadata(_: str, patch: dict) -> None:
        metadata["conversation_turn"].update(patch["conversation_turn"])

    repository = SimpleNamespace(
        find_conversation_turn_by_agent_task_id=AsyncMock(
            return_value={
                "conversation_id": "conversation-1",
                "assistant_message_id": "assistant-1",
                "assistant_model_id": "selected-model",
                "metadata": metadata,
            }
        ),
        merge_message_metadata=AsyncMock(side_effect=merge_metadata),
        update_message=AsyncMock(),
    )
    broadcast_activity = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(return_value=activity_task(timeline=[])),
        broadcast_status=AsyncMock(),
        broadcast_activity=broadcast_activity,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_progress("task-1", "Inspecting the active project configuration")

    assert broadcast_activity.await_args.args[0]["summary"]["latest_activity"] == "Inspecting the active project configuration"
    assert metadata["conversation_turn"]["activity_summary"]["latest_activity"] == "Inspecting the active project configuration"


@pytest.mark.asyncio
async def test_activity_projection_suppresses_duplicate_persisted_summary_after_recovery() -> None:
    metadata = routed_metadata()

    async def merge_metadata(_: str, patch: dict) -> None:
        metadata["conversation_turn"].update(patch["conversation_turn"])

    repository = SimpleNamespace(
        find_conversation_turn_by_agent_task_id=AsyncMock(
            return_value={
                "conversation_id": "conversation-1",
                "assistant_message_id": "assistant-1",
                "assistant_model_id": "selected-model",
                "metadata": metadata,
            }
        ),
        merge_message_metadata=AsyncMock(side_effect=merge_metadata),
        update_message=AsyncMock(),
    )
    first_activity_broadcast = AsyncMock()
    first = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(return_value=activity_task()),
        broadcast_status=AsyncMock(),
        broadcast_activity=first_activity_broadcast,
    )
    first.register_link(link())
    event = AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="processing")

    await first.handle_agent_task_event(event)

    recovered_activity_broadcast = AsyncMock()
    recovered = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(return_value=activity_task()),
        broadcast_status=AsyncMock(),
        broadcast_activity=recovered_activity_broadcast,
    )

    await recovered.handle_agent_task_event(event)

    assert first_activity_broadcast.await_count == 1
    recovered_activity_broadcast.assert_not_awaited()
    assert repository.merge_message_metadata.await_count == 2


@pytest.mark.asyncio
async def test_activity_projection_never_broadcasts_after_activity_metadata_write_failure() -> None:
    metadata = routed_metadata()
    merge_count = 0

    async def merge_metadata(_: str, patch: dict) -> None:
        nonlocal merge_count
        merge_count += 1
        if "activity_summary" in patch["conversation_turn"]:
            raise RuntimeError("activity metadata unavailable")
        metadata["conversation_turn"].update(patch["conversation_turn"])

    repository = SimpleNamespace(
        find_conversation_turn_by_agent_task_id=AsyncMock(
            return_value={
                "conversation_id": "conversation-1",
                "assistant_message_id": "assistant-1",
                "assistant_model_id": "selected-model",
                "metadata": metadata,
            }
        ),
        merge_message_metadata=AsyncMock(side_effect=merge_metadata),
        update_message=AsyncMock(),
    )
    broadcast_activity = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(return_value=activity_task()),
        broadcast_status=AsyncMock(),
        broadcast_activity=broadcast_activity,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="processing")
    )

    assert merge_count == 2
    assert "activity_summary" not in metadata["conversation_turn"]
    broadcast_activity.assert_not_awaited()


@pytest.mark.asyncio
async def test_activity_projection_ignores_malformed_task_source_after_status_projection() -> None:
    metadata = routed_metadata()

    async def merge_metadata(_: str, patch: dict) -> None:
        metadata["conversation_turn"].update(patch["conversation_turn"])

    repository = SimpleNamespace(
        find_conversation_turn_by_agent_task_id=AsyncMock(
            return_value={
                "conversation_id": "conversation-1",
                "assistant_message_id": "assistant-1",
                "assistant_model_id": "selected-model",
                "metadata": metadata,
            }
        ),
        merge_message_metadata=AsyncMock(side_effect=merge_metadata),
        update_message=AsyncMock(),
    )
    broadcast_status = AsyncMock()
    broadcast_activity = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(
            return_value=SimpleNamespace(
                id="task-1",
                status="processing",
                result_data=["malformed"],
                accumulated_artifacts=None,
                execution_timeline=[],
            )
        ),
        broadcast_status=broadcast_status,
        broadcast_activity=broadcast_activity,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="processing")
    )

    assert repository.merge_message_metadata.await_count == 1
    assert broadcast_status.await_count == 1
    broadcast_activity.assert_not_awaited()
    assert "activity_summary" not in metadata["conversation_turn"]


@pytest.mark.asyncio
async def test_activity_projection_rejects_a_terminal_regression() -> None:
    metadata = routed_metadata(
        lifecycle="completed",
        terminal_outcome="Paprika finished the task.",
        narration_lifecycle="ready",
    )
    repository = SimpleNamespace(
        find_conversation_turn_by_agent_task_id=AsyncMock(
            return_value={
                "conversation_id": "conversation-1",
                "assistant_message_id": "assistant-1",
                "assistant_model_id": "selected-model",
                "metadata": metadata,
            }
        ),
        merge_message_metadata=AsyncMock(),
        update_message=AsyncMock(),
    )
    broadcast_activity = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(return_value=activity_task()),
        broadcast_status=AsyncMock(),
        broadcast_activity=broadcast_activity,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="processing")
    )

    repository.merge_message_metadata.assert_not_awaited()
    broadcast_activity.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_duplicate_running_events_write_and_broadcast_once() -> None:
    metadata = routed_metadata()

    async def find_turn(_: str) -> dict:
        return {
            "conversation_id": "conversation-1",
            "assistant_message_id": "assistant-1",
            "metadata": metadata,
        }

    async def merge_metadata(_: str, patch: dict) -> None:
        metadata["conversation_turn"].update(patch["conversation_turn"])

    broadcast = AsyncMock()
    repository = SimpleNamespace(
        find_conversation_turn_by_agent_task_id=AsyncMock(side_effect=find_turn),
        merge_message_metadata=AsyncMock(side_effect=merge_metadata),
        update_message=AsyncMock(),
    )
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=broadcast,
    )
    lifecycle.register_link(link())
    event = AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="routing")

    await asyncio.gather(
        lifecycle.handle_agent_task_event(event),
        lifecycle.handle_agent_task_event(event),
    )

    repository.merge_message_metadata.assert_awaited_once()
    broadcast.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_projection_is_ignored_from_durable_metadata(
    repository: SimpleNamespace,
) -> None:
    repository.find_conversation_turn_by_agent_task_id.return_value["metadata"] = routed_metadata(
        lifecycle="completed",
        terminal_outcome="Paprika finished the task.",
        narration_lifecycle="ready",
    )
    broadcast = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(return_value=SimpleNamespace(status="completed", result_data={}, accumulated_artifacts=None, execution_timeline=[])),
        broadcast_status=broadcast,
    )
    lifecycle.register_link(link(ConversationTurnRoute.AGENT_TASK))

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="completed")
    )

    repository.merge_message_metadata.assert_not_awaited()
    broadcast.assert_not_awaited()


@pytest.mark.asyncio
async def test_fresh_lifecycle_restores_durable_link_and_ignores_unrelated_task(
    repository: SimpleNamespace,
) -> None:
    broadcast = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(return_value=SimpleNamespace(status="routing", result_data={}, accumulated_artifacts=None, execution_timeline=[])),
        broadcast_status=broadcast,
    )

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="created", new_status="routing")
    )
    assert "task-1" in lifecycle._links
    assert lifecycle._links["task-1"].model_id == "selected-model"
    assert lifecycle._links["task-1"].user_message_id == "user-1"

    repository.find_conversation_turn_by_agent_task_id.return_value = None
    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="unrelated-task", event_type="status_changed", new_status="completed")
    )

    assert broadcast.await_count == 1


@pytest.mark.asyncio
async def test_terminal_projection_does_not_regress_and_attempts_activity_repair(
    repository: SimpleNamespace,
) -> None:
    repository.find_conversation_turn_by_agent_task_id.return_value["metadata"] = routed_metadata(
        lifecycle="completed",
        terminal_outcome="Paprika finished the task.",
    )
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=AsyncMock(),
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="routing")
    )

    repository.merge_message_metadata.assert_not_awaited()
    lifecycle._get_agent_task.assert_awaited_once_with("task-1")


def test_callback_registration_is_additive_and_process_local_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    callbacks = []
    database = SimpleNamespace(
        db_path=tmp_path / "conversation-callback.db",
        get_agent_task=AsyncMock(),
        register_agent_task_callback=callbacks.append,
    )
    monkeypatch.setattr(lifecycle_module, "_callback_registered", False)
    monkeypatch.setattr(lifecycle_module, "_registered_lifecycle", None)
    monkeypatch.setattr(lifecycle_module, "get_sqlite_knowledge_service", lambda: database)

    lifecycle_module.ensure_conversation_agent_turn_callback_registered()
    lifecycle_module.ensure_conversation_agent_turn_callback_registered()

    assert len(callbacks) == 1
    assert lifecycle_module.get_registered_conversation_agent_turn_lifecycle()._get_agent_task is database.get_agent_task


@pytest.mark.asyncio
async def test_terminal_event_retains_runtime_agent_task_mapping_for_narration(
    repository: SimpleNamespace,
) -> None:
    released: list[str] = []
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=AsyncMock(),
        release_agent_task=released.append,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="completed")
    )

    assert released == []


@pytest.mark.asyncio
async def test_nonterminal_event_does_not_release_the_runtime_agent_task_mapping(
    repository: SimpleNamespace,
) -> None:
    released: list[str] = []
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(
            return_value=SimpleNamespace(status="processing", result_data={}, accumulated_artifacts=None, execution_timeline=[])
        ),
        broadcast_status=AsyncMock(),
        release_agent_task=released.append,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="processing")
    )

    assert released == []


@pytest.mark.asyncio
async def test_duplicate_terminal_event_retains_runtime_agent_task_mapping(
    repository: SimpleNamespace,
) -> None:
    repository.find_conversation_turn_by_agent_task_id.return_value["metadata"] = routed_metadata(
        lifecycle="completed",
        terminal_outcome="Paprika finished the task.",
        narration_lifecycle="ready",
    )
    released: list[str] = []
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=AsyncMock(),
        release_agent_task=released.append,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(agent_task_id="task-1", event_type="status_changed", new_status="completed")
    )

    assert released == []


@pytest.mark.asyncio
async def test_submission_failure_retains_runtime_agent_task_mapping_for_narration(
    repository: SimpleNamespace,
) -> None:
    released: list[str] = []
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=AsyncMock(),
        release_agent_task=released.append,
    )

    await lifecycle.record_submission_failure(link(), "Submission unavailable.")

    assert released == []


def test_registration_wires_the_shared_runtime_release_callback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from api.routes.websocket_routes.conversation_request_runtime import (
        conversation_request_runtime,
    )

    database = SimpleNamespace(
        db_path=tmp_path / "conversation-callback.db",
        get_agent_task=AsyncMock(),
        register_agent_task_callback=lambda _callback: None,
    )
    monkeypatch.setattr(lifecycle_module, "_callback_registered", False)
    monkeypatch.setattr(lifecycle_module, "_registered_lifecycle", None)
    monkeypatch.setattr(lifecycle_module, "get_sqlite_knowledge_service", lambda: database)

    lifecycle_module.ensure_conversation_agent_turn_callback_registered()

    registered = lifecycle_module.get_registered_conversation_agent_turn_lifecycle()
    assert registered._release_agent_task == conversation_request_runtime.release_agent_task


@pytest.mark.asyncio
async def test_checkpoint_status_projects_a_durable_attention_marker(
    repository: SimpleNamespace,
) -> None:
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=AsyncMock(),
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_event(
        AgentTaskEvent(
            agent_task_id="task-1",
            event_type="status_changed",
            new_status="awaiting_user_input",
            agent_task_data={
                "status": "awaiting_user_input",
                "result_data": {
                    "checkpoint_data": {
                        "checkpoint_id": "checkpoint-1",
                    }
                },
            },
        )
    )

    patch = repository.merge_message_metadata.await_args.args[1]["conversation_turn"]
    assert patch["requires_user_attention"] is True
    assert patch["attention_id"] == "checkpoint-1"
    payload = lifecycle._broadcast_status.await_args.args[0]
    assert payload["requires_user_attention"] is True
    assert payload["attention_id"] == "checkpoint-1"


@pytest.mark.asyncio
async def test_stale_attention_resolution_cannot_clear_newer_prompt(
    repository: SimpleNamespace,
) -> None:
    repository.find_conversation_turn_by_agent_task_id.return_value["metadata"] = {
        "conversation_turn": {
            "route": "agent_task",
            "lifecycle": "running",
            "agent_task_id": "task-1",
            "terminal_outcome": None,
            "user_message_id": "user-1",
            "narration": {"lifecycle": "pending", "attempt_count": 0},
            "requires_user_attention": True,
            "attention_id": "checkpoint-new",
        }
    }
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=AsyncMock(),
    )
    lifecycle.register_link(link())

    await lifecycle.clear_agent_task_attention("task-1", "checkpoint-old")

    repository.merge_message_metadata.assert_not_awaited()
    lifecycle._broadcast_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_matching_attention_resolution_clears_the_marker(
    repository: SimpleNamespace,
) -> None:
    repository.find_conversation_turn_by_agent_task_id.return_value["metadata"] = {
        "conversation_turn": {
            "route": "agent_task",
            "lifecycle": "running",
            "agent_task_id": "task-1",
            "terminal_outcome": None,
            "user_message_id": "user-1",
            "narration": {"lifecycle": "pending", "attempt_count": 0},
            "requires_user_attention": True,
            "attention_id": "checkpoint-1",
        }
    }
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=AsyncMock(),
    )
    lifecycle.register_link(link())

    await lifecycle.clear_agent_task_attention("task-1", "checkpoint-1")

    patch = repository.merge_message_metadata.await_args.args[1]["conversation_turn"]
    assert patch["requires_user_attention"] is False
    assert patch["attention_id"] is None


@pytest.mark.asyncio
async def test_multiple_attention_markers_clear_independently(
    repository: SimpleNamespace,
) -> None:
    repository.find_conversation_turn_by_agent_task_id.return_value["metadata"] = {
        "conversation_turn": {
            "route": "agent_task",
            "lifecycle": "running",
            "agent_task_id": "task-1",
            "terminal_outcome": None,
            "user_message_id": "user-1",
            "narration": {"lifecycle": "pending", "attempt_count": 0},
            "requires_user_attention": True,
            "attention_id": "approval-1",
            "attention_ids": ["approval-1", "approval-2"],
        }
    }
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(),
        broadcast_status=AsyncMock(),
    )
    lifecycle.register_link(link())

    await lifecycle.clear_agent_task_attention("task-1", "approval-1")

    patch = repository.merge_message_metadata.await_args.args[1]["conversation_turn"]
    assert patch["requires_user_attention"] is True
    assert patch["attention_id"] == "approval-2"
    assert patch["attention_ids"] == ["approval-2"]


@pytest.mark.asyncio
async def test_attention_transitions_update_the_durable_activity_summary() -> None:
    metadata = routed_metadata(lifecycle="running")

    async def merge_metadata(_: str, patch: dict) -> None:
        metadata["conversation_turn"].update(patch["conversation_turn"])

    repository = SimpleNamespace(
        find_conversation_turn_by_agent_task_id=AsyncMock(
            return_value={
                "conversation_id": "conversation-1",
                "assistant_message_id": "assistant-1",
                "assistant_model_id": "selected-model",
                "metadata": metadata,
            }
        ),
        merge_message_metadata=AsyncMock(side_effect=merge_metadata),
        update_message=AsyncMock(),
    )
    broadcast_activity = AsyncMock()
    lifecycle = ConversationAgentTurnLifecycle(
        repository=repository,
        get_agent_task=AsyncMock(return_value=activity_task()),
        broadcast_status=AsyncMock(),
        broadcast_activity=broadcast_activity,
    )
    lifecycle.register_link(link())

    await lifecycle.handle_agent_task_attention("task-1", "approval-1")
    assert metadata["conversation_turn"]["activity_summary"]["requires_user_attention"] is True

    await lifecycle.clear_agent_task_attention("task-1", "approval-1")

    assert metadata["conversation_turn"]["activity_summary"]["requires_user_attention"] is False
    assert broadcast_activity.await_count == 2
