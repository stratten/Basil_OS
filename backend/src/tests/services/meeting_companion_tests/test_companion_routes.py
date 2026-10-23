import httpx
import pytest
from fastapi import FastAPI

from api.routes.meetings import companion_routes
from api.routes.meetings import router as meetings_router
from api.services.meeting_companion import store as store_module
from api.services.meeting_companion.chat import ChatResult
from api.services.meeting_companion.models import CompanionItem, CompanionSettings, TimelineEvent, TranscriptRange
from api.services.meeting_companion.store import CompanionDocument, CompanionStore

QUESTION = "How does the retry policy handle timeouts in billing?"


class FakeChat:
    async def stream_answer(self, request, on_delta):
        await on_delta("Retries cap ")
        await on_delta("at five.")
        return ChatResult(text="Retries cap at five.", deltas=["Retries cap ", "at five."])


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "meetings_root", lambda: tmp_path)
    return tmp_path


def client_for(env):
    app = FastAPI()
    app.dependency_overrides[companion_routes.get_companion_runtime] = lambda: env.runtime
    app.include_router(companion_routes.router, prefix="/meetings")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def stored_item_event(seq=1, item_id="i1"):
    item = CompanionItem(id=item_id, kind="insight", text="Retries were tuned.", confidence=0.8, transcript_range=TranscriptRange(start=8.0, end=10.0, turn_ids=[]), trigger="periodic")
    return TimelineEvent(id=f"e{seq}", seq=seq, kind="item", meeting_time=10.0, wall_time="w", payload={"item": item.model_dump(mode="json")})


async def live_meeting(runtime_factory, recorder_factory, **kwargs):
    env = runtime_factory(**kwargs)
    mic = recorder_factory("mic1")
    env.recorders.append(mic)
    env.mic = mic
    return env


@pytest.mark.asyncio
async def test_companion_router_is_registered_before_the_lifecycle_catch_all(home, runtime_factory):
    env = runtime_factory()
    app = FastAPI()
    app.dependency_overrides[companion_routes.get_companion_runtime] = lambda: env.runtime
    app.include_router(meetings_router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/meetings/companion/settings")
        assert response.status_code == 200
        assert set(response.json()) == {"auto_enable", "default_mode", "screen_share_note_dismissed", "next_focus", "proposal_mode", "proposal_capabilities", "auto_execute_capabilities"}
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_global_settings_roundtrip_and_validation(home, runtime_factory):
    env = runtime_factory()
    base = {"auto_enable": False, "default_mode": "active", "screen_share_note_dismissed": False, "next_focus": "", "proposal_mode": "suggestion_only", "proposal_capabilities": ["todo", "agent_task", "assistant_session"], "auto_execute_capabilities": []}
    async with client_for(env) as client:
        assert (await client.get("/meetings/companion/settings")).json() == base
        updated = await client.put("/meetings/companion/settings", json={"auto_enable": True, "default_mode": "passive"})
        assert updated.status_code == 200 and updated.json() == {**base, "auto_enable": True, "default_mode": "passive"}
        assert (await client.put("/meetings/companion/settings", json={})).json() == {**base, "auto_enable": True, "default_mode": "passive"}
        dismissed = await client.put("/meetings/companion/settings", json={"screen_share_note_dismissed": True})
        assert dismissed.json() == {**base, "auto_enable": True, "default_mode": "passive", "screen_share_note_dismissed": True}
        assert (await client.get("/meetings/companion/settings")).json()["screen_share_note_dismissed"] is True
        focused = await client.put("/meetings/companion/settings", json={"next_focus": "  Watch the budget numbers  "})
        assert focused.json()["next_focus"] == "Watch the budget numbers"
        assert (await client.put("/meetings/companion/settings", json={"next_focus": ""})).json()["next_focus"] == ""
        assert (await client.put("/meetings/companion/settings", json={"next_focus": "x" * 601})).status_code == 422
        assert (await client.put("/meetings/companion/settings", json={"unknown": 1})).status_code == 422
        assert (await client.put("/meetings/companion/settings", json={"default_mode": "loud"})).status_code == 422
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_missing_runtime_is_503():
    app = FastAPI()
    app.include_router(companion_routes.router, prefix="/meetings")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/meetings/companion/settings")).status_code == 503
        assert (await client.get("/meetings/m1/companion")).status_code == 503


@pytest.mark.asyncio
async def test_snapshot_for_finished_meetings_unknown_meetings_and_bad_ids(home, runtime_factory):
    env = runtime_factory()
    (home / "m1").mkdir()
    async with client_for(env) as client:
        empty = await client.get("/meetings/m1/companion")
        assert empty.status_code == 200 and empty.json()["status"]["enabled"] is False and empty.json()["items"] == []
        assert (await client.get("/meetings/nope/companion")).status_code == 404
        assert (await client.get("/meetings/.hidden/companion")).status_code == 404
        CompanionStore(home / "m1").save(CompanionDocument(session_key="m1", settings=CompanionSettings(enabled=True), events=[stored_item_event()], saved_at="w"))
        stored = (await client.get("/meetings/m1/companion")).json()
        assert [item["id"] for item in stored["items"]] == ["i1"] and stored["status"]["live"] is False
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_live_only_actions_are_409_when_not_live(home, runtime_factory):
    env = runtime_factory()
    (home / "m1").mkdir()
    async with client_for(env) as client:
        assert (await client.post("/meetings/m1/companion/enable", json={})).status_code == 409
        assert (await client.patch("/meetings/m1/companion/settings", json={"mode": "passive"})).status_code == 409
        assert (await client.post("/meetings/m1/companion/chat", json={"text": "hello?"})).status_code == 409
        assert (await client.post("/meetings/m1/companion/watches", json={"topic": "billing", "instruction": "x"})).status_code == 409
        assert (await client.delete("/meetings/m1/companion/watches/w1")).status_code == 409
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_enable_patch_settings_distinguish_omitted_and_null_model(home, runtime_factory, recorder_factory):
    env = await live_meeting(runtime_factory, recorder_factory)
    async with client_for(env) as client:
        enabled = await client.post("/meetings/mic1/companion/enable", json={"mode": "passive", "model_id": "model-a"})
        assert enabled.status_code == 200 and enabled.json()["status"]["live"] is True
        assert enabled.json()["status"]["mode"] == "passive" and enabled.json()["status"]["model_id"] == "model-a"
        kept = await client.patch("/meetings/mic1/companion/settings", json={"mode": "active"})
        assert kept.json()["mode"] == "active" and kept.json()["model_id"] == "model-a"
        cleared = await client.patch("/meetings/mic1/companion/settings", json={"model_id": None})
        assert cleared.json()["model_id"] is None and cleared.json()["mode"] == "active"
        assert (await client.patch("/meetings/mic1/companion/settings", json={"mode": "loud"})).status_code == 422
        live = await client.get("/meetings/mic1/companion")
        assert live.json()["status"]["live"] is True
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_roots_attach_validate_and_detach(home, runtime_factory, recorder_factory, project):
    env = await live_meeting(runtime_factory, recorder_factory)
    async with client_for(env) as client:
        await client.post("/meetings/mic1/companion/enable", json={})
        attached = await client.post("/meetings/mic1/companion/roots", json={"path": str(project)})
        assert attached.status_code == 201 and attached.json()["kind"] == "folder" and attached.json()["display_name"] == "proj"
        rejected = await client.post("/meetings/mic1/companion/roots", json={"path": "relative/path"})
        assert rejected.status_code == 422 and "absolute" in rejected.json()["detail"]
        assert (await client.post("/meetings/mic1/companion/roots", json={"path": ""})).status_code == 422
        root_id = attached.json()["id"]
        assert (await client.get("/meetings/mic1/companion")).json()["roots"][0]["id"] == root_id
        assert (await client.delete(f"/meetings/mic1/companion/roots/{root_id}")).json() == {"ok": True}
        assert (await client.delete(f"/meetings/mic1/companion/roots/{root_id}")).status_code == 404
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_watches_create_validate_limit_and_cancel(home, runtime_factory, recorder_factory):
    env = await live_meeting(runtime_factory, recorder_factory)
    async with client_for(env) as client:
        await client.post("/meetings/mic1/companion/enable", json={})
        created = await client.post("/meetings/mic1/companion/watches", json={"topic": "billing", "instruction": "show me the endpoint"})
        assert created.status_code == 201 and created.json()["keywords"] == ["billing"] and created.json()["active"] is True
        too_short = await client.post("/meetings/mic1/companion/watches", json={"topic": "ok", "instruction": "x"})
        assert too_short.status_code == 422
        for topic in ("ledger", "invoice", "payroll", "refund", "tariff", "escrow", "audit"):
            assert (await client.post("/meetings/mic1/companion/watches", json={"topic": topic, "instruction": "x"})).status_code == 201
        over = await client.post("/meetings/mic1/companion/watches", json={"topic": "budget", "instruction": "x"})
        assert over.status_code == 422 and "at most 8" in over.json()["detail"]
        watch_id = created.json()["id"]
        assert (await client.delete(f"/meetings/mic1/companion/watches/{watch_id}")).json() == {"ok": True}
        assert (await client.delete(f"/meetings/mic1/companion/watches/{watch_id}")).status_code == 404
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_chat_is_accepted_then_answered_and_validated(home, runtime_factory, recorder_factory):
    env = await live_meeting(runtime_factory, recorder_factory, chat_service=FakeChat())
    async with client_for(env) as client:
        await client.post("/meetings/mic1/companion/enable", json={})
        accepted = await client.post("/meetings/mic1/companion/chat", json={"text": "What is the retry limit?"})
        assert accepted.status_code == 202 and accepted.json()["message_id"]
        await env.runtime.session_for("mic1").wait_idle()
        chat = (await client.get("/meetings/mic1/companion")).json()["chat"]
        assert [(message["role"], message["text"]) for message in chat] == [("user", "What is the retry limit?"), ("assistant", "Retries cap at five.")]
        assert chat[1]["id"] == accepted.json()["message_id"]
        deltas = [message["text_delta"] for message in env.broadcasts if message["event_type"] == "meeting_companion_chat_delta"]
        assert deltas == ["Retries cap ", "at five."]
        assert (await client.post("/meetings/mic1/companion/chat", json={"text": ""})).status_code == 422
        assert (await client.post("/meetings/mic1/companion/chat", json={"text": "   "})).status_code == 422
        assert (await client.post("/meetings/mic1/companion/chat", json={"text": "x" * 4001})).status_code == 422
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_feedback_on_a_live_meeting(home, runtime_factory, recorder_factory):
    env = await live_meeting(runtime_factory, recorder_factory)
    async with client_for(env) as client:
        await client.post("/meetings/mic1/companion/enable", json={})
        session = env.runtime.session_for("mic1")
        env.runtime._on_registry_event("segment", "mic1", env.mic, {"segment": {"start": 1.0, "end": 4.0, "text": QUESTION, "speaker": "Microphone", "is_interim": False}})
        await env.runtime.wait_idle()
        await session.tick()
        await session.wait_idle()
        item_id = (await client.get("/meetings/mic1/companion")).json()["items"][0]["id"]
        assert (await client.post(f"/meetings/mic1/companion/items/{item_id}/feedback", json={"action": "pinned"})).json() == {"ok": True}
        assert (await client.get("/meetings/mic1/companion")).json()["items"][0]["pinned"] is True
        assert (await client.post("/meetings/mic1/companion/items/missing/feedback", json={"action": "pinned"})).status_code == 404
        assert (await client.post(f"/meetings/mic1/companion/items/{item_id}/feedback", json={"action": "bogus"})).status_code == 422
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_a_dismissed_item_can_be_restored_and_restoring_a_shown_item_changes_nothing(home, runtime_factory, recorder_factory):
    env = await live_meeting(runtime_factory, recorder_factory)
    async with client_for(env) as client:
        await client.post("/meetings/mic1/companion/enable", json={})
        session = env.runtime.session_for("mic1")
        env.runtime._on_registry_event("segment", "mic1", env.mic, {"segment": {"start": 1.0, "end": 4.0, "text": QUESTION, "speaker": "Microphone", "is_interim": False}})
        await env.runtime.wait_idle()
        await session.tick()
        await session.wait_idle()
        item_id = (await client.get("/meetings/mic1/companion")).json()["items"][0]["id"]
        feedback = f"/meetings/mic1/companion/items/{item_id}/feedback"
        assert (await client.post(feedback, json={"action": "restored"})).json() == {"ok": True}
        assert (await client.get("/meetings/mic1/companion")).json()["items"][0]["dismissed"] is False
        assert (await client.post(feedback, json={"action": "dismissed"})).json() == {"ok": True}
        assert (await client.get("/meetings/mic1/companion")).json()["items"][0]["dismissed"] is True
        assert (await client.post(feedback, json={"action": "restored"})).json() == {"ok": True}
        restored = (await client.get("/meetings/mic1/companion")).json()["items"][0]
        assert restored["dismissed"] is False
        assert (await client.post("/meetings/mic1/companion/items/missing/feedback", json={"action": "restored"})).status_code == 404
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_feedback_on_a_finished_meeting_uses_the_saved_timeline(home, runtime_factory):
    env = runtime_factory()
    (home / "m1").mkdir()
    async with client_for(env) as client:
        assert (await client.post("/meetings/m1/companion/items/i1/feedback", json={"action": "pinned"})).status_code == 404
        CompanionStore(home / "m1").save(CompanionDocument(session_key="m1", settings=CompanionSettings(enabled=True), events=[stored_item_event()], saved_at="w"))
        assert (await client.post("/meetings/m1/companion/items/i1/feedback", json={"action": "pinned"})).status_code == 200
        snapshot = (await client.get("/meetings/m1/companion")).json()
        assert snapshot["items"][0]["pinned"] is True and snapshot["status"]["live"] is False and snapshot["last_seq"] == 2
        assert (await client.post("/meetings/m1/companion/items/missing/feedback", json={"action": "pinned"})).status_code == 404
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_disable_returns_the_saved_snapshot_and_is_safe_when_not_live(home, runtime_factory, recorder_factory):
    env = await live_meeting(runtime_factory, recorder_factory)
    (home / "other").mkdir()
    async with client_for(env) as client:
        await client.post("/meetings/mic1/companion/enable", json={})
        disabled = await client.post("/meetings/mic1/companion/disable")
        assert disabled.status_code == 200 and disabled.json()["status"]["live"] is False and disabled.json()["status"]["enabled"] is False
        again = await client.post("/meetings/other/companion/disable")
        assert again.status_code == 200 and again.json()["status"]["enabled"] is False
        assert (await client.post("/meetings/ghost/companion/disable")).status_code == 404
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_sources_can_be_attached_and_detached_for_a_finished_meeting(home, runtime_factory, project):
    env = runtime_factory()
    (home / "m1").mkdir()
    async with client_for(env) as client:
        attached = await client.post("/meetings/m1/companion/roots", json={"path": str(project)})
        assert attached.status_code == 201 and attached.json()["display_name"] == "proj"
        root_id = attached.json()["id"]
        snapshot = (await client.get("/meetings/m1/companion")).json()
        assert [root["id"] for root in snapshot["roots"]] == [root_id] and snapshot["status"]["live"] is False
        assert (await client.post("/meetings/m1/companion/roots", json={"path": "relative/path"})).status_code == 422
        assert (await client.post("/meetings/nope/companion/roots", json={"path": str(project)})).status_code == 404
        assert (await client.delete(f"/meetings/m1/companion/roots/{root_id}")).json() == {"ok": True}
        assert (await client.delete(f"/meetings/m1/companion/roots/{root_id}")).status_code == 404
        assert (await client.get("/meetings/m1/companion")).json()["roots"] == []
        assert (await client.delete("/meetings/m2/companion/roots/r-x")).status_code == 404
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_a_recording_meeting_without_a_companion_still_refuses_sources(home, runtime_factory, recorder_factory, project):
    env = await live_meeting(runtime_factory, recorder_factory)
    async with client_for(env) as client:
        assert (await client.post("/meetings/mic1/companion/roots", json={"path": str(project)})).status_code == 409
        assert (await client.delete("/meetings/mic1/companion/roots/r-x")).status_code == 409
    assert not (home / "mic1" / "companion.json").exists()
    await env.runtime.shutdown()
