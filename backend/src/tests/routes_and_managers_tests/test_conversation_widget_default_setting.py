from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.models.preferences import Preferences
from api.routes.settings_routes import voice_routes


def build_client(monkeypatch):
    state = {"preferences": Preferences(), "saved": []}

    def fake_load_preferences():
        return state["preferences"]

    def fake_save_preferences(preferences):
        state["saved"].append(preferences.conversation_widget.default_conversation_only)
        state["preferences"] = preferences

    monkeypatch.setattr(voice_routes, "load_preferences", fake_load_preferences)
    monkeypatch.setattr(voice_routes, "save_preferences", fake_save_preferences)
    app = FastAPI()
    app.include_router(voice_routes.router, prefix="/settings")
    return TestClient(app), state


def test_conversation_only_default_is_false_when_unset(monkeypatch):
    client, _ = build_client(monkeypatch)

    response = client.get("/settings/conversation-widget")

    assert response.status_code == 200
    assert response.json()["settings"]["default_conversation_only"] is False


def test_conversation_only_default_round_trips(monkeypatch):
    client, state = build_client(monkeypatch)

    response = client.put("/settings/conversation-widget", json={"default_conversation_only": True})

    assert response.status_code == 200
    assert response.json()["updated_settings"]["default_conversation_only"] is True
    assert state["saved"] == [True]
    assert client.get("/settings/conversation-widget").json()["settings"]["default_conversation_only"] is True


def test_conversation_only_default_rejects_non_boolean(monkeypatch):
    client, state = build_client(monkeypatch)

    response = client.put("/settings/conversation-widget", json={"default_conversation_only": "yes"})

    assert response.status_code == 400
    assert state["saved"] == []


def test_other_conversation_widget_updates_leave_default_unchanged(monkeypatch):
    client, state = build_client(monkeypatch)
    state["preferences"].conversation_widget.default_conversation_only = True

    response = client.put("/settings/conversation-widget", json={"is_sidebar_collapsed": True})

    assert response.status_code == 200
    body = response.json()["updated_settings"]
    assert body["is_sidebar_collapsed"] is True
    assert body["default_conversation_only"] is True
