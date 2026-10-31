import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from api.routes.meetings import companion_routes
from api.services.meeting_companion import offline
from api.services.meeting_companion import store as store_module
from api.services.meeting_companion.audit import AuditFailed, AuditRejected
from api.services.meeting_companion.models import AuditMoment, AuditReport, CompanionSettings, CompanionTurn, TimelineEvent
from api.services.meeting_companion.offline_audits import StoredAudits
from api.services.meeting_companion.proposals import ProposalPolicy
from api.services.meeting_companion.store import CompanionDocument, CompanionStore

from .proposal_fakes import FakeLauncher

QUESTION = "How does the retry policy handle timeouts in billing?"


def moment(moment_id="am-1", text="Email Acme about the renewal term this week."):
    return AuditMoment(id=moment_id, start=10.0, end=20.0, kind="todo", why="Nobody took the follow-up.", suggested_text=text, confidence=0.8)


def report(audit_id="au-1", moments=None, scope="so_far"):
    return AuditReport(audit_id=audit_id, scope=scope, summary="Mostly right to stay quiet.", moments=moments if moments is not None else [moment()], evaluations=6, spoke=1, covered_until=30.0)


class FakeAuditor:
    def __init__(self, result=None, error=None):
        self.result = result if result is not None else report()
        self.error = error
        self.inputs = []
        self.gate = None

    async def audit(self, inputs):
        self.inputs.append(inputs)
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return self.result


def turn(index, start):
    return CompanionTurn(id=f"t-{index:04d}", source_meeting_id="m1", role="self", speaker="Microphone", start=start, end=start + 4.0, text="We should email Acme about the renewal term.")


async def started(make_session, auditor):
    harness = make_session(auditor=auditor)
    harness.add_member()
    await harness.session.start(run_loop=False)
    return harness


async def feed(harness):
    harness.say(QUESTION, 1.0, 4.0)
    await harness.settle()


@pytest.mark.asyncio
async def test_an_audit_of_a_live_meeting_runs_in_the_background_and_lands_on_the_timeline(make_session):
    auditor = FakeAuditor()
    auditor.gate = asyncio.Event()
    harness = await started(make_session, auditor)
    await feed(harness)
    harness.session.request_audit()
    assert harness.session.status().auditing is True
    with pytest.raises(AuditRejected, match="already running"):
        harness.session.request_audit()
    auditor.gate.set()
    await harness.session.wait_idle()
    assert harness.session.status().auditing is False
    audit = harness.session.snapshot("mic1").audit
    assert audit.audit_id == "au-1" and audit.moments[0].id == "am-1"
    assert auditor.inputs[0].scope == "so_far" and [t.text for t in auditor.inputs[0].turns] == [QUESTION]
    assert [event.kind for event in harness.session.events()].count("audit") == 1
    assert any(frame.get("event_type") == "meeting_companion_event" and frame["event"]["kind"] == "audit" for frame in harness.broadcasts)
    feed_items = [item for item in harness.session.snapshot("mic1").items if item.trigger == "audit"]
    assert [(item.text, item.kind, item.transcript_range.start, item.transcript_range.end) for item in feed_items] == [("Email Acme about the renewal term this week.", "suggestion", 10.0, 20.0)]
    assert any(frame.get("event_type") == "meeting_companion_event" and frame["event"]["kind"] == "item" and frame["event"]["meeting_time"] == 20.0 for frame in harness.broadcasts)


@pytest.mark.asyncio
async def test_an_audit_is_refused_without_a_transcript_or_an_auditor(make_session):
    harness = await started(make_session, FakeAuditor())
    with pytest.raises(AuditRejected, match="no transcript"):
        harness.session.request_audit()
    bare = make_session()
    bare.add_member()
    await bare.session.start(run_loop=False)
    with pytest.raises(AuditRejected, match="not available"):
        bare.session.request_audit()


@pytest.mark.asyncio
async def test_a_failed_audit_is_recorded_for_the_pane_and_clears_the_running_state(make_session):
    harness = await started(make_session, FakeAuditor(error=AuditFailed("timeout")))
    await feed(harness)
    harness.session.request_audit()
    await harness.session.wait_idle()
    assert harness.session.status().auditing is False and harness.session.snapshot("mic1").audit is None
    errors = [event.payload for event in harness.session.events() if event.kind == "error"]
    assert errors[-1]["code"] == "audit_failed" and "timeout" in errors[-1]["message"]
    harness.session.request_audit()
    await harness.session.wait_idle()
    assert len([event for event in harness.session.events() if event.kind == "error" and event.payload["code"] == "audit_failed"]) == 2


@pytest.mark.asyncio
async def test_marks_are_recorded_on_findings_and_a_new_audit_replaces_the_report(make_session):
    auditor = FakeAuditor()
    harness = await started(make_session, auditor)
    await feed(harness)
    harness.session.request_audit()
    await harness.session.wait_idle()
    assert harness.session.record_feedback("am-1", "audit_agree") is True
    assert harness.session.snapshot("mic1").audit.moments[0].mark == "agree"
    assert harness.session.record_feedback("am-1", "audit_clear") is True and harness.session.snapshot("mic1").audit.moments[0].mark is None
    assert harness.session.record_feedback("nope", "audit_agree") is False
    assert harness.session.record_feedback("am-1", "dismissed") is False
    auditor.result = report("au-2", [moment("am-9", "Check the vendor security audit results.")], scope="meeting")
    harness.session.request_audit()
    await harness.session.wait_idle()
    audit = harness.session.snapshot("mic1").audit
    assert audit.audit_id == "au-2" and [m.id for m in audit.moments] == ["am-9"]
    assert harness.session.record_feedback("am-1", "audit_agree") is False


@pytest.mark.asyncio
async def test_a_finding_becomes_a_to_do_through_the_same_action_as_a_note(make_session):
    launcher = FakeLauncher()
    harness = make_session(auditor=FakeAuditor(), proposal_launcher=launcher, proposal_policy=lambda: ProposalPolicy())
    harness.add_member()
    await harness.session.start(run_loop=False)
    await feed(harness)
    harness.session.request_audit()
    await harness.session.wait_idle()
    result = await harness.session.act_on_item("am-1", "todo")
    assert result.decision.state == "started" and launcher.created[0]["title"] == "Email Acme about the renewal term this week."
    [card] = [item for item in harness.session.snapshot("mic1").items if item.kind == "proposal"]
    assert card.source_item_id == "am-1" and card.proposal.authority == "review"
    with pytest.raises(Exception, match="already has an action"):
        await harness.session.act_on_item("am-1", "agent_task")


@pytest.mark.asyncio
async def test_a_session_is_audited_at_the_end_only_after_five_evaluations(make_session):
    harness = await started(make_session, FakeAuditor())
    assert harness.session.should_audit_at_end() is False
    for index in range(4):
        harness.session._append("evaluation", float(index), {"trigger": "periodic", "considered": "", "kept": 0})
    assert harness.session.should_audit_at_end() is False
    harness.session._append("evaluation", 5.0, {"trigger": "periodic", "considered": "", "kept": 0})
    assert harness.session.should_audit_at_end() is True
    bare = make_session()
    bare.add_member()
    await bare.session.start(run_loop=False)
    for index in range(6):
        bare.session._append("evaluation", float(index), {"trigger": "periodic", "considered": "", "kept": 0})
    assert bare.session.should_audit_at_end() is False


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "meetings_root", lambda: tmp_path)
    return tmp_path


def save_meeting(home, meeting_id="m1", events=None):
    directory = home / meeting_id
    directory.mkdir(parents=True, exist_ok=True)
    CompanionStore(directory).save(CompanionDocument(session_key=meeting_id, settings=CompanionSettings(enabled=True), events=events or [], saved_at="w"))
    return directory


def stored(auditor, broadcasts):
    async def broadcast(message):
        broadcasts.append(message)

    return StoredAudits(auditor=auditor, broadcast=broadcast)


@pytest.mark.asyncio
async def test_a_finished_meeting_audit_is_saved_announced_and_restored(home):
    save_meeting(home)
    broadcasts = []
    auditor = FakeAuditor(report(scope="meeting"))
    service = stored(auditor, broadcasts)
    assert await service.request("m1", turns=[turn(1, 10.0), turn(2, 30.0)]) is True
    await service.wait_idle()
    await asyncio.sleep(0)
    audit = offline.load_stored_snapshot("m1").audit
    assert audit.audit_id == "au-1" and audit.scope == "meeting"
    kinds = [(frame["event_type"], frame.get("auditing")) for frame in broadcasts]
    assert ("meeting_companion_status", True) in kinds and ("meeting_companion_status", False) in kinds
    assert any(frame["event_type"] == "meeting_companion_event" and frame["event"]["kind"] == "audit" and frame["meeting_ids"] == ["m1"] for frame in broadcasts)
    assert service.is_running("m1") is False
    assert [(item.text, item.trigger, item.transcript_range.end) for item in offline.load_stored_snapshot("m1").items] == [("Email Acme about the renewal term this week.", "audit", 20.0)]
    assert any(frame["event_type"] == "meeting_companion_event" and frame["event"]["kind"] == "item" and frame["meeting_ids"] == ["m1"] for frame in broadcasts)
    assert offline.record_stored_feedback("m1", "am-1", "audit_disagree") is True
    assert offline.load_stored_snapshot("m1").audit.moments[0].mark == "disagree"
    assert offline.record_stored_feedback("m1", "ghost", "audit_agree") is False
    assert offline.record_stored_feedback("m1", "am-1", "pinned") is False


@pytest.mark.asyncio
async def test_a_second_audit_is_refused_while_one_runs_and_missing_or_empty_meetings_are_reported(home):
    save_meeting(home)
    auditor = FakeAuditor()
    auditor.gate = asyncio.Event()
    service = stored(auditor, [])
    assert await service.request("m1", turns=[turn(1, 10.0)]) is True
    with pytest.raises(AuditRejected, match="already running"):
        await service.request("m1", turns=[turn(1, 10.0)])
    auditor.gate.set()
    await service.wait_idle()
    (home / "m2").mkdir()
    assert await service.request("m2", turns=[turn(1, 10.0)]) is None
    assert service.is_running("m2") is False
    save_meeting(home, "m3")
    with pytest.raises(AuditRejected, match="no saved transcript"):
        await service.request("m3")
    assert service.is_running("m3") is False


@pytest.mark.asyncio
async def test_the_saved_transcript_is_read_when_no_turns_are_given(home):
    directory = save_meeting(home)
    (directory / "metadata.json").write_text(json.dumps({"audio_source": "Microphone"}), encoding="utf-8")
    (directory / "transcript.json").write_text(json.dumps({"segments": [{"start": 1.0, "end": 4.0, "text": QUESTION}]}), encoding="utf-8")
    auditor = FakeAuditor()
    service = stored(auditor, [])
    assert await service.request("m1") is True
    await service.wait_idle()
    assert [t.text for t in auditor.inputs[0].turns] == [QUESTION]


@pytest.mark.asyncio
async def test_a_failed_finished_meeting_audit_is_saved_as_an_error_and_unblocks_a_retry(home):
    save_meeting(home)
    broadcasts = []
    service = stored(FakeAuditor(error=AuditFailed("timeout")), broadcasts)
    await service.request("m1", turns=[turn(1, 10.0)])
    await service.wait_idle()
    assert offline.load_stored_snapshot("m1").audit is None
    log = offline._open_stored_log("m1")
    assert [event.payload["code"] for event in log.events() if event.kind == "error"] == ["audit_failed"]
    assert service.is_running("m1") is False
    await service.request("m1", turns=[turn(1, 10.0)])
    await service.wait_idle()
    assert len([event for event in offline._open_stored_log("m1").events() if event.kind == "error"]) == 2


def client_for(env):
    app = FastAPI()
    app.dependency_overrides[companion_routes.get_companion_runtime] = lambda: env.runtime
    app.include_router(companion_routes.router, prefix="/meetings")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_the_audit_route_covers_finished_and_missing_meetings(home, runtime_factory):
    env = runtime_factory()
    env.runtime._stored_audits._auditor = FakeAuditor(report(scope="meeting"))
    directory = save_meeting(home)
    (directory / "transcript.json").write_text(json.dumps({"segments": [{"start": 1.0, "end": 4.0, "text": QUESTION}]}), encoding="utf-8")
    async with client_for(env) as client:
        accepted = await client.post("/meetings/m1/companion/audit")
        assert accepted.status_code == 202 and accepted.json() == {"started": True}
        await env.runtime.stored_audits.wait_idle()
        snapshot = (await client.get("/meetings/m1/companion")).json()
        assert snapshot["audit"]["audit_id"] == "au-1" and snapshot["audit"]["moments"][0]["mark"] is None
        mark = await client.post("/meetings/m1/companion/items/am-1/feedback", json={"action": "audit_agree"})
        assert mark.status_code == 200
        assert (await client.get("/meetings/m1/companion")).json()["audit"]["moments"][0]["mark"] == "agree"
        assert (await client.post("/meetings/m1/companion/items/ghost/feedback", json={"action": "audit_agree"})).status_code == 404
        (home / "m2").mkdir()
        missing = await client.post("/meetings/m2/companion/audit")
        assert missing.status_code == 404 and "no saved Companion notes" in missing.json()["detail"]
        save_meeting(home, "m3")
        empty = await client.post("/meetings/m3/companion/audit")
        assert empty.status_code == 409 and "no saved transcript" in empty.json()["detail"]
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_a_finding_in_a_finished_meeting_can_become_a_to_do_over_http(home, runtime_factory):
    env = runtime_factory()
    env.launcher = FakeLauncher()
    env.runtime._proposal_launcher = env.launcher
    env.runtime._stored_audits._auditor = FakeAuditor(report(scope="meeting"))
    directory = save_meeting(home)
    (directory / "transcript.json").write_text(json.dumps({"segments": [{"start": 1.0, "end": 4.0, "text": QUESTION}]}), encoding="utf-8")
    async with client_for(env) as client:
        await client.post("/meetings/m1/companion/audit")
        await env.runtime.stored_audits.wait_idle()
        done = await client.post("/meetings/m1/companion/items/am-1/action", json={"action": "todo"})
        assert done.status_code == 200 and done.json()["state"] == "started"
        cards = [item for item in (await client.get("/meetings/m1/companion")).json()["items"] if item["kind"] == "proposal"]
        assert cards[0]["source_item_id"] == "am-1"
        assert (await client.post("/meetings/m1/companion/items/am-1/action", json={"action": "todo"})).status_code == 409
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_a_live_audit_route_returns_202_and_a_second_request_is_a_conflict(home, runtime_factory, recorder_factory):
    env = runtime_factory()
    auditor = FakeAuditor()
    auditor.gate = asyncio.Event()
    env.runtime._auditor = auditor
    env.recorders.append(recorder_factory("mic1"))
    async with client_for(env) as client:
        await client.post("/meetings/mic1/companion/enable", json={})
        session = env.runtime.session_for("mic1")
        assert (await client.post("/meetings/mic1/companion/audit")).status_code == 409
        session._auditor = auditor
        session.on_segment("mic1", {"start": 1.0, "end": 4.0, "text": QUESTION, "speaker": "Microphone", "is_interim": False})
        await session.tick()
        await session.wait_idle()
        assert (await client.post("/meetings/mic1/companion/audit")).status_code == 202
        again = await client.post("/meetings/mic1/companion/audit")
        assert again.status_code == 409 and "already running" in again.json()["detail"]
        auditor.gate.set()
        await session.wait_idle()
    await env.runtime.shutdown()


def segment(text, start, end):
    return {"start": start, "end": end, "text": text, "speaker": "Microphone", "is_interim": False}


async def stopped(env, recorder_factory, tmp_path, *, evaluations, discarded=False):
    mic = recorder_factory("mic1")
    env.recorders.append(mic)
    session = await env.runtime.enable("mic1")
    env.runtime._on_registry_event("segment", "mic1", mic, {"segment": segment(QUESTION, 1.0, 4.0)})
    await env.runtime.wait_idle()
    await session.tick()
    await session.wait_idle()
    for index in range(evaluations):
        session._append("evaluation", 5.0 + index, {"trigger": "periodic", "considered": "", "kept": 0})
    env.runtime._on_registry_event("discarded" if discarded else "stopped", "mic1", mic, None)
    await env.runtime.wait_idle()
    await env.runtime.stored_audits.wait_idle()
    return CompanionStore(tmp_path / "mic1").load()


@pytest.mark.asyncio
async def test_ending_a_meeting_runs_one_audit_from_the_transcript_the_session_held(home, runtime_factory, recorder_factory, tmp_path):
    env = runtime_factory()
    auditor = FakeAuditor(report(scope="meeting"))
    env.runtime._auditor = auditor
    env.runtime._stored_audits._auditor = auditor
    document = await stopped(env, recorder_factory, tmp_path, evaluations=5)
    assert len(auditor.inputs) == 1 and auditor.inputs[0].scope == "meeting"
    assert QUESTION in [t.text for t in auditor.inputs[0].turns]
    assert any(event.kind == "audit" for event in document.events)
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_ending_a_meeting_with_few_evaluations_is_not_audited(home, runtime_factory, recorder_factory, tmp_path):
    few = runtime_factory()
    few_auditor = FakeAuditor()
    few.runtime._auditor = few_auditor
    few.runtime._stored_audits._auditor = few_auditor
    document = await stopped(few, recorder_factory, tmp_path, evaluations=2)
    assert few_auditor.inputs == [] and not any(event.kind == "audit" for event in document.events)
    await few.runtime.shutdown()


@pytest.mark.asyncio
async def test_a_discarded_meeting_is_not_audited(home, runtime_factory, recorder_factory, tmp_path):
    env = runtime_factory()
    auditor = FakeAuditor()
    env.runtime._auditor = auditor
    env.runtime._stored_audits._auditor = auditor
    await stopped(env, recorder_factory, tmp_path, evaluations=8, discarded=True)
    assert auditor.inputs == []
    await env.runtime.shutdown()
