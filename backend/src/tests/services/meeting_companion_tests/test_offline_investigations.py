import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from api.routes.meetings import companion_routes
from api.services.meeting_companion import offline
from api.services.meeting_companion import store as store_module
from api.services.meeting_companion.investigator.models import InvestigationRejected
from api.services.meeting_companion.models import CompanionItem, CompanionSettings, TimelineEvent, TranscriptRange
from api.services.meeting_companion.offline_investigations import StoredInvestigations
from api.services.meeting_companion.store import CompanionDocument, CompanionStore
from api.services.meeting_companion.stored_transcript import load_stored_turns

from .investigator_session_fakes import FakeInvestigator

QUESTION = "What is the vendor renewal term in the Acme contract?"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "meetings_root", lambda: tmp_path)
    return tmp_path


def item_event(seq, item_id="i1"):
    item = CompanionItem(id=item_id, kind="insight", text="Worth confirming the term.", confidence=0.7, transcript_range=TranscriptRange(start=1.0, end=2.0, turn_ids=[]), trigger="periodic")
    return TimelineEvent(id=f"e{seq}", seq=seq, kind="item", meeting_time=2.0, wall_time="w", payload={"item": item.model_dump(mode="json")})


def source_event(seq, path, state="attached", root_id="r1"):
    return TimelineEvent(id=f"e{seq}", seq=seq, kind="source", meeting_time=0.0, wall_time="w", payload={"root_id": root_id, "state": state, "path": str(path), "display_name": "proj", "kind": "folder"})


def start_event(seq, subject):
    return TimelineEvent(id=f"e{seq}", seq=seq, kind="retrieval", meeting_time=3.0, wall_time="w", payload={"purpose": "investigation", "queries": [subject], "hit_count": 0, "paths": [], "duration_ms": 0, "cache": "miss", "investigation_id": f"iv-{seq}", "origin": "explicit"})


def save(home, events, meeting_id="m1"):
    directory = home / meeting_id
    directory.mkdir(parents=True, exist_ok=True)
    CompanionStore(directory).save(CompanionDocument(session_key=meeting_id, settings=CompanionSettings(enabled=True, investigate=False), events=events, saved_at="w"))


def write_transcript(home, meeting_id="m1", segments=None, **metadata):
    directory = home / meeting_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metadata.json").write_text(json.dumps({"id": meeting_id, **metadata}), encoding="utf-8")
    default = [{"start": 1.0, "end": 3.0, "text": "We should confirm the renewal term.", "speaker": None}, {"start": 10.0, "end": 12.0, "text": "I think it was a year", "speaker": None}]
    (directory / "transcript.json").write_text(json.dumps({"meeting_id": meeting_id, "segments": default if segments is None else segments}), encoding="utf-8")


def make_service(fake):
    frames = []

    async def broadcast(message):
        frames.append(message)

    async def model_for(model_id):
        return SimpleNamespace(model_id=model_id)

    return StoredInvestigations(investigator=fake, model_provider=model_for, broadcast=broadcast), frames


@pytest.mark.asyncio
async def test_an_investigation_runs_in_a_finished_meeting_and_lands_in_the_saved_timeline(home, tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    save(home, [source_event(1, project), item_event(2)])
    write_transcript(home)
    fake = FakeInvestigator()
    service, frames = make_service(fake)
    investigation_id = await service.request("m1", QUESTION)
    await service.wait_idle()
    assert investigation_id.startswith("iv-")
    request = fake.requests[0]
    assert request.origin == "explicit" and request.question == QUESTION
    assert [turn.text for turn in request.window_turns] == ["We should confirm the renewal term.", "I think it was a year"]
    snapshot = offline.load_stored_snapshot("m1")
    researched = [item for item in snapshot.items if item.researched]
    assert len(researched) == 1 and researched[0].investigation_id == investigation_id and researched[0].evidence_count == 3
    assert snapshot.last_seq == 5
    events = [frame for frame in frames if frame["event_type"] == "meeting_companion_event"]
    assert [frame["event"]["seq"] for frame in events] == [3, 4, 5]
    assert all(frame["meeting_ids"] == ["m1"] and frame["session_key"] == "m1" for frame in frames)
    statuses = [frame["investigating"] for frame in frames if frame["event_type"] == "meeting_companion_status"]
    assert statuses[0] == 1 and statuses[-1] == 0


@pytest.mark.asyncio
async def test_the_stored_switch_being_off_does_not_block_an_explicit_request(home):
    save(home, [item_event(1)])
    write_transcript(home)
    service, _frames = make_service(FakeInvestigator())
    assert await service.request("m1", QUESTION) is not None
    await service.wait_idle()


@pytest.mark.asyncio
async def test_a_meeting_with_nothing_saved_answers_none(home):
    (home / "m2").mkdir()
    service, _frames = make_service(FakeInvestigator())
    assert await service.request("m2", QUESTION) is None


@pytest.mark.asyncio
async def test_the_run_count_and_questions_are_restored_from_the_saved_timeline(home):
    subjects = ["alpha budget forecast", "bravo hiring plan", "charlie retention metrics", "delta security review", "echo pricing tiers", "foxtrot launch timeline", "hotel vendor onboarding", "india warehouse capacity", "juliet partner rebate", "kilo compliance audit"]
    save(home, [start_event(index + 1, subject) for index, subject in enumerate(subjects)])
    write_transcript(home)
    service, _frames = make_service(FakeInvestigator())
    with pytest.raises(InvestigationRejected, match="10 investigations"):
        await service.request("m1", "golf vendor contract")


@pytest.mark.asyncio
async def test_a_question_already_investigated_before_the_restart_is_refused(home):
    save(home, [start_event(1, QUESTION)])
    write_transcript(home)
    service, _frames = make_service(FakeInvestigator())
    with pytest.raises(InvestigationRejected, match="already been investigated"):
        await service.request("m1", QUESTION)


@pytest.mark.asyncio
async def test_a_source_folder_that_no_longer_exists_is_skipped_and_a_detached_one_is_not_attached(home, tmp_path):
    gone = tmp_path / "gone"
    detached = tmp_path / "detached"
    detached.mkdir()
    save(home, [source_event(1, gone, root_id="r1"), source_event(2, detached, root_id="r2"), source_event(3, detached, state="detached", root_id="r2")])
    write_transcript(home)
    seen = []

    class Recording(FakeInvestigator):
        async def investigate(self, request, *, context, cancel_event, model_provider):
            seen.append(context.has_roots())
            return await super().investigate(request, context=context, cancel_event=cancel_event, model_provider=model_provider)

    service, _frames = make_service(Recording())
    await service.request("m1", QUESTION)
    await service.wait_idle()
    assert seen == [False]


@pytest.mark.asyncio
async def test_a_reaction_saved_while_a_run_is_in_flight_is_not_lost_when_the_result_lands(home):
    save(home, [item_event(1)])
    write_transcript(home)
    fake = FakeInvestigator()
    fake.release = asyncio.Event()
    service, _frames = make_service(fake)
    await service.request("m1", QUESTION)
    await asyncio.sleep(0)
    assert offline.record_stored_feedback("m1", "i1", "pinned") is True
    fake.release.set()
    await service.wait_idle()
    snapshot = offline.load_stored_snapshot("m1")
    assert next(item for item in snapshot.items if item.id == "i1").pinned is True
    assert len([item for item in snapshot.items if item.researched]) == 1


@pytest.mark.asyncio
async def test_a_running_investigation_can_be_canceled_once(home):
    save(home, [item_event(1)])
    write_transcript(home)
    fake = FakeInvestigator()
    fake.release = asyncio.Event()
    service, _frames = make_service(fake)
    investigation_id = await service.request("m1", QUESTION)
    await asyncio.sleep(0)
    assert service.active_count("m1") == 1
    assert service.cancel("m1", investigation_id) is True
    await asyncio.wait_for(service.wait_idle(), timeout=3.0)
    assert service.cancel("m1", investigation_id) is False and service.cancel("other", investigation_id) is False
    assert [item for item in offline.load_stored_snapshot("m1").items if item.researched] == []
    assert fake.canceled == [investigation_id]


@pytest.mark.asyncio
async def test_a_reply_target_must_be_a_saved_user_chat_message(home):
    save(home, [item_event(1)])
    write_transcript(home)
    service, _frames = make_service(FakeInvestigator())
    with pytest.raises(ValueError, match="no longer available"):
        await service.request("m1", QUESTION, "msg-missing")


@pytest.mark.asyncio
async def test_a_failed_explicit_run_records_a_visible_failure_not_a_crash(home):
    save(home, [item_event(1)])
    write_transcript(home)
    service, _frames = make_service(FakeInvestigator(status="failed"))
    await service.request("m1", QUESTION)
    await service.wait_idle()
    events = [event for event in offline.load_stored_snapshot("m1").retrievals]
    assert len(events) == 1
    log_events = CompanionStore(home / "m1").load().events
    assert [event.kind for event in log_events][-2:] == ["error", "investigation"] and log_events[-2].payload["code"] == "investigation_failed"
    assert log_events[-1].payload["status"] == "failed" and log_events[-1].payload["shown"] is False


def client_for(runtime):
    app = FastAPI()
    app.dependency_overrides[companion_routes.get_companion_runtime] = lambda: runtime
    app.include_router(companion_routes.router, prefix="/meetings")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_the_route_investigates_a_finished_meeting_and_reports_missing_notes(home, runtime_factory):
    save(home, [item_event(1)])
    write_transcript(home)
    env = runtime_factory()
    fake = FakeInvestigator()
    service, _frames = make_service(fake)
    env.runtime._stored_investigations = service
    async with client_for(env.runtime) as client:
        accepted = await client.post("/meetings/m1/companion/investigations", json={"question": QUESTION})
        assert accepted.status_code == 202 and accepted.json()["investigation_id"].startswith("iv-")
        await service.wait_idle()
        snapshot = (await client.get("/meetings/m1/companion")).json()
        assert [item["investigation_id"] for item in snapshot["items"] if item["researched"]] == [accepted.json()["investigation_id"]]
        duplicate = await client.post("/meetings/m1/companion/investigations", json={"question": QUESTION})
        assert duplicate.status_code == 409 and "already been investigated" in duplicate.json()["detail"]
        (home / "m3").mkdir()
        assert (await client.post("/meetings/m3/companion/investigations", json={"question": QUESTION})).status_code == 404
        assert (await client.delete("/meetings/m1/companion/investigations/iv-nothing")).status_code == 404
    await env.runtime.shutdown()


def test_turns_from_every_session_member_share_one_timeline_and_bare_words_are_spaced(home):
    write_transcript(
        home,
        "mic",
        segments=[{"start": 1.0, "end": 2.0, "text": "whatever", "speaker": None}, {"start": 2.0, "end": 3.0, "text": "time", "speaker": None}],
        session_id="s1",
        audio_source="Microphone",
        start_time="2026-01-01T10:00:00.000000Z",
    )
    write_transcript(
        home,
        "sys",
        segments=[{"start": 1.0, "end": 2.0, "text": "Hello from the call.", "speaker": None}, {"start": "bad", "end": 3.0, "text": "skipped", "speaker": None}, {"start": 4.0, "end": 5.0, "text": "  ", "speaker": None}],
        session_id="s1",
        audio_source="System Audio",
        start_time="2026-01-01T10:00:05.000000Z",
    )
    turns = load_stored_turns("mic")
    assert [(turn.speaker, turn.text, round(turn.start, 1)) for turn in turns] == [("Microphone", "whatever time", 1.0), ("System Audio", "Hello from the call.", 6.0)]
    assert {turn.source_meeting_id for turn in turns} == {"mic", "sys"}


def test_a_meeting_without_a_transcript_has_no_turns_and_the_limit_keeps_the_latest(home):
    (home / "empty").mkdir()
    assert load_stored_turns("empty") == []
    segments = [{"start": float(index * 20), "end": float(index * 20 + 3), "text": f"Statement number {index} is long enough.", "speaker": "Anna"} for index in range(10)]
    write_transcript(home, "long", segments=segments)
    turns = load_stored_turns("long", limit=3)
    assert [turn.text for turn in turns] == [f"Statement number {index} is long enough." for index in (7, 8, 9)]


@pytest.mark.asyncio
async def test_a_source_attached_after_the_context_was_cached_reaches_the_next_run_and_a_detached_one_leaves_it(home, project):
    save(home, [item_event(1)])
    write_transcript(home)
    seen = []

    class Recording(FakeInvestigator):
        async def investigate(self, request, *, context, cancel_event, model_provider):
            seen.append(context.has_roots())
            return await super().investigate(request, context=context, cancel_event=cancel_event, model_provider=model_provider)

    service, _frames = make_service(Recording())
    await service.request("m1", QUESTION)
    await service.wait_idle()
    root = offline.attach_stored_root("m1", str(project))
    service.sync_attached("m1", root)
    await service.request("m1", "What does the retry policy do about timeouts in billing?")
    await service.wait_idle()
    service.sync_detached("m1", root.id)
    await service.request("m1", "Which other vendors quoted a different renewal term last quarter?")
    await service.wait_idle()
    assert seen == [False, True, False]
