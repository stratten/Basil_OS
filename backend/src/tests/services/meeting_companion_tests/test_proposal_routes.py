import httpx
import pytest
from fastapi import FastAPI

from api.routes.meetings import companion_routes
from api.services.meeting_companion import offline
from api.services.meeting_companion import store as store_module
from api.services.meeting_companion.investigator.models import ProposedAction
from api.services.meeting_companion.models import CompanionItem, CompanionSettings, ProposalInfo, TimelineEvent, TranscriptRange
from api.services.meeting_companion.proposals import ProposalLaunchError
from api.services.meeting_companion.store import CompanionDocument, CompanionStore

from .investigator_session_fakes import FakeInvestigator
from .proposal_fakes import FakeLauncher

ACTIONS = [
    ProposedAction(action="agent_task", title="Draft vendor summary", instruction="Write a one page summary of the vendor comparison"),
    ProposedAction(action="todo", title="Add renewal reminder", instruction="Create a reminder for the contract renewal date"),
]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "meetings_root", lambda: tmp_path)
    return tmp_path


def client_for(env):
    app = FastAPI()
    app.dependency_overrides[companion_routes.get_companion_runtime] = lambda: env.runtime
    app.include_router(companion_routes.router, prefix="/meetings")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def live_with_proposals(runtime_factory, recorder_factory):
    env = runtime_factory()
    fake = FakeInvestigator()
    fake.proposals = list(ACTIONS)
    env.launcher = FakeLauncher()
    env.runtime._investigator = fake
    env.runtime._proposal_launcher = env.launcher
    env.recorders.append(recorder_factory("mic1"))
    return env


async def proposal_items(client):
    await client.post("/meetings/mic1/companion/enable", json={})
    accepted = await client.post("/meetings/mic1/companion/investigations", json={"question": "What is the Acme renewal term?"})
    assert accepted.status_code == 202
    return accepted


async def snapshot_cards(client):
    return [item for item in (await client.get("/meetings/mic1/companion")).json()["items"] if item["kind"] == "proposal"]


@pytest.mark.asyncio
async def test_approving_over_http_starts_the_action_and_the_snapshot_shows_it(home, runtime_factory, recorder_factory):
    env = await live_with_proposals(runtime_factory, recorder_factory)
    async with client_for(env) as client:
        await proposal_items(client)
        await env.runtime.session_for("mic1").wait_idle()
        waiting = await snapshot_cards(client)
        assert [card["proposal"]["state"] for card in waiting] == ["proposed", "proposed"]
        response = await client.post(f"/meetings/mic1/companion/items/{waiting[0]['id']}/proposal", json={"decision": "approve"})
        assert response.status_code == 200
        assert response.json() == {"state": "started", "title": "Draft vendor summary", "instruction": "Write a one page summary of the vendor comparison", "todo_id": "todo-1", "agent_task_id": "task-1", "error": None}
        after = await snapshot_cards(client)
        assert after[0]["proposal"]["state"] == "started" and after[0]["proposal"]["todo_id"] == "todo-1" and after[1]["proposal"]["state"] == "proposed"
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_http_refusals_use_the_right_status_codes(home, runtime_factory, recorder_factory):
    env = await live_with_proposals(runtime_factory, recorder_factory)
    async with client_for(env) as client:
        await proposal_items(client)
        await env.runtime.session_for("mic1").wait_idle()
        waiting = await snapshot_cards(client)
        plain = next(item for item in (await client.get("/meetings/mic1/companion")).json()["items"] if item["kind"] == "answer")
        url = "/meetings/mic1/companion/items/{}/proposal"
        assert (await client.post(url.format("nope"), json={"decision": "approve"})).status_code == 404
        not_a_proposal = await client.post(url.format(plain["id"]), json={"decision": "approve"})
        assert not_a_proposal.status_code == 409 and "not a proposal" in not_a_proposal.json()["detail"]
        assert (await client.post(url.format(waiting[0]["id"]), json={"decision": "maybe"})).status_code == 422
        assert (await client.post(url.format(waiting[0]["id"]), json={"decision": "approve", "extra": 1})).status_code == 422
        assert (await client.post(url.format(waiting[0]["id"]), json={})).status_code == 422
        assert (await client.post(url.format(waiting[0]["id"]), json={"decision": "approve"})).status_code == 200
        repeat = await client.post(url.format(waiting[0]["id"]), json={"decision": "approve"})
        assert repeat.status_code == 409 and "already started" in repeat.json()["detail"]
        assert (await client.post("/meetings/bad id/companion/items/x/proposal", json={"decision": "approve"})).status_code == 404
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_dismissing_over_http_hides_the_card(home, runtime_factory, recorder_factory):
    env = await live_with_proposals(runtime_factory, recorder_factory)
    async with client_for(env) as client:
        await proposal_items(client)
        await env.runtime.session_for("mic1").wait_idle()
        waiting = await snapshot_cards(client)
        dismissed = await client.post(f"/meetings/mic1/companion/items/{waiting[1]['id']}/proposal", json={"decision": "dismiss"})
        assert dismissed.status_code == 200 and dismissed.json()["state"] == "dismissed"
        after = await snapshot_cards(client)
        assert after[1]["dismissed"] is True and after[1]["proposal"]["state"] == "dismissed" and env.launcher.created == []
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_a_failed_launch_is_a_normal_response_and_a_retry_succeeds(home, runtime_factory, recorder_factory):
    env = await live_with_proposals(runtime_factory, recorder_factory)
    env.launcher.launch_error = ProposalLaunchError("The To-Do worker is not ready yet. Try again in a moment.")
    async with client_for(env) as client:
        await proposal_items(client)
        await env.runtime.session_for("mic1").wait_idle()
        card = (await snapshot_cards(client))[0]
        url = f"/meetings/mic1/companion/items/{card['id']}/proposal"
        failed = await client.post(url, json={"decision": "approve"})
        assert failed.status_code == 200 and failed.json()["state"] == "failed" and "not ready" in failed.json()["error"] and failed.json()["todo_id"] == "todo-1"
        assert (await snapshot_cards(client))[0]["proposal"]["state"] == "failed"
        env.launcher.launch_error = None
        retried = await client.post(url, json={"decision": "approve"})
        assert retried.json()["state"] == "started" and retried.json()["todo_id"] == "todo-1" and retried.json()["agent_task_id"] == "task-1"
        assert len(env.launcher.created) == 1
    await env.runtime.shutdown()


def saved_proposal(home, meeting_id="m1"):
    item = CompanionItem(
        id="i1",
        kind="proposal",
        text="Add a renewal reminder",
        confidence=0.9,
        transcript_range=TranscriptRange(start=1.0, end=2.0, turn_ids=[]),
        trigger="investigation",
        researched=True,
        proposal=ProposalInfo(proposal_id="pr-i1", action="todo", title="Add a renewal reminder", instruction="Add a reminder to renew the contract"),
    )
    directory = home / meeting_id
    directory.mkdir(parents=True, exist_ok=True)
    event = TimelineEvent(id="e1", seq=1, kind="item", meeting_time=2.0, wall_time="w", payload={"item": item.model_dump(mode="json")})
    CompanionStore(directory).save(CompanionDocument(session_key=meeting_id, settings=CompanionSettings(enabled=True), events=[event], saved_at="w"))


@pytest.mark.asyncio
async def test_a_finished_meeting_can_still_approve_and_the_outcome_is_saved(home, runtime_factory):
    env = runtime_factory()
    env.launcher = FakeLauncher()
    env.runtime._proposal_launcher = env.launcher
    saved_proposal(home)
    async with client_for(env) as client:
        response = await client.post("/meetings/m1/companion/items/i1/proposal", json={"decision": "approve"})
        assert response.status_code == 200 and response.json()["state"] == "started" and response.json()["todo_id"] == "todo-1"
        assert (await client.get("/meetings/m1/companion")).json()["items"][0]["proposal"]["state"] == "started"
        assert (await client.post("/meetings/m1/companion/items/i1/proposal", json={"decision": "approve"})).status_code == 409
        assert (await client.post("/meetings/m1/companion/items/missing/proposal", json={"decision": "approve"})).status_code == 404
        (home / "m2").mkdir()
        empty = await client.post("/meetings/m2/companion/items/i1/proposal", json={"decision": "approve"})
        assert empty.status_code == 404 and "no saved Companion notes" in empty.json()["detail"]
    assert offline.load_stored_snapshot("m1").items[0].proposal.state == "started"


@pytest.mark.asyncio
async def test_global_settings_carry_the_proposal_policy_and_reject_unsafe_values(home, runtime_factory, recorder_factory):
    env = runtime_factory()
    async with client_for(env) as client:
        defaults = (await client.get("/meetings/companion/settings")).json()
        assert defaults["proposal_mode"] == "suggestion_only" and defaults["auto_execute_capabilities"] == [] and defaults["proposal_capabilities"] == ["todo", "agent_task", "assistant_session"]
        updated = await client.put("/meetings/companion/settings", json={"proposal_mode": "auto_execute", "auto_execute_capabilities": ["todo", "todo", "agent_task"], "proposal_capabilities": ["todo", "agent_task"]})
        assert updated.status_code == 200
        assert updated.json()["proposal_mode"] == "auto_execute" and updated.json()["auto_execute_capabilities"] == ["todo", "agent_task"] and updated.json()["proposal_capabilities"] == ["todo", "agent_task"]
        assert env.runtime._proposal_policy.auto_capabilities == ("todo", "agent_task") and env.runtime._proposal_policy.capabilities == ("todo", "agent_task")
        assert (await client.put("/meetings/companion/settings", json={"auto_execute_capabilities": ["assistant_session"]})).status_code == 422
        assert (await client.put("/meetings/companion/settings", json={"proposal_capabilities": ["email"]})).status_code == 422
        assert (await client.put("/meetings/companion/settings", json={"proposal_mode": "always"})).status_code == 422
        assert (await client.put("/meetings/companion/settings", json={"auto_enable": True})).json()["proposal_mode"] == "auto_execute"
        off = await client.put("/meetings/companion/settings", json={"proposal_mode": "suggestion_only"})
        assert off.json()["proposal_mode"] == "suggestion_only" and env.runtime._proposal_policy.auto_capabilities == ()
    env.recorders.append(recorder_factory("mic1"))
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_a_new_session_reads_the_saved_policy(home, runtime_factory, recorder_factory):
    env = runtime_factory()
    env.runtime.update_global_settings(proposal_mode="auto_execute", auto_execute_capabilities=["todo"])
    env.recorders.append(recorder_factory("mic1"))
    async with client_for(env) as client:
        await client.post("/meetings/mic1/companion/enable", json={})
        policy = env.runtime.session_for("mic1")._proposal_policy()
        assert policy.auto_capabilities == ("todo",)
    await env.runtime.shutdown()
