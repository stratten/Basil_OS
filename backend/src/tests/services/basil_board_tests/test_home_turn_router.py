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
from api.services.conversation.conversation_models import (
    ConversationError,
    ConversationResponse,
    Message,
    MessageRole,
    ModelNotAvailableError,
)


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


async def _fake_send_message_success(conversation_id, content, *, model_id=None, file_paths=None, message_metadata=None):
    """Mirrors the real ConversationService.send_message contract closely
    enough to satisfy basil_board_inquiries' FK on user_message_id/
    assistant_message_id: both ids must be real conversation_messages rows."""
    conv_repo = _fake_send_message_success.conv_repo
    user_message_id = await conv_repo.add_message(conversation_id, "user", content, metadata=message_metadata)
    assistant_message_id = await conv_repo.add_message(conversation_id, "assistant", "Hello!")
    return ConversationResponse(
        message=Message(id=assistant_message_id, content="Hello!", role=MessageRole.ASSISTANT),
        conversation_id=conversation_id,
        user_message_id=user_message_id,
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
async def test_conversation_route_creates_inquiry_and_persists_completed_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, board_service = _build_router(tmp_path, monkeypatch)
    _fake_send_message_success.conv_repo = router._conversation_service.conversation_repository
    router._conversation_service.send_message = AsyncMock(side_effect=_fake_send_message_success)
    router._classifier.classify = _classify_as(HomeTurnRouteKind.CONVERSATION, "Direct chat", 0.95)

    response = await router.submit_turn(HomeTurnRequest(content="Hello"))
    assert response.route_kind == HomeTurnRouteKind.CONVERSATION
    assert response.state == HomeTurnState.COMPLETED
    assert response.inquiry_id

    inquiry = await board_service._repo.get_inquiry(response.inquiry_id)
    assert inquiry is not None
    assert inquiry.state == HomeTurnState.COMPLETED
    assert inquiry.conversationId


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
async def test_conversation_error_response_persists_failed_inquiry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, board_service = _build_router(tmp_path, monkeypatch)

    async def _fake_send_message_raises(conversation_id, content, *, model_id=None, file_paths=None, message_metadata=None):
        conv_repo = router._conversation_service.conversation_repository
        user_message_id = await conv_repo.add_message(conversation_id, "user", content, metadata=message_metadata)
        error_message_id = await conv_repo.add_message(conversation_id, "error", "Error: model unavailable")
        raise ModelNotAvailableError(
            "Error: model unavailable",
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            error_message_id=error_message_id,
        )

    router._conversation_service.send_message = AsyncMock(side_effect=_fake_send_message_raises)
    router._classifier.classify = _classify_as(HomeTurnRouteKind.CONVERSATION, "Direct chat", 0.95)

    response = await router.submit_turn(HomeTurnRequest(content="Hello"))

    assert response.state == HomeTurnState.FAILED
    assert response.assistant_content == "Error: model unavailable"
    inquiry = await board_service._repo.get_inquiry(response.inquiry_id)
    assert inquiry is not None
    assert inquiry.state == HomeTurnState.FAILED


@pytest.mark.asyncio
async def test_conversation_exception_without_message_ids_marks_inquiry_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, board_service = _build_router(tmp_path, monkeypatch)
    router._conversation_service.send_message = AsyncMock(
        side_effect=ConversationError("conversation failed")
    )
    router._classifier.classify = _classify_as(
        HomeTurnRouteKind.CONVERSATION,
        "Direct chat",
        0.95,
    )

    with pytest.raises(ValueError, match="conversation failed"):
        await router.submit_turn(HomeTurnRequest(content="Hello"))

    inquiries = await board_service._repo.list_recent_inquiries()
    assert len(inquiries) == 1
    assert inquiries[0].routeKind == HomeTurnRouteKind.CONVERSATION
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
async def test_conversation_route_passes_metadata_and_file_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, _ = _build_router(tmp_path, monkeypatch)
    _fake_send_message_success.conv_repo = router._conversation_service.conversation_repository
    router._conversation_service.send_message = AsyncMock(side_effect=_fake_send_message_success)
    router._classifier.classify = _classify_as(HomeTurnRouteKind.CONVERSATION, "Direct chat", 0.95)

    await router.submit_turn(
        HomeTurnRequest(
            content="Summarize this",
            display_prompt_markdown="**Summarize this**",
            reference_paths=["/tmp/a.txt", "/tmp/b.txt"],
        )
    )

    call_args = router._conversation_service.send_message.await_args
    assert call_args.args[1] == "Summarize this"
    assert call_args.kwargs["model_id"] is None
    assert call_args.kwargs["file_paths"] == ["/tmp/a.txt", "/tmp/b.txt"]
    assert call_args.kwargs["message_metadata"] == {
        "surface": "basil_board_home",
        "reference_paths": ["/tmp/a.txt", "/tmp/b.txt"],
        "display_prompt_markdown": "**Summarize this**",
    }


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
async def test_no_metadata_request_keeps_existing_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router, _ = _build_router(tmp_path, monkeypatch)
    _fake_send_message_success.conv_repo = router._conversation_service.conversation_repository
    router._conversation_service.send_message = AsyncMock(side_effect=_fake_send_message_success)
    router._classifier.classify = _classify_as(HomeTurnRouteKind.CONVERSATION, "Direct chat", 0.95)

    await router.submit_turn(HomeTurnRequest(content="Hello"))

    call_args = router._conversation_service.send_message.await_args
    assert call_args.kwargs["message_metadata"] == {
        "surface": "basil_board_home",
        "reference_paths": [],
    }


@pytest.mark.asyncio
async def test_each_inquiry_gets_its_own_conversation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two submissions must not share a conversation_id -- this is the
    core property that makes Recent Inquiries a list of independent
    records instead of one singleton scrollback."""
    router, board_service = _build_router(tmp_path, monkeypatch)
    _fake_send_message_success.conv_repo = router._conversation_service.conversation_repository
    router._conversation_service.send_message = AsyncMock(side_effect=_fake_send_message_success)
    router._classifier.classify = _classify_as(HomeTurnRouteKind.CONVERSATION, "Direct chat", 0.95)

    first = await router.submit_turn(HomeTurnRequest(content="First question"))
    second = await router.submit_turn(HomeTurnRequest(content="Second question"))

    first_inquiry = await board_service._repo.get_inquiry(first.inquiry_id)
    second_inquiry = await board_service._repo.get_inquiry(second.inquiry_id)
    assert first_inquiry.conversationId != second_inquiry.conversationId


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
