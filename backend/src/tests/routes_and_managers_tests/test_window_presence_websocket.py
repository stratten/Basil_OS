"""The /ws endpoint records window presence per connection and drops it on disconnect."""

import time

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.use_temp_home


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_window_presence_is_held_while_connected_and_cleared_on_disconnect(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace

    from fastapi import FastAPI

    from api import dependencies
    from api.core.models.model_manager import ModelManager
    from api.core.services import model_service as model_service_module
    from api.routes import websocket as websocket_routes

    manager = ModelManager(tmp_path / "models")
    monkeypatch.setattr(
        model_service_module, "get_model_service", lambda: SimpleNamespace(model_manager=manager)
    )
    app = FastAPI()
    app.include_router(websocket_routes.router)
    for dependency in (
        dependencies.get_agent_task_submission_service,
        dependencies.get_wake_word_service,
        dependencies.get_transcription_service,
        dependencies.get_conversation_turn_router,
        dependencies.get_todo_workspace_turn_manager,
    ):
        app.dependency_overrides[dependency] = lambda: SimpleNamespace()
    before = manager.window_hold_count()

    client = TestClient(app)
    with client.websocket_connect("/ws") as websocket:
        websocket.send_text(json.dumps({
            "agent_task_action": "window_presence",
            "window_id": "agent-task-result-widget",
            "agent_task_id": "task-1",
            "present": True,
        }))
        assert _wait_for(lambda: manager.window_hold_count() == before + 1)

        websocket.send_text(json.dumps({
            "agent_task_action": "window_presence",
            "window_id": "detached-agent-task-t2",
            "present": True,
        }))
        assert _wait_for(lambda: manager.window_hold_count() == before + 2)

        websocket.send_text(json.dumps({
            "agent_task_action": "window_presence",
            "window_id": "agent-task-result-widget",
            "present": False,
        }))
        assert _wait_for(lambda: manager.window_hold_count() == before + 1)

    # Closing the socket forgets whatever it still reported.
    assert _wait_for(lambda: manager.window_hold_count() == before)
