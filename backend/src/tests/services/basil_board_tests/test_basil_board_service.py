from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.core.knowledge.sqlite.conversation_repository import ConversationRepository
from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from pydantic import ValidationError

from api.services.basil_board.models import (
    BasilBoardArtifact,
    BasilBoardTabKind,
    HomeTurnRouteKind,
    HomeTurnState,
)
from api.services.basil_board.repository import BasilBoardRepository
from api.services.basil_board.service import BasilBoardService


def _build_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[BasilBoardService, SQLiteKnowledgeService]:
    sqlite_service = SQLiteKnowledgeService(tmp_path / "basil_board.db")
    monkeypatch.setattr(
        "api.services.basil_board.service.get_sqlite_knowledge_service",
        lambda: sqlite_service,
    )
    return BasilBoardService(BasilBoardRepository(str(sqlite_service.db_path))), sqlite_service


@pytest.mark.asyncio
async def test_schema_seeds_home_and_capability_tabs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = _build_service(tmp_path, monkeypatch)
    hydration = await service.hydrate_board()

    tabs_by_id = {tab.id: tab for tab in hydration.tabs}
    assert set(tabs_by_id) == {"home", "todos", "chats", "meetings", "agent_tasks"}
    assert tabs_by_id["home"].tab_kind == BasilBoardTabKind.HOME
    assert tabs_by_id["todos"].tab_kind == BasilBoardTabKind.CAPABILITY
    assert tabs_by_id["todos"].configuration["capability_id"] == "todos.workspace"
    assert tabs_by_id["chats"].tab_kind == BasilBoardTabKind.CAPABILITY
    assert tabs_by_id["chats"].configuration["capability_id"] == "conversations.history"
    assert tabs_by_id["meetings"].tab_kind == BasilBoardTabKind.CAPABILITY
    assert tabs_by_id["meetings"].configuration["capability_id"] == "meetings.history"
    assert tabs_by_id["agent_tasks"].tab_kind == BasilBoardTabKind.CAPABILITY
    assert tabs_by_id["agent_tasks"].configuration["capability_id"] == "agent_tasks.history"
    assert tabs_by_id["home"].configuration["detach_behavior"] == "none"
    assert tabs_by_id["chats"].configuration["detach_behavior"] == "useNativeWindow"
    assert tabs_by_id["meetings"].configuration["detach_behavior"] == "useBoardWindow"
    assert tabs_by_id["agent_tasks"].configuration["detach_behavior"] == "useNativeWindow"
    assert hydration.recent_inquiries == []
    assert "conversations.history" in hydration.supported_renderer_kinds
    assert "meetings.history" in hydration.supported_renderer_kinds
    assert "agent_tasks.history" in hydration.supported_renderer_kinds


@pytest.mark.asyncio
async def test_home_state_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ensure_home_state is legacy-only now (no longer called by the
    submission flow) but must keep working for old data/routes."""
    service, _ = _build_service(tmp_path, monkeypatch)
    first = await service.ensure_home_state()
    second = await service.ensure_home_state()
    assert first.conversation_id == second.conversation_id


@pytest.mark.asyncio
async def test_legacy_home_turn_persistence_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, sqlite_service = _build_service(tmp_path, monkeypatch)
    home_state = await service.ensure_home_state()
    repo = service._repo
    conv_repo = ConversationRepository(sqlite_service=sqlite_service)
    user_message_id = await conv_repo.add_message(home_state.conversation_id, "user", "hello")

    turn = await repo.create_home_turn(
        user_message_id=user_message_id,
        conversation_id=home_state.conversation_id,
        route_kind=HomeTurnRouteKind.AGENT_TASK,
        route_reason="Needs retrieval",
        route_confidence=0.42,
        state=HomeTurnState.RUNNING,
        agent_task_id="task-123",
    )

    loaded = await repo.get_home_turn(user_message_id)
    assert loaded is not None
    assert loaded.agent_task_id == "task-123"
    assert loaded.state == HomeTurnState.RUNNING
    assert turn.route_reason == "Needs retrieval"


def test_future_artifacts_fail_closed_until_a_supported_schema_exists() -> None:
    with pytest.raises(ValidationError, match="Unsupported artifact kind"):
        BasilBoardArtifact(
            id="artifact-1",
            tab_id="home",
            artifact_kind="dashboard",
            schema_version="v1",
        )


@pytest.mark.asyncio
async def test_create_inquiry_and_list_recent_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = _build_service(tmp_path, monkeypatch)
    inquiry = await service.create_inquiry(
        prompt_text="Summarize this",
        display_prompt_markdown="**Summarize this**",
        reference_paths=["/tmp/a.txt"],
    )
    assert inquiry.state == HomeTurnState.ROUTING
    assert inquiry.conversationId is None

    conversation_id = await service.create_inquiry_conversation("Summarize this")
    updated = await service.update_inquiry(inquiry.id, conversation_id=conversation_id)
    assert updated is not None
    assert updated.conversationId == conversation_id

    recent = await service.list_recent_inquiries()
    assert len(recent) == 1
    assert recent[0].id == inquiry.id
    assert recent[0].displayMarkdown == "**Summarize this**"
    assert recent[0].referencePaths == ["/tmp/a.txt"]

    hydration = await service.hydrate_board()
    assert [item.id for item in hydration.recent_inquiries] == [inquiry.id]


@pytest.mark.asyncio
async def test_hydrate_inquiry_builds_timeline_for_conversation_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, sqlite_service = _build_service(tmp_path, monkeypatch)
    conv_repo = ConversationRepository(sqlite_service=sqlite_service)

    inquiry = await service.create_inquiry(
        prompt_text="Hello",
        display_prompt_markdown=None,
        reference_paths=[],
    )
    conversation_id = await service.create_inquiry_conversation("Hello")
    user_message_id = await conv_repo.add_message(conversation_id, "user", "Hello")
    assistant_message_id = await conv_repo.add_message(conversation_id, "assistant", "Hi there!")
    await service.update_inquiry(
        inquiry.id,
        conversation_id=conversation_id,
        route_kind=HomeTurnRouteKind.CONVERSATION,
        route_reason="Direct chat",
        route_confidence=0.95,
        state=HomeTurnState.COMPLETED,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
    )

    detail = await service.hydrate_inquiry(inquiry.id)
    assert detail is not None
    assert detail.state == HomeTurnState.COMPLETED
    assert len(detail.timeline) == 2
    assert detail.timeline[0]["kind"] == "user_message"
    assert detail.timeline[0]["content"] == "Hello"
    assert detail.timeline[1]["kind"] == "conversation_answer"
    assert detail.timeline[1]["content"] == "Hi there!"


@pytest.mark.asyncio
async def test_hydrate_inquiry_reconciles_terminal_agent_task_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, sqlite_service = _build_service(tmp_path, monkeypatch)
    conv_repo = ConversationRepository(sqlite_service=sqlite_service)

    inquiry = await service.create_inquiry(
        prompt_text="Search my notes",
        display_prompt_markdown=None,
        reference_paths=[],
    )
    conversation_id = await service.create_inquiry_conversation("Search my notes")
    user_message_id = await conv_repo.add_message(conversation_id, "user", "Search my notes")
    await service.update_inquiry(
        inquiry.id,
        conversation_id=conversation_id,
        route_kind=HomeTurnRouteKind.AGENT_TASK,
        route_reason="Needs retrieval",
        route_confidence=0.2,
        state=HomeTurnState.RUNNING,
        user_message_id=user_message_id,
        agent_task_id="task-abc",
    )

    service._agent_tasks = SimpleNamespace(
        get_agent_task=AsyncMock(
            return_value=SimpleNamespace(
                status="completed",
                result_data={"agent_output": "Found 3 notes."},
            )
        )
    )

    detail = await service.hydrate_inquiry(inquiry.id)
    assert detail is not None
    assert detail.state == HomeTurnState.COMPLETED
    agent_task_item = next(item for item in detail.timeline if item["kind"] == "agent_task")
    assert agent_task_item["state"] == "completed"
    assert agent_task_item["result"] == "Found 3 notes."

    persisted = await service._repo.get_inquiry(inquiry.id)
    assert persisted is not None
    assert persisted.state == HomeTurnState.COMPLETED


@pytest.mark.asyncio
async def test_hydrate_board_reconciles_terminal_agent_task_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, sqlite_service = _build_service(tmp_path, monkeypatch)
    conv_repo = ConversationRepository(sqlite_service=sqlite_service)
    inquiry = await service.create_inquiry(
        prompt_text="Search my notes",
        display_prompt_markdown=None,
        reference_paths=[],
    )
    conversation_id = await service.create_inquiry_conversation("Search my notes")
    user_message_id = await conv_repo.add_message(conversation_id, "user", "Search my notes")
    await service.update_inquiry(
        inquiry.id,
        conversation_id=conversation_id,
        route_kind=HomeTurnRouteKind.AGENT_TASK,
        route_reason="Needs retrieval",
        state=HomeTurnState.RUNNING,
        user_message_id=user_message_id,
        agent_task_id="task-board-hydration",
    )
    service._agent_tasks = SimpleNamespace(
        get_agent_task=AsyncMock(
            return_value=SimpleNamespace(status="completed", result_data={})
        )
    )

    hydration = await service.hydrate_board()

    assert hydration.recent_inquiries[0].state == HomeTurnState.COMPLETED
    persisted = await service._repo.get_inquiry(inquiry.id)
    assert persisted is not None
    assert persisted.state == HomeTurnState.COMPLETED


@pytest.mark.asyncio
async def test_hydrate_inquiry_returns_none_for_unknown_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = _build_service(tmp_path, monkeypatch)
    assert await service.hydrate_inquiry("does-not-exist") is None


def test_row_to_inquiry_ignores_malformed_reference_paths_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, sqlite_service = _build_service(tmp_path, monkeypatch)
    repo = BasilBoardRepository(str(sqlite_service.db_path))
    row = {
        "id": "inquiry-1",
        "prompt_text": "Hello",
        "display_prompt_markdown": None,
        "reference_paths_json": "not-json",
        "route_kind": None,
        "route_reason": None,
        "route_confidence": None,
        "state": "routing",
        "conversation_id": None,
        "agent_task_id": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    inquiry = repo._row_to_inquiry(row)
    assert inquiry.referencePaths == []
