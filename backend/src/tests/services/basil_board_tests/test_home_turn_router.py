from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pydantic import ValidationError

from api.core.knowledge.sqlite.conversation_repository import ConversationRepository
from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.basil_board.home_turn_router import HomeTurnRouteClassifier, HomeTurnRouter
from api.services.basil_board.models import HomeTurnRequest, HomeTurnRouteKind, HomeTurnState
from api.services.basil_board.repository import BasilBoardRepository
from api.services.basil_board.service import BasilBoardService


def _build_router(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[HomeTurnRouter, BasilBoardService]:
    sqlite_service = SQLiteKnowledgeService(tmp_path / "basil_board_router.db")
    monkeypatch.setattr(
        "api.services.basil_board.service.get_sqlite_knowledge_service",
        lambda: sqlite_service,
    )
    board_service = BasilBoardService(BasilBoardRepository(str(sqlite_service.db_path)))
    conversation_service = SimpleNamespace(
        _get_model_for_task=AsyncMock(return_value=None),
        send_message=AsyncMock(),
        conversation_repository=ConversationRepository(sqlite_service=sqlite_service),
    )
    submission_service = SimpleNamespace(
        process_agent_task_direct=AsyncMock(return_value={"success": True, "status": "processing"}),
        cancel_agent_task_durably=AsyncMock(return_value={"canceled_task_ids": []}),
    )
    router = HomeTurnRouter(
        basil_board_service=board_service,
        conversation_service=conversation_service,
        agent_task_submission_service=submission_service,
    )
    return router, board_service


def _classify_as(route_kind: HomeTurnRouteKind, reason: str, confidence: float) -> AsyncMock:
    return AsyncMock(
        return_value=SimpleNamespace(route_kind=route_kind, reason=reason, confidence=confidence)
    )


@pytest.mark.asyncio
async def test_classifier_falls_back_to_agent_task_without_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, _ = _build_router(tmp_path, monkeypatch)
    route = await router._classifier.classify("Find my notes from yesterday")
    assert route.route_kind == HomeTurnRouteKind.AGENT_TASK


@pytest.mark.asyncio
async def test_conversation_route_hands_off_without_waiting_for_an_answer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, board_service = _build_router(tmp_path, monkeypatch)
    router._classifier.classify = _classify_as(HomeTurnRouteKind.CONVERSATION, "Direct chat", 0.95)

    response = await router.submit_turn(HomeTurnRequest(content="Hello"))

    router._conversation_service.send_message.assert_not_awaited()
    assert response.route_kind == HomeTurnRouteKind.CONVERSATION
    assert response.state == HomeTurnState.COMPLETED
    assert response.inquiry_id
    assert response.conversation_id
    assert response.user_message_id is None
    assert response.assistant_content is None

    inquiry = await board_service._repo.get_inquiry(response.inquiry_id)
    assert inquiry is not None
    assert inquiry.routeKind == HomeTurnRouteKind.CONVERSATION
    assert inquiry.state == HomeTurnState.COMPLETED
    assert inquiry.conversationId == response.conversation_id


@pytest.mark.asyncio
async def test_agent_task_route_allocates_task_and_marks_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, board_service = _build_router(tmp_path, monkeypatch)
    router._classifier.classify = _classify_as(HomeTurnRouteKind.AGENT_TASK, "Needs tools", 0.2)

    response = await router.submit_turn(HomeTurnRequest(content="Search my email history"))
    assert response.route_kind == HomeTurnRouteKind.AGENT_TASK
    assert response.agent_task_id
    assert response.state == HomeTurnState.RUNNING
    router._submission_service.process_agent_task_direct.assert_awaited_once()

    inquiry = await board_service._repo.get_inquiry(response.inquiry_id)
    assert inquiry is not None
    assert inquiry.agentTaskId == response.agent_task_id
    assert inquiry.state == HomeTurnState.RUNNING


@pytest.mark.asyncio
async def test_agent_task_failure_marks_inquiry_failed_and_reraises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, board_service = _build_router(tmp_path, monkeypatch)
    router._classifier.classify = _classify_as(HomeTurnRouteKind.AGENT_TASK, "Needs tools", 0.2)
    router._submission_service.process_agent_task_direct = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await router.submit_turn(HomeTurnRequest(content="Search my email history"))

    inquiries = await board_service._repo.list_recent_inquiries()
    assert len(inquiries) == 1
    assert inquiries[0].state == HomeTurnState.FAILED


@pytest.mark.asyncio
async def test_conversation_creation_failure_marks_inquiry_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, board_service = _build_router(tmp_path, monkeypatch)
    board_service.create_inquiry_conversation = AsyncMock(
        side_effect=RuntimeError("conversation creation failed")
    )

    with pytest.raises(RuntimeError, match="conversation creation failed"):
        await router.submit_turn(HomeTurnRequest(content="Hello"))

    inquiries = await board_service._repo.list_recent_inquiries()
    assert len(inquiries) == 1
    assert inquiries[0].state == HomeTurnState.FAILED


@pytest.mark.asyncio
async def test_classifier_accepts_high_confidence_conversation_json() -> None:
    conversation_service = SimpleNamespace(
        _get_model_for_task=AsyncMock(
            return_value=SimpleNamespace(
                chat_completion=AsyncMock(
                    return_value={
                        "content": '{"route_kind":"conversation","reason":"Small talk","confidence":0.91}'
                    }
                )
            )
        )
    )
    classifier = HomeTurnRouteClassifier(conversation_service)
    route = await classifier.classify("How are you?")
    assert route.route_kind == HomeTurnRouteKind.CONVERSATION
    assert route.confidence == pytest.approx(0.91)


@pytest.mark.asyncio
async def test_agent_task_route_passes_display_markdown_and_reference_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, _ = _build_router(tmp_path, monkeypatch)
    router._classifier.classify = _classify_as(HomeTurnRouteKind.AGENT_TASK, "Needs tools", 0.2)

    await router.submit_turn(
        HomeTurnRequest(
            content="Search my email history",
            display_prompt_markdown="Search my **email** history",
            reference_paths=["/tmp/inbox", "/tmp/archive"],
        )
    )

    call_kwargs = router._submission_service.process_agent_task_direct.await_args.kwargs
    assert call_kwargs["agent_task"] == "Search my email history"
    assert call_kwargs["display_prompt_markdown"] == "Search my **email** history"
    assert call_kwargs["reference_paths"] == ["/tmp/inbox", "/tmp/archive"]
    assert call_kwargs["origin_type"] == "conversation"
    assert call_kwargs["origin_id"] == call_kwargs["conversation_id"]


@pytest.mark.asyncio
async def test_each_inquiry_gets_its_own_conversation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two submissions must not share a conversation_id -- this is the
    core property that makes Recent Inquiries a list of independent
    records instead of one singleton scrollback."""
    router, board_service = _build_router(tmp_path, monkeypatch)
    router._classifier.classify = _classify_as(HomeTurnRouteKind.CONVERSATION, "Direct chat", 0.95)

    first = await router.submit_turn(HomeTurnRequest(content="First question"))
    second = await router.submit_turn(HomeTurnRequest(content="Second question"))

    first_inquiry = await board_service._repo.get_inquiry(first.inquiry_id)
    second_inquiry = await board_service._repo.get_inquiry(second.inquiry_id)
    assert first_inquiry.conversationId != second_inquiry.conversationId


@pytest.mark.asyncio
async def test_reroute_chat_to_agent_task_reuses_inquiry_and_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, board_service = _build_router(tmp_path, monkeypatch)
    router._classifier.classify = _classify_as(HomeTurnRouteKind.CONVERSATION, "Direct chat", 0.95)
    first = await router.submit_turn(
        HomeTurnRequest(
            content="Find my notes",
            display_prompt_markdown="Find my **notes**",
            reference_paths=["/tmp/a.txt"],
        )
    )

    rerouted = await router.reroute_inquiry(first.inquiry_id, HomeTurnRouteKind.AGENT_TASK)

    assert rerouted.inquiry_id == first.inquiry_id
    assert rerouted.route_kind == HomeTurnRouteKind.AGENT_TASK
    assert rerouted.agent_task_id
    assert rerouted.conversation_id and rerouted.conversation_id != first.conversation_id
    call_kwargs = router._submission_service.process_agent_task_direct.await_args.kwargs
    assert call_kwargs["agent_task"] == "Find my notes"
    assert call_kwargs["display_prompt_markdown"] == "Find my **notes**"
    assert call_kwargs["reference_paths"] == ["/tmp/a.txt"]
    inquiries = await board_service._repo.list_recent_inquiries()
    assert len(inquiries) == 1
    assert inquiries[0].routeKind == HomeTurnRouteKind.AGENT_TASK
    assert inquiries[0].agentTaskId == rerouted.agent_task_id
    assert inquiries[0].state == HomeTurnState.RUNNING


@pytest.mark.asyncio
async def test_reroute_agent_task_to_chat_cancels_running_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, board_service = _build_router(tmp_path, monkeypatch)
    router._classifier.classify = _classify_as(HomeTurnRouteKind.AGENT_TASK, "Needs tools", 0.2)
    first = await router.submit_turn(HomeTurnRequest(content="What is a haiku?"))

    rerouted = await router.reroute_inquiry(first.inquiry_id, HomeTurnRouteKind.CONVERSATION)

    router._submission_service.cancel_agent_task_durably.assert_awaited_once()
    assert router._submission_service.cancel_agent_task_durably.await_args.args[0] == first.agent_task_id
    assert rerouted.route_kind == HomeTurnRouteKind.CONVERSATION
    assert rerouted.agent_task_id is None
    assert rerouted.conversation_id and rerouted.conversation_id != first.conversation_id
    inquiry = await board_service._repo.get_inquiry(first.inquiry_id)
    assert inquiry is not None
    assert inquiry.routeKind == HomeTurnRouteKind.CONVERSATION
    assert inquiry.agentTaskId is None
    assert inquiry.conversationId == rerouted.conversation_id


@pytest.mark.asyncio
async def test_reroute_rejects_same_route_missing_inquiry_and_finished_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, board_service = _build_router(tmp_path, monkeypatch)
    router._classifier.classify = _classify_as(HomeTurnRouteKind.AGENT_TASK, "Needs tools", 0.2)
    first = await router.submit_turn(HomeTurnRequest(content="Search my email history"))

    with pytest.raises(ValueError, match="already routed"):
        await router.reroute_inquiry(first.inquiry_id, HomeTurnRouteKind.AGENT_TASK)
    with pytest.raises(LookupError):
        await router.reroute_inquiry("missing", HomeTurnRouteKind.CONVERSATION)

    await board_service.update_inquiry(first.inquiry_id, state=HomeTurnState.COMPLETED)
    with pytest.raises(ValueError, match="already finished"):
        await router.reroute_inquiry(first.inquiry_id, HomeTurnRouteKind.CONVERSATION)
    router._submission_service.cancel_agent_task_durably.assert_not_awaited()


def test_reference_paths_validator_normalizes_and_rejects() -> None:
    request = HomeTurnRequest(
        content="Hello",
        reference_paths=[" /tmp/a.txt ", "/tmp/a.txt", "/tmp/b.txt"],
    )
    assert request.reference_paths == ["/tmp/a.txt", "/tmp/b.txt"]

    with pytest.raises(ValidationError):
        HomeTurnRequest(content="Hello", reference_paths=[""])

    with pytest.raises(ValidationError):
        HomeTurnRequest(content="Hello", reference_paths=[f"/tmp/{index}.txt" for index in range(33)])
