import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.routes.basil_board import home_routes as basil_board_home_routes
from api.routes.basil_board import router as basil_board_router
from api.services.basil_board.models import HomeTurnRouteKind, HomeTurnState
from api.services.basil_board.repository import BasilBoardRepository
from api.services.basil_board.service import BasilBoardService


def _build_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, BasilBoardService]:
    sqlite_service = SQLiteKnowledgeService(tmp_path / "basil_board_routes.db")
    monkeypatch.setattr(
        "api.services.basil_board.service.get_sqlite_knowledge_service",
        lambda: sqlite_service,
    )
    service = BasilBoardService(BasilBoardRepository(str(sqlite_service.db_path)))
    basil_board_home_routes._service_instance = service

    fake_router = SimpleNamespace(
        submit_turn=AsyncMock(
            return_value=SimpleNamespace(
                inquiry_id="inquiry-1",
                user_message_id="msg-1",
                route_kind=HomeTurnRouteKind.CONVERSATION,
                route_reason="Direct chat",
                route_confidence=0.9,
                state=HomeTurnState.COMPLETED,
                assistant_message_id="assistant-1",
                agent_task_id=None,
                assistant_content="Hi there",
            )
        )
    )

    app = FastAPI()
    app.include_router(basil_board_router)
    app.dependency_overrides[basil_board_home_routes._router] = lambda: fake_router
    return TestClient(app), service


def test_hydrate_returns_home_and_capability_tabs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_client(tmp_path, monkeypatch)
    response = client.get("/api/v1/basil-board/hydrate")
    assert response.status_code == 200
    payload = response.json()
    tab_ids = {tab["id"] for tab in payload["tabs"]}
    assert tab_ids == {"home", "todos", "chats", "meetings", "agent_tasks"}
    assert payload["recent_inquiries"] == []


def test_home_turn_rejects_blank_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_client(tmp_path, monkeypatch)
    response = client.post("/api/v1/basil-board/home/turn", json={"content": "   "})
    assert response.status_code == 400


def test_home_turn_accepts_typed_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_client(tmp_path, monkeypatch)
    response = client.post("/api/v1/basil-board/home/turn", json={"content": "Hello Basil"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["inquiry_id"] == "inquiry-1"
    assert payload["route_kind"] == "conversation"
    assert payload["assistant_content"] == "Hi there"


def test_home_turn_passes_snake_case_payload_to_router(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_client(tmp_path, monkeypatch)
    response = client.post(
        "/api/v1/basil-board/home/turn",
        json={
            "content": "Summarize this",
            "display_prompt_markdown": "**Summarize this**",
            "reference_paths": ["/tmp/a.txt", "/tmp/b.txt"],
            "model_id": "model-1",
        },
    )
    assert response.status_code == 200


def test_home_turn_rejects_unknown_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_client(tmp_path, monkeypatch)
    response = client.post(
        "/api/v1/basil-board/home/turn",
        json={"content": "Hello", "artifact_html": "<div/>"},
    )
    assert response.status_code == 422


def test_home_turn_rejects_blank_and_invalid_reference_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_client(tmp_path, monkeypatch)
    assert client.post("/api/v1/basil-board/home/turn", json={"content": "Hello", "reference_paths": [""]}).status_code == 422
    assert client.post("/api/v1/basil-board/home/turn", json={"content": "Hello", "reference_paths": [123]}).status_code == 422
    assert client.post(
        "/api/v1/basil-board/home/turn",
        json={"content": "Hello", "reference_paths": [f"/tmp/{index}.txt" for index in range(33)]},
    ).status_code == 422


def test_get_board_inquiry_returns_404_for_unknown_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build_client(tmp_path, monkeypatch)
    response = client.get("/api/v1/basil-board/inquiries/does-not-exist")
    assert response.status_code == 404


def test_get_board_inquiry_returns_hydrated_detail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, service = _build_client(tmp_path, monkeypatch)
    inquiry = asyncio.get_event_loop().run_until_complete(
        service.create_inquiry(
            prompt_text="Hello",
            display_prompt_markdown=None,
            reference_paths=[],
        )
    )
    response = client.get(f"/api/v1/basil-board/inquiries/{inquiry.id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == inquiry.id
    assert payload["timeline"][0]["kind"] == "user_message"
