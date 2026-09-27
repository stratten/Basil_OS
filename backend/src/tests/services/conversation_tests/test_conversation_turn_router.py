import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.services.conversation.conversation_agent_turn_lifecycle import ConversationAgentTurnLink
from api.services.conversation.conversation_models import ConversationError, MessageRole
from api.services.conversation.conversation_route_selector import ConversationRouteDecision
from api.services.conversation.conversation_turn_contract import (
    ConversationTaskContinuationCandidate,
    ConversationTurnRoute,
)
from api.core.knowledge.sqlite.conversation_repository import ConversationTurnAdmissionConflict
from api.services.conversation.conversation_turn_router import (
    AgentTaskConversationTurn,
    ConversationTurnAlreadyActiveError,
    ConversationTurnRequest,
    ConversationTurnRouter,
    DEFAULT_CONVERSATION_SYSTEM_MESSAGE,
    DirectConversationTurn,
)


def build_conversation(user_message_count: int = 0):
    messages = [SimpleNamespace(role=MessageRole.USER) for _ in range(user_message_count)]
    return SimpleNamespace(id="conversation-1", messages=messages)


def build_repository(bounded_messages=None, pair=None, latest_turn_metadata=None, admit_raises=None):
    default_pair = pair or SimpleNamespace(
        conversation_id="conversation-1",
        user_message_id="user-1",
        assistant_message_id="assistant-1",
    )
    admit_mock = AsyncMock(return_value=default_pair)
    if admit_raises is not None:
        admit_mock.side_effect = admit_raises
    return SimpleNamespace(
        get_bounded_recent_messages=AsyncMock(return_value=bounded_messages or []),
        get_latest_conversation_turn_metadata=AsyncMock(return_value=latest_turn_metadata),
        create_message_pair=AsyncMock(return_value=default_pair),
        admit_and_create_message_pair=admit_mock,
    )


def build_conversation_service(*, conversation=None, repository=None, create_conversation_id="created-conversation"):
    repository = repository or build_repository()
    return SimpleNamespace(
        conversation_repository=repository,
        get_conversation=AsyncMock(return_value=conversation),
        create_conversation=AsyncMock(return_value=SimpleNamespace(id=create_conversation_id, messages=[])),
        _auto_title_conversation=AsyncMock(),
        _schedule_background_task=MagicMock(),
    )


def build_route_selector(route: ConversationTurnRoute):
    return SimpleNamespace(select_route=AsyncMock(return_value=ConversationRouteDecision(route=route)))


def build_agent_turn_service(agent_task_id: str = "task-1"):
    return SimpleNamespace(
        list_continuation_candidates=AsyncMock(return_value=[]),
        submit_turn=AsyncMock(
            return_value=ConversationAgentTurnLink(
                conversation_id="conversation-1",
                user_message_id="user-1",
                assistant_message_id="assistant-1",
                agent_task_id=agent_task_id,
                route=ConversationTurnRoute.AGENT_TASK,
                model_id=None,
            )
        )
    )


def build_request(**overrides) -> ConversationTurnRequest:
    defaults = dict(
        content="Hello",
        conversation_id="conversation-1",
        model_id=None,
        file_paths=None,
        message_metadata={"surface": "basil_board_chats"},
        display_prompt_markdown=None,
        delegation_opt_out=False,
        use_streaming=False,
    )
    defaults.update(overrides)
    return ConversationTurnRequest(**defaults)


@pytest.mark.asyncio
async def test_direct_route_returns_turn_without_creating_a_pair():
    conversation = build_conversation(user_message_count=1)
    repository = build_repository()
    conversation_service = build_conversation_service(conversation=conversation, repository=repository)
    agent_turn_service = build_agent_turn_service()
    router = ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=build_route_selector(ConversationTurnRoute.DIRECT),
        agent_turn_service=agent_turn_service,
    )

    result = await router.route_turn(build_request(use_streaming=True))

    assert result == DirectConversationTurn(
        conversation_id="conversation-1",
        content="Hello",
        model_id=None,
        file_paths=None,
        message_metadata={"surface": "basil_board_chats"},
        use_streaming=True,
    )
    repository.admit_and_create_message_pair.assert_not_awaited()
    agent_turn_service.submit_turn.assert_not_awaited()
    conversation_service._auto_title_conversation.assert_not_called()


@pytest.mark.asyncio
async def test_non_streaming_direct_route_is_preserved():
    conversation = build_conversation(user_message_count=1)
    conversation_service = build_conversation_service(conversation=conversation)
    router = ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=build_route_selector(ConversationTurnRoute.DIRECT),
        agent_turn_service=build_agent_turn_service(),
    )

    result = await router.route_turn(build_request(use_streaming=False))

    assert isinstance(result, DirectConversationTurn)
    assert result.use_streaming is False


@pytest.mark.asyncio
async def test_opt_out_is_forwarded_to_the_selector_and_returns_direct():
    conversation = build_conversation(user_message_count=1)
    conversation_service = build_conversation_service(conversation=conversation)
    route_selector = build_route_selector(ConversationTurnRoute.DIRECT)
    router = ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=route_selector,
        agent_turn_service=build_agent_turn_service(),
    )

    result = await router.route_turn(build_request(delegation_opt_out=True))

    assert isinstance(result, DirectConversationTurn)
    assert route_selector.select_route.await_args.kwargs["delegation_opt_out"] is True


@pytest.mark.asyncio
async def test_agent_task_route_creates_pair_with_attachment_metadata_and_bridges_to_submission(tmp_path):
    notes_file = tmp_path / "notes.txt"
    notes_file.write_text("release notes", encoding="utf-8")
    conversation = build_conversation(user_message_count=1)
    repository = build_repository(
        pair=SimpleNamespace(
            conversation_id="conversation-1",
            user_message_id="user-2",
            assistant_message_id="assistant-2",
        )
    )
    conversation_service = build_conversation_service(conversation=conversation, repository=repository)
    agent_turn_service = build_agent_turn_service(agent_task_id="task-42")
    router = ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=build_route_selector(ConversationTurnRoute.AGENT_TASK),
        agent_turn_service=agent_turn_service,
    )

    result = await router.route_turn(
        build_request(
            content="Write the release notes.",
            model_id="model-1",
            file_paths=[str(notes_file)],
            message_metadata={"surface": "basil_board_chats", "request_id": "request-1"},
            display_prompt_markdown="Write the release notes.",
        )
    )

    assert result == AgentTaskConversationTurn(
        conversation_id="conversation-1",
        user_message_id="user-2",
        assistant_message_id="assistant-2",
        agent_task_id="task-42",
    )
    pair_kwargs = repository.admit_and_create_message_pair.await_args.kwargs
    assert pair_kwargs["conversation_id"] == "conversation-1"
    assert pair_kwargs["user_content"] == "Write the release notes."
    assert pair_kwargs["user_metadata"]["surface"] == "basil_board_chats"
    assert pair_kwargs["user_metadata"]["request_id"] == "request-1"
    assert pair_kwargs["user_metadata"]["attached_files"][0]["filename"] == "notes.txt"
    assert pair_kwargs["assistant_metadata"]["conversation_turn"]["route"] == "agent_task"
    assert pair_kwargs["assistant_model_id"] == "model-1"
    agent_turn_service.submit_turn.assert_awaited_once_with(
        conversation_id="conversation-1",
        user_message_id="user-2",
        assistant_message_id="assistant-2",
        route=ConversationTurnRoute.AGENT_TASK,
        content="Write the release notes.",
        display_prompt_markdown="Write the release notes.",
        reference_paths=[str(notes_file)],
        model_id="model-1",
        continuation_candidate=None,
    )


@pytest.mark.asyncio
async def test_agent_task_route_forwards_only_the_model_selected_continuation_candidate():
    conversation = build_conversation(user_message_count=1)
    conversation_service = build_conversation_service(conversation=conversation)
    selected = ConversationTaskContinuationCandidate(
        candidate_id=2,
        root_task_id="root-2",
        previous_task_id="leaf-2",
        request_text="Summarize the project.",
        outcome_text="Project summary completed.",
        terminal_status="completed",
    )
    ignored = ConversationTaskContinuationCandidate(
        candidate_id=1,
        root_task_id="root-1",
        previous_task_id="leaf-1",
        request_text="Unrelated task.",
        outcome_text="Unrelated completion.",
        terminal_status="completed",
    )
    agent_turn_service = build_agent_turn_service()
    agent_turn_service.list_continuation_candidates = AsyncMock(return_value=[ignored, selected])
    route_selector = SimpleNamespace(
        select_route=AsyncMock(
            return_value=ConversationRouteDecision(
                route=ConversationTurnRoute.AGENT_TASK,
                continuation_candidate_id=2,
            )
        )
    )
    router = ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=route_selector,
        agent_turn_service=agent_turn_service,
    )

    await router.route_turn(build_request(content="Give a detailed breakdown."))

    route_selector.select_route.assert_awaited_once()
    assert route_selector.select_route.await_args.kwargs["continuation_candidates"] == [ignored, selected]
    assert agent_turn_service.submit_turn.await_args.kwargs["continuation_candidate"] == selected


@pytest.mark.asyncio
async def test_agent_task_route_uses_a_new_root_when_the_decision_ordinal_is_unknown():
    conversation = build_conversation(user_message_count=1)
    conversation_service = build_conversation_service(conversation=conversation)
    candidate = ConversationTaskContinuationCandidate(
        candidate_id=1,
        root_task_id="root-1",
        previous_task_id="leaf-1",
        request_text="Prior work.",
        outcome_text="Prior outcome.",
        terminal_status="completed",
    )
    agent_turn_service = build_agent_turn_service()
    agent_turn_service.list_continuation_candidates = AsyncMock(return_value=[candidate])
    router = ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=SimpleNamespace(
            select_route=AsyncMock(
                return_value=ConversationRouteDecision(
                    route=ConversationTurnRoute.AGENT_TASK,
                    continuation_candidate_id=99,
                )
            )
        ),
        agent_turn_service=agent_turn_service,
    )

    await router.route_turn(build_request())

    assert agent_turn_service.submit_turn.await_args.kwargs["continuation_candidate"] is None


@pytest.mark.asyncio
async def test_agent_task_route_without_attachments_omits_attached_files_key():
    conversation = build_conversation(user_message_count=1)
    repository = build_repository()
    conversation_service = build_conversation_service(conversation=conversation, repository=repository)
    router = ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=build_route_selector(ConversationTurnRoute.AGENT_TASK),
        agent_turn_service=build_agent_turn_service(),
    )

    await router.route_turn(build_request(file_paths=None))

    pair_kwargs = repository.admit_and_create_message_pair.await_args.kwargs
    assert "attached_files" not in pair_kwargs["user_metadata"]


@pytest.mark.asyncio
async def test_agent_task_route_forwards_link_callback_to_the_bridge():
    conversation = build_conversation(user_message_count=1)
    conversation_service = build_conversation_service(conversation=conversation)
    agent_turn_service = build_agent_turn_service()
    router = ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=build_route_selector(ConversationTurnRoute.AGENT_TASK),
        agent_turn_service=agent_turn_service,
    )
    on_link_persisted = AsyncMock()

    await router.route_turn(
        build_request(),
        on_link_persisted=on_link_persisted,
    )

    assert agent_turn_service.submit_turn.await_args.kwargs["on_link_persisted"] is on_link_persisted


@pytest.mark.asyncio
async def test_agent_task_route_schedules_auto_title_only_for_first_user_message():
    conversation_with_history = build_conversation(user_message_count=1)
    service_with_history = build_conversation_service(conversation=conversation_with_history)
    router = ConversationTurnRouter(
        conversation_service=service_with_history,
        route_selector=build_route_selector(ConversationTurnRoute.AGENT_TASK),
        agent_turn_service=build_agent_turn_service(),
    )

    await router.route_turn(build_request())

    service_with_history._schedule_background_task.assert_not_called()

    conversation_without_history = build_conversation(user_message_count=0)
    service_without_history = build_conversation_service(conversation=conversation_without_history)
    router_new = ConversationTurnRouter(
        conversation_service=service_without_history,
        route_selector=build_route_selector(ConversationTurnRoute.AGENT_TASK),
        agent_turn_service=build_agent_turn_service(),
    )

    await router_new.route_turn(build_request())

    service_without_history._schedule_background_task.assert_called_once()
    coroutine, task_name = service_without_history._schedule_background_task.call_args.args
    assert task_name == "conversation-auto-title-conversation-1"
    coroutine.close()


@pytest.mark.asyncio
async def test_missing_conversation_id_creates_a_conversation_with_default_system_message():
    conversation_service = build_conversation_service(conversation=None, create_conversation_id="new-conversation")
    router = ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=build_route_selector(ConversationTurnRoute.DIRECT),
        agent_turn_service=build_agent_turn_service(),
    )

    result = await router.route_turn(build_request(conversation_id=None))

    conversation_service.create_conversation.assert_awaited_once_with(
        system_message=DEFAULT_CONVERSATION_SYSTEM_MESSAGE
    )
    conversation_service.get_conversation.assert_not_awaited()
    assert result.conversation_id == "new-conversation"


@pytest.mark.asyncio
async def test_missing_existing_conversation_raises_without_creating_a_pair_or_submitting():
    conversation_service = build_conversation_service(conversation=None)
    repository = conversation_service.conversation_repository
    router = ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=build_route_selector(ConversationTurnRoute.AGENT_TASK),
        agent_turn_service=build_agent_turn_service(),
    )

    with pytest.raises(ConversationError, match="conversation-1 not found"):
        await router.route_turn(build_request(conversation_id="conversation-1"))

    repository.admit_and_create_message_pair.assert_not_awaited()
    conversation_service.create_conversation.assert_not_awaited()


@pytest.mark.asyncio
async def test_route_turn_rejects_a_running_direct_turn_for_the_same_conversation():
    conversation = build_conversation(user_message_count=1)
    repository = build_repository(
        admit_raises=ConversationTurnAdmissionConflict("conversation-1"),
    )
    conversation_service = build_conversation_service(conversation=conversation, repository=repository)
    router = ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=build_route_selector(ConversationTurnRoute.AGENT_TASK),
        agent_turn_service=build_agent_turn_service(),
    )

    with pytest.raises(ConversationTurnAlreadyActiveError):
        await router.route_turn(build_request())


@pytest.mark.asyncio
async def test_route_turn_rejects_an_agent_task_still_awaiting_narration():
    conversation = build_conversation(user_message_count=1)
    repository = build_repository(
        admit_raises=ConversationTurnAdmissionConflict("conversation-1"),
    )
    conversation_service = build_conversation_service(conversation=conversation, repository=repository)
    router = ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=build_route_selector(ConversationTurnRoute.AGENT_TASK),
        agent_turn_service=build_agent_turn_service(),
    )

    with pytest.raises(ConversationTurnAlreadyActiveError):
        await router.route_turn(build_request())


@pytest.mark.asyncio
async def test_route_turn_admits_a_conversation_whose_last_turn_fully_completed():
    conversation = build_conversation(user_message_count=1)
    repository = build_repository(
        latest_turn_metadata={
            "conversation_turn": {
                "route": "agent_task",
                "lifecycle": "completed",
                "agent_task_id": "task-1",
                "terminal_outcome": "Done",
                "user_message_id": "user-1",
                "narration": {"lifecycle": "completed", "attempt_count": 1},
            }
        }
    )
    conversation_service = build_conversation_service(conversation=conversation, repository=repository)
    router = ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=build_route_selector(ConversationTurnRoute.DIRECT),
        agent_turn_service=build_agent_turn_service(),
    )

    result = await router.route_turn(build_request())

    assert isinstance(result, DirectConversationTurn)


@pytest.mark.asyncio
async def test_route_turn_admits_a_conversation_with_malformed_turn_metadata():
    conversation = build_conversation(user_message_count=1)
    repository = build_repository(latest_turn_metadata={"conversation_turn": {"route": "not-a-real-route"}})
    conversation_service = build_conversation_service(conversation=conversation, repository=repository)
    router = ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=build_route_selector(ConversationTurnRoute.DIRECT),
        agent_turn_service=build_agent_turn_service(),
    )

    result = await router.route_turn(build_request())

    assert isinstance(result, DirectConversationTurn)


@pytest.mark.asyncio
async def test_route_turn_never_checks_admission_for_a_brand_new_conversation():
    conversation_service = build_conversation_service(conversation=None, create_conversation_id="new-conversation")
    router = ConversationTurnRouter(
        conversation_service=conversation_service,
        route_selector=build_route_selector(ConversationTurnRoute.DIRECT),
        agent_turn_service=build_agent_turn_service(),
    )

    result = await router.route_turn(build_request(conversation_id=None))

    conversation_service.conversation_repository.get_latest_conversation_turn_metadata.assert_not_awaited()
    assert result.conversation_id == "new-conversation"
