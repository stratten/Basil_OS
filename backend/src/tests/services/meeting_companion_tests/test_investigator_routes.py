import asyncio

import httpx
import pytest
from fastapi import FastAPI

from api.routes.meetings import companion_routes
from api.services.meeting_companion import store as store_module

from .investigator_session_fakes import FakeInvestigator


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "meetings_root", lambda: tmp_path)
    return tmp_path


def client_for(env):
    app = FastAPI()
    app.dependency_overrides[companion_routes.get_companion_runtime] = lambda: env.runtime
    app.include_router(companion_routes.router, prefix="/meetings")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def live(runtime_factory, recorder_factory, fake):
    env = runtime_factory()
    env.runtime._investigator = fake
    env.recorders.append(recorder_factory("mic1"))
    return env


@pytest.mark.asyncio
async def test_enable_and_patch_carry_the_investigator_switch(home, runtime_factory, recorder_factory):
    env = await live(runtime_factory, recorder_factory, FakeInvestigator())
    async with client_for(env) as client:
        enabled = await client.post("/meetings/mic1/companion/enable", json={"investigate": False})
        assert enabled.status_code == 200 and enabled.json()["status"]["investigate"] is False and enabled.json()["status"]["investigating"] == 0
        patched = await client.patch("/meetings/mic1/companion/settings", json={"investigate": True})
        assert patched.status_code == 200 and patched.json()["investigate"] is True
        unchanged = await client.patch("/meetings/mic1/companion/settings", json={"mode": "passive"})
        assert unchanged.json()["investigate"] is True
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_an_explicit_investigation_is_accepted_and_lands_in_the_snapshot(home, runtime_factory, recorder_factory):
    fake = FakeInvestigator()
    env = await live(runtime_factory, recorder_factory, fake)
    async with client_for(env) as client:
        await client.post("/meetings/mic1/companion/enable", json={})
        accepted = await client.post("/meetings/mic1/companion/investigations", json={"question": "What is the Acme renewal term?"})
        assert accepted.status_code == 202 and accepted.json()["investigation_id"].startswith("iv-")
        await env.runtime.session_for("mic1").wait_idle()
        snapshot = (await client.get("/meetings/mic1/companion")).json()
        researched = [item for item in snapshot["items"] if item["researched"]]
        assert len(researched) == 1 and researched[0]["investigation_id"] == accepted.json()["investigation_id"]
        assert researched[0]["evidence_count"] == 3 and snapshot["status"]["investigating"] == 0
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_investigation_requests_validate_and_report_refusals(home, runtime_factory, recorder_factory):
    env = await live(runtime_factory, recorder_factory, FakeInvestigator())
    async with client_for(env) as client:
        missing = await client.post("/meetings/mic1/companion/investigations", json={"question": "What is the Acme renewal term?"})
        assert missing.status_code == 409
        await client.post("/meetings/mic1/companion/enable", json={})
        assert (await client.post("/meetings/mic1/companion/investigations", json={"question": ""})).status_code == 422
        assert (await client.post("/meetings/mic1/companion/investigations", json={"question": "x" * 301})).status_code == 422
        assert (await client.post("/meetings/mic1/companion/investigations", json={"question": "   "})).status_code == 422
        assert (await client.post("/meetings/mic1/companion/investigations", json={"question": "valid question here", "extra": 1})).status_code == 422
        await client.patch("/meetings/mic1/companion/settings", json={"investigate": False})
        refused = await client.post("/meetings/mic1/companion/investigations", json={"question": "What is the Acme renewal term?"})
        assert refused.status_code == 409 and "turned off" in refused.json()["detail"]
        assert (await client.post("/meetings/bad%20id/companion/investigations", json={"question": "valid question here"})).status_code == 404
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_an_active_investigation_can_be_canceled_once(home, runtime_factory, recorder_factory):
    fake = FakeInvestigator()
    fake.release = asyncio.Event()
    env = await live(runtime_factory, recorder_factory, fake)
    async with client_for(env) as client:
        await client.post("/meetings/mic1/companion/enable", json={})
        accepted = await client.post("/meetings/mic1/companion/investigations", json={"question": "What is the Acme renewal term?"})
        investigation_id = accepted.json()["investigation_id"]
        await asyncio.sleep(0)
        assert (await client.delete(f"/meetings/mic1/companion/investigations/{investigation_id}")).status_code == 200
        await asyncio.wait_for(env.runtime.session_for("mic1").wait_idle(), timeout=3.0)
        assert (await client.delete(f"/meetings/mic1/companion/investigations/{investigation_id}")).status_code == 404
        snapshot = (await client.get("/meetings/mic1/companion")).json()
        assert [item for item in snapshot["items"] if item["researched"]] == [] and fake.canceled == [investigation_id]
    await env.runtime.shutdown()
