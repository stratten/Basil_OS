import asyncio
import json
from typing import Dict, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.meetings import cloud_transcription_routes as routes
from api.services.meeting_cloud_asr import settings_store as settings_module
from api.services.meeting_cloud_asr.assemblyai_provider import AssemblyAIProvider
from api.services.meeting_cloud_asr.chunked_provider import ChunkedProxyProvider
from api.services.meeting_cloud_asr.deepgram_provider import DeepgramProvider
from api.services.meeting_cloud_asr.models import CloudAsrError
from api.services.meeting_cloud_asr.planner import plan_cloud_session
from api.services.meeting_cloud_asr.settings_store import CloudTranscriptionSettings, CloudTranscriptionSettingsStore

from .fakes import FakeProvider


class MemoryKeys:
    def __init__(self, **keys: str) -> None:
        self.keys: Dict[str, str] = dict(keys)

    def read(self, provider: str) -> Optional[str]:
        return self.keys.get(provider) or None

    def write(self, provider: str, key: str) -> bool:
        self.keys[provider] = key
        return True

    def clear(self, provider: str) -> bool:
        self.keys.pop(provider, None)
        return True


@pytest.fixture
def store(tmp_path) -> CloudTranscriptionSettingsStore:
    return CloudTranscriptionSettingsStore(tmp_path / "cloud.json")


def enabled(**overrides) -> CloudTranscriptionSettings:
    return CloudTranscriptionSettings(**{"enabled": True, "acknowledged": True, **overrides})


def test_settings_default_to_off_and_unreadable_files_read_as_off(store) -> None:
    assert store.load() == CloudTranscriptionSettings()
    store.path.write_text("{not json", encoding="utf-8")
    assert store.load().enabled is False
    store.path.write_text(json.dumps({"enabled": True, "provider": "nonsense"}), encoding="utf-8")
    assert store.load().enabled is False
    store.save(enabled(provider="assemblyai"))
    assert store.load().provider == "assemblyai"
    assert set(json.loads(store.path.read_text())) == {"enabled", "provider", "connection", "acknowledged"}


def test_plan_requires_opt_in_acknowledgment_and_a_usable_connection(store) -> None:
    keys = MemoryKeys(deepgram="dg-key-123456")
    store.save(CloudTranscriptionSettings(enabled=False, acknowledged=True))
    assert plan_cloud_session(store=store, keys=keys, account_available=lambda: True) is None
    store.save(CloudTranscriptionSettings(enabled=True, acknowledged=False))
    assert plan_cloud_session(store=store, keys=keys, account_available=lambda: True) is None
    store.save(enabled(provider="assemblyai"))
    assert plan_cloud_session(store=store, keys=keys, account_available=lambda: True) is None
    store.save(enabled(connection="basil_account"))
    assert plan_cloud_session(store=store, keys=keys, account_available=lambda: False) is None


def test_plan_picks_streaming_with_a_key_and_chunked_through_the_account(store) -> None:
    keys = MemoryKeys(deepgram="dg-key-123456", assemblyai="aai-key-123456")
    store.save(enabled(provider="deepgram"))
    plan = plan_cloud_session(store=store, keys=keys, account_available=lambda: False)
    assert (plan.provider_id, plan.tier) == ("deepgram", "streaming") and isinstance(plan.build_provider(), DeepgramProvider)
    store.save(enabled(provider="assemblyai"))
    plan = plan_cloud_session(store=store, keys=keys, account_available=lambda: False)
    assert (plan.provider_id, plan.tier) == ("assemblyai", "streaming") and isinstance(plan.build_provider(), AssemblyAIProvider)
    store.save(enabled(connection="basil_account"))
    plan = plan_cloud_session(store=store, keys=MemoryKeys(), account_available=lambda: True)
    assert (plan.provider_id, plan.tier) == ("basil_account", "chunked") and isinstance(plan.build_provider(), ChunkedProxyProvider)


@pytest.fixture
def client(store):
    keys = MemoryKeys()
    state = {"account": False, "check": FakeProvider()}
    app = FastAPI()
    app.include_router(routes.router, prefix="/meetings")
    app.dependency_overrides[routes.get_store] = lambda: store
    app.dependency_overrides[routes.get_keys] = lambda: keys
    app.dependency_overrides[routes.get_account_check] = lambda: (lambda: state["account"])
    app.dependency_overrides[routes.get_provider_builder] = lambda: (lambda provider_id, key: state["check"])
    test_client = TestClient(app)
    test_client.keys = keys
    test_client.state = state
    return test_client


def test_state_lists_providers_and_never_returns_a_key(client) -> None:
    client.keys.write("deepgram", "dg-super-secret-key")
    body = client.get("/meetings/cloud-transcription").json()
    assert body["enabled"] is False and body["status"]["state"] == "off"
    assert [(item["id"], item["has_key"]) for item in body["providers"]] == [("deepgram", True), ("assemblyai", False)]
    assert "dg-super-secret-key" not in json.dumps(body)


def test_enabling_needs_the_disclosure_and_a_key_or_an_account(client) -> None:
    assert client.put("/meetings/cloud-transcription/settings", json={"enabled": True}).status_code == 400
    refused = client.put("/meetings/cloud-transcription/settings", json={"enabled": True, "acknowledge_disclosure": True})
    assert refused.status_code == 409 and refused.json()["detail"] == "Add a Deepgram API key first."
    assert client.get("/meetings/cloud-transcription").json()["enabled"] is False
    client.keys.write("deepgram", "dg-key-123456")
    accepted = client.put("/meetings/cloud-transcription/settings", json={"enabled": True, "acknowledge_disclosure": True})
    assert accepted.status_code == 200 and accepted.json()["enabled"] is True and accepted.json()["acknowledged"] is True
    unavailable = client.put("/meetings/cloud-transcription/settings", json={"connection": "basil_account"})
    assert unavailable.status_code == 409 and "Sign in" in unavailable.json()["detail"]
    client.state["account"] = True
    assert client.put("/meetings/cloud-transcription/settings", json={"connection": "basil_account"}).json()["connection"] == "basil_account"
    assert client.put("/meetings/cloud-transcription/settings", json={"enabled": False}).json()["enabled"] is False


def test_unknown_fields_and_values_are_rejected(client) -> None:
    assert client.put("/meetings/cloud-transcription/settings", json={"provider": "other"}).status_code == 422
    assert client.put("/meetings/cloud-transcription/settings", json={"surprise": 1}).status_code == 422


def test_key_routes_validate_store_and_clear_keys_and_disable_when_the_active_key_goes(client) -> None:
    assert client.put("/meetings/cloud-transcription/keys/other", json={"api_key": "abcdefgh12"}).status_code == 404
    assert client.put("/meetings/cloud-transcription/keys/deepgram", json={"api_key": "short"}).status_code == 422
    assert client.put("/meetings/cloud-transcription/keys/deepgram", json={"api_key": "has a space 123"}).status_code == 422
    saved = client.put("/meetings/cloud-transcription/keys/deepgram", json={"api_key": "  dg-key-123456  "})
    assert saved.status_code == 200 and client.keys.read("deepgram") == "dg-key-123456"
    assert "dg-key-123456" not in saved.text
    client.put("/meetings/cloud-transcription/settings", json={"enabled": True, "acknowledge_disclosure": True})
    cleared = client.delete("/meetings/cloud-transcription/keys/deepgram")
    assert cleared.status_code == 200 and cleared.json()["enabled"] is False and client.keys.read("deepgram") is None
    assert client.delete("/meetings/cloud-transcription/keys/other").status_code == 404


def test_the_connection_check_opens_and_closes_without_sending_audio(client) -> None:
    missing = client.post("/meetings/cloud-transcription/check", json={"provider": "deepgram"}).json()
    assert missing == {"ok": False, "message": "Add a Deepgram API key first."}
    client.keys.write("deepgram", "dg-key-123456")
    checked = client.post("/meetings/cloud-transcription/check", json={"provider": "deepgram"}).json()
    provider = client.state["check"]
    assert checked["ok"] is True and "No meeting audio was sent" in checked["message"]
    assert provider.opened is True and provider.closed == 1 and provider.sent == []


def test_a_failed_connection_check_reports_the_provider_message(client) -> None:
    client.keys.write("assemblyai", "aai-key-123456")
    client.state["check"] = FakeProvider(open_error=CloudAsrError("AssemblyAI rejected the API key."))
    result = client.post("/meetings/cloud-transcription/check", json={"provider": "assemblyai"}).json()
    assert result == {"ok": False, "message": "AssemblyAI rejected the API key."}


def test_the_literal_path_is_served_by_the_meetings_router_not_the_meeting_id_catch_all(store) -> None:
    from api.routes.meetings import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[routes.get_store] = lambda: store
    app.dependency_overrides[routes.get_keys] = lambda: MemoryKeys()
    app.dependency_overrides[routes.get_account_check] = lambda: (lambda: False)
    response = TestClient(app).get("/meetings/cloud-transcription")
    assert response.status_code == 200 and response.json()["enabled"] is False
