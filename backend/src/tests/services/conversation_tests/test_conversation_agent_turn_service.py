from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.conversation.conversation_agent_turn_lifecycle import ConversationAgentTurnLink
from api.services.conversation.conversation_agent_turn_service import (
    ConversationAgentTurnService,
    _CONVERSATION_AGENT_TASK_INSTRUCTION,
)
from api.services.conversation.conversation_turn_contract import (
    ConversationTaskContinuationCandidate,
    ConversationTurnRoute,
)


@pytest.fixture
def repository() -> SimpleNamespace:
    return SimpleNamespace(merge_message_metadata=AsyncMock())


@pytest.fixture
def lifecycle() -> SimpleNamespace:
    return SimpleNamespace(
        register_link=lambda link: registered_links.append(link),
        record_submission_failure=AsyncMock(),
    )


registered_links: list[ConversationAgentTurnLink] = []


@pytest.fixture(autouse=True)
def clear_registered_links() -> None:
    registered_links.clear()


def empty_agent_task_service() -> SimpleNamespace:
    return SimpleNamespace(
        list_recent_conversation_task_summaries=AsyncMock(return_value=[]),
        get_agent_task=AsyncMock(return_value=None),
        get_agent_task_chain=AsyncMock(return_value=[]),
    )


def continuation_candidate(
    root_task_id: str = "root-1",
    previous_task_id: str = "leaf-1",
) -> ConversationTaskContinuationCandidate:
    return ConversationTaskContinuationCandidate(
        candidate_id=1,
        root_task_id=root_task_id,
        previous_task_id=previous_task_id,
        request_text="Prepare the delivery plan.",
        outcome_text="Delivery plan completed.",
        terminal_status="completed",
    )


@pytest.mark.asyncio
async def test_continuation_candidates_use_only_valid_terminal_summaries(
    repository: SimpleNamespace,
    lifecycle: SimpleNamespace,
) -> None:
    agent_task_service = empty_agent_task_service()
    agent_task_service.list_recent_conversation_task_summaries = AsyncMock(
        return_value=[
            {
                "root_task_id": "root-1",
                "previous_task_id": "leaf-1",
                "request_text": "A" * 700,
                "outcome_text": "Completed.",
                "status": "completed",
            },
            "malformed summary",
            {
                "root_task_id": "root-2",
                "previous_task_id": "leaf-2",
                "request_text": "Ignored active task.",
                "outcome_text": "",
                "status": "processing",
            },
            {
                "root_task_id": "root-3",
                "previous_task_id": "leaf-3",
                "request_text": "Retry the failed work.",
                "outcome_text": "Failed.",
                "status": "failed",
            },
        ]
    )
    service = ConversationAgentTurnService(
        repository=repository,
        submission_service=SimpleNamespace(process_agent_task_direct=AsyncMock()),
        agent_task_service=agent_task_service,
        lifecycle=lifecycle,
    )

    candidates = await service.list_continuation_candidates("conversation-1")

    assert [(candidate.candidate_id, candidate.root_task_id) for candidate in candidates] == [
        (1, "root-1"),
        (2, "root-3"),
    ]
    assert candidates[0].request_text == "A" * 600
    agent_task_service.list_recent_conversation_task_summaries.assert_awaited_once_with(
        "conversation-1",
        limit=3,
    )


@pytest.mark.asyncio
async def test_agent_task_submission_persists_link_before_submission(
    repository: SimpleNamespace,
    lifecycle: SimpleNamespace,
) -> None:
    operation_order: list[str] = []
    repository.merge_message_metadata.side_effect = lambda *_: operation_order.append("metadata")
    lifecycle.register_link = lambda _: operation_order.append("link")

    async def submit(**_):
        assert operation_order == ["metadata", "link"]
        operation_order.append("submit")
        return {"success": True, "status": "routing"}

    submission_service = SimpleNamespace(
        process_agent_task_direct=AsyncMock(side_effect=submit)
    )
    service = ConversationAgentTurnService(
        repository=repository,
        submission_service=submission_service,
        agent_task_service=empty_agent_task_service(),
        lifecycle=lifecycle,
    )

    link = await service.submit_turn(
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        route=ConversationTurnRoute.AGENT_TASK,
        content="Summarize this conversation.",
        display_prompt_markdown="Summarize this conversation.",
        reference_paths=["/tmp/reference.txt"],
        model_id="model-1",
    )

    assert repository.merge_message_metadata.await_args.args[0] == "assistant-1"
    metadata_patch = repository.merge_message_metadata.await_args.args[1]["conversation_turn"]
    assert metadata_patch["agent_task_id"] == link.agent_task_id
    assert metadata_patch["lifecycle"] == "pending"
    assert metadata_patch["user_message_id"] == "user-1"
    assert metadata_patch["narration"] == {"lifecycle": "pending"}
    assert operation_order == ["metadata", "link", "submit"]
    assert registered_links == []
    submission_service.process_agent_task_direct.assert_awaited_once_with(
        agent_task=f"{_CONVERSATION_AGENT_TASK_INSTRUCTION}\n\nUser request:\nSummarize this conversation.",
        display_prompt_markdown="Summarize this conversation.",
        agent_task_id=link.agent_task_id,
        reference_paths=["/tmp/reference.txt"],
        model_id="model-1",
        conversation_id="conversation-1",
        origin_type="conversation",
        origin_id="conversation-1",
    )


@pytest.mark.asyncio
async def test_link_callback_runs_after_registration_and_before_submission(
    repository: SimpleNamespace,
    lifecycle: SimpleNamespace,
) -> None:
    operation_order: list[str] = []
    repository.merge_message_metadata.side_effect = lambda *_: operation_order.append("metadata")
    lifecycle.register_link = lambda _: operation_order.append("link")

    async def on_link_persisted(link: ConversationAgentTurnLink) -> None:
        assert link.conversation_id == "conversation-1"
        operation_order.append("callback")

    async def submit(**_) -> dict:
        assert operation_order == ["metadata", "link", "callback"]
        operation_order.append("submit")
        return {"success": True, "status": "routing"}

    service = ConversationAgentTurnService(
        repository=repository,
        submission_service=SimpleNamespace(process_agent_task_direct=AsyncMock(side_effect=submit)),
        agent_task_service=empty_agent_task_service(),
        lifecycle=lifecycle,
    )

    await service.submit_turn(
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        route=ConversationTurnRoute.AGENT_TASK,
        content="Summarize this conversation.",
        display_prompt_markdown=None,
        reference_paths=None,
        model_id=None,
        on_link_persisted=on_link_persisted,
    )

    assert operation_order == ["metadata", "link", "callback", "submit"]


@pytest.mark.asyncio
async def test_link_callback_failure_projects_the_durable_placeholder(
    repository: SimpleNamespace,
    lifecycle: SimpleNamespace,
) -> None:
    submission_service = SimpleNamespace(process_agent_task_direct=AsyncMock())
    service = ConversationAgentTurnService(
        repository=repository,
        submission_service=submission_service,
        agent_task_service=empty_agent_task_service(),
        lifecycle=lifecycle,
    )

    async def failing_callback(_link: ConversationAgentTurnLink) -> None:
        raise RuntimeError("cancellation unavailable")

    await service.submit_turn(
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        route=ConversationTurnRoute.AGENT_TASK,
        content="Summarize this conversation.",
        display_prompt_markdown=None,
        reference_paths=None,
        model_id=None,
        on_link_persisted=failing_callback,
    )

    submission_service.process_agent_task_direct.assert_not_awaited()
    assert lifecycle.record_submission_failure.await_args.args[1] == "cancellation unavailable"


@pytest.mark.asyncio
async def test_metadata_persistence_failure_prevents_link_registration_and_submission(
    repository: SimpleNamespace,
    lifecycle: SimpleNamespace,
) -> None:
    repository.merge_message_metadata.side_effect = RuntimeError("metadata unavailable")
    submission_service = SimpleNamespace(process_agent_task_direct=AsyncMock())
    service = ConversationAgentTurnService(
        repository=repository,
        submission_service=submission_service,
        agent_task_service=empty_agent_task_service(),
        lifecycle=lifecycle,
    )

    with pytest.raises(RuntimeError, match="metadata unavailable"):
        await service.submit_turn(
            conversation_id="conversation-1",
            user_message_id="user-1",
            assistant_message_id="assistant-1",
            route=ConversationTurnRoute.AGENT_TASK,
            content="Summarize this conversation.",
            display_prompt_markdown="Summarize this conversation.",
            reference_paths=None,
            model_id=None,
        )

    assert registered_links == []
    submission_service.process_agent_task_direct.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_task_submission_prefixes_conversation_instruction(
    repository: SimpleNamespace,
    lifecycle: SimpleNamespace,
) -> None:
    submission_service = SimpleNamespace(
        process_agent_task_direct=AsyncMock(return_value={"success": True, "status": "routing"})
    )
    service = ConversationAgentTurnService(
        repository=repository,
        submission_service=submission_service,
        agent_task_service=empty_agent_task_service(),
        lifecycle=lifecycle,
    )

    await service.submit_turn(
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        route=ConversationTurnRoute.AGENT_TASK,
        content="Edit the release notes.",
        display_prompt_markdown="Edit the release notes.",
        reference_paths=None,
        model_id=None,
    )

    assert submission_service.process_agent_task_direct.await_args.kwargs["agent_task"] == (
        f"{_CONVERSATION_AGENT_TASK_INSTRUCTION}\n\nUser request:\nEdit the release notes."
    )
    assert submission_service.process_agent_task_direct.await_args.kwargs["display_prompt_markdown"] == "Edit the release notes."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "submission_result",
    [
        {"success": False, "status": "failed", "error": "rejected"},
        {"success": True, "status": "canceled", "message": "canceled"},
        "invalid-result",
    ],
)
async def test_submission_failures_project_terminal_placeholder_state(
    repository: SimpleNamespace,
    lifecycle: SimpleNamespace,
    submission_result: object,
) -> None:
    submission_service = SimpleNamespace(
        process_agent_task_direct=AsyncMock(return_value=submission_result)
    )
    service = ConversationAgentTurnService(
        repository=repository,
        submission_service=submission_service,
        agent_task_service=empty_agent_task_service(),
        lifecycle=lifecycle,
    )

    link = await service.submit_turn(
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        route=ConversationTurnRoute.AGENT_TASK,
        content="Do work.",
        display_prompt_markdown=None,
        reference_paths=None,
        model_id=None,
    )

    lifecycle.record_submission_failure.assert_awaited_once()
    assert lifecycle.record_submission_failure.await_args.args[0] == link


@pytest.mark.asyncio
async def test_submission_exception_projects_terminal_placeholder_state(
    repository: SimpleNamespace,
    lifecycle: SimpleNamespace,
) -> None:
    submission_service = SimpleNamespace(
        process_agent_task_direct=AsyncMock(side_effect=RuntimeError("submission exploded"))
    )
    service = ConversationAgentTurnService(
        repository=repository,
        submission_service=submission_service,
        agent_task_service=empty_agent_task_service(),
        lifecycle=lifecycle,
    )

    await service.submit_turn(
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        route=ConversationTurnRoute.AGENT_TASK,
        content="Do work.",
        display_prompt_markdown=None,
        reference_paths=None,
        model_id=None,
    )

    assert lifecycle.record_submission_failure.await_args.args[1] == "submission exploded"


@pytest.mark.asyncio
async def test_direct_route_is_rejected_without_persistence_or_submission(
    repository: SimpleNamespace,
    lifecycle: SimpleNamespace,
) -> None:
    submission_service = SimpleNamespace(process_agent_task_direct=AsyncMock())
    service = ConversationAgentTurnService(
        repository=repository,
        submission_service=submission_service,
        agent_task_service=empty_agent_task_service(),
        lifecycle=lifecycle,
    )

    with pytest.raises(ValueError, match="only accepts the agent_task route"):
        await service.submit_turn(
            conversation_id="conversation-1",
            user_message_id="user-1",
            assistant_message_id="assistant-1",
            route=ConversationTurnRoute.DIRECT,
            content="Hello.",
            display_prompt_markdown=None,
            reference_paths=None,
            model_id=None,
        )

    repository.merge_message_metadata.assert_not_awaited()
    submission_service.process_agent_task_direct.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("leaf_status", ["completed", "failed", "canceled"])
async def test_terminal_conversation_candidate_submits_a_linked_child(
    repository: SimpleNamespace,
    lifecycle: SimpleNamespace,
    leaf_status: str,
) -> None:
    root = SimpleNamespace(
        id="root-1",
        root_task_id="root-1",
        origin_type="conversation",
        origin_id="conversation-1",
        status="completed",
    )
    leaf = SimpleNamespace(id="leaf-1", status=leaf_status)
    agent_task_service = SimpleNamespace(
        list_recent_conversation_task_summaries=AsyncMock(return_value=[]),
        get_agent_task=AsyncMock(return_value=root),
        get_agent_task_chain=AsyncMock(return_value=[root, leaf]),
    )
    submission_service = SimpleNamespace(
        process_agent_task_direct=AsyncMock(return_value={"success": True, "status": "routing"})
    )
    service = ConversationAgentTurnService(
        repository=repository,
        submission_service=submission_service,
        agent_task_service=agent_task_service,
        lifecycle=lifecycle,
    )

    await service.submit_turn(
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        route=ConversationTurnRoute.AGENT_TASK,
        content="Break the plan down by owner.",
        display_prompt_markdown=None,
        reference_paths=None,
        model_id=None,
        continuation_candidate=continuation_candidate(),
    )

    assert submission_service.process_agent_task_direct.await_args.kwargs["root_task_id"] == "root-1"
    assert submission_service.process_agent_task_direct.await_args.kwargs["previous_task_id"] == "leaf-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["missing", "foreign", "active"])
async def test_invalid_continuation_candidate_uses_a_new_root(
    repository: SimpleNamespace,
    lifecycle: SimpleNamespace,
    scenario: str,
) -> None:
    root = None
    chain = []
    if scenario == "foreign":
        root = SimpleNamespace(
            id="root-1",
            root_task_id="root-1",
            origin_type="conversation",
            origin_id="conversation-2",
            status="completed",
        )
        chain = [root]
    if scenario == "active":
        root = SimpleNamespace(
            id="root-1",
            root_task_id="root-1",
            origin_type="conversation",
            origin_id="conversation-1",
            status="completed",
        )
        chain = [root, SimpleNamespace(id="leaf-1", status="processing")]
    agent_task_service = SimpleNamespace(
        list_recent_conversation_task_summaries=AsyncMock(return_value=[]),
        get_agent_task=AsyncMock(return_value=root),
        get_agent_task_chain=AsyncMock(return_value=chain),
    )
    submission_service = SimpleNamespace(
        process_agent_task_direct=AsyncMock(return_value={"success": True, "status": "routing"})
    )
    service = ConversationAgentTurnService(
        repository=repository,
        submission_service=submission_service,
        agent_task_service=agent_task_service,
        lifecycle=lifecycle,
    )

    await service.submit_turn(
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
        route=ConversationTurnRoute.AGENT_TASK,
        content="Continue the work.",
        display_prompt_markdown=None,
        reference_paths=None,
        model_id=None,
        continuation_candidate=continuation_candidate(),
    )

    kwargs = submission_service.process_agent_task_direct.await_args.kwargs
    assert "root_task_id" not in kwargs
    assert "previous_task_id" not in kwargs
