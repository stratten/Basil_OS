import asyncio

import pytest

from api.services.meeting_companion.evaluator import EvaluationOutcome
from api.services.meeting_companion.investigator.escalation import ResearchRequest
from api.services.meeting_companion.investigator.models import InvestigationRejected
from api.services.meeting_companion.models import CompanionItem, CompanionSettings, TimelineEvent, TranscriptRange
from api.services.meeting_companion.store import CompanionDocument, CompanionStore

from .investigator_session_fakes import FakeInvestigator

QUESTION = "How does the retry policy handle timeouts in billing?"
RESEARCH = ResearchRequest(question="What is the vendor renewal term in the Acme contract?", reason="not in the transcript")
SUBJECTS = ["alpha budget forecast", "bravo hiring plan", "charlie retention metrics", "delta security review", "echo pricing tiers", "foxtrot launch timeline"]


def research_outcome():
    return EvaluationOutcome(items=[], conversation_state="Reviewing the Acme contract.", research=RESEARCH)


async def started(make_session, fake=None, **kwargs):
    fake = fake or FakeInvestigator()
    harness = make_session(investigator=fake, **kwargs)
    harness.add_member()
    await harness.session.start(run_loop=False)
    return harness, fake


def researched_items(harness):
    return [item for item in harness.session.snapshot("mic1").items if item.researched]


@pytest.mark.asyncio
async def test_an_unanswered_question_escalates_and_appends_a_researched_item(make_session):
    harness, fake = await started(make_session)
    harness.evaluator.override = research_outcome()
    harness.say(QUESTION, 10.0, 14.0)
    await harness.settle()
    request = fake.requests[0]
    assert request.origin == "unanswered" and request.question == RESEARCH.question and request.source_turn_ids
    items = researched_items(harness)
    assert len(items) == 1
    item = items[0]
    assert item.kind == "answer" and item.trigger == "investigation" and item.text == "The renewal term is twelve months."
    assert item.investigation_id == request.investigation_id and item.evidence_count == 3 and item.no_source is False
    assert [citation.path for citation in item.citations] == ["proj/contract.md"]
    assert item.transcript_range.turn_ids == request.source_turn_ids and item.transcript_range.end == pytest.approx(14.0)
    starts = [event for event in harness.event_kinds("retrieval") if event.payload["purpose"] == "investigation"]
    assert len(starts) == 1 and starts[0].payload["queries"] == [RESEARCH.question] and starts[0].payload["origin"] == "unanswered"
    assert harness.session.status().investigating == 0


@pytest.mark.asyncio
async def test_research_is_ignored_when_the_evaluator_also_returned_an_item(make_session):
    harness, fake = await started(make_session)
    direct = CompanionItem(id="i1", kind="answer", text="Direct answer.", confidence=0.9, no_source=True, transcript_range=TranscriptRange(start=10.0, end=14.0, turn_ids=[]), trigger="question")
    harness.evaluator.override = EvaluationOutcome(items=[direct], research=RESEARCH)
    harness.say(QUESTION, 10.0, 14.0)
    await harness.settle()
    assert fake.requests == [] and researched_items(harness) == []


@pytest.mark.asyncio
async def test_a_watch_escalation_carries_the_watch_id(make_session):
    harness, fake = await started(make_session)
    watch = harness.session.create_watch("billing", "show me the endpoint")
    harness.evaluator.override = research_outcome()
    harness.say("The billing endpoint is slow today.", 1.0, 4.0)
    await harness.settle()
    assert fake.requests[0].origin == "watch" and fake.requests[0].watch_id == watch.id
    assert researched_items(harness)[0].watch_id == watch.id


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["not_found", "failed", "timed_out"])
async def test_automatic_origins_stay_silent_unless_there_is_an_answer(make_session, status):
    harness, fake = await started(make_session, FakeInvestigator(status))
    harness.evaluator.override = research_outcome()
    harness.say(QUESTION, 10.0, 14.0)
    await harness.settle()
    assert len(fake.requests) == 1
    assert harness.session.snapshot("mic1").items == [] and harness.event_kinds("error") == []


@pytest.mark.asyncio
async def test_an_automatic_answer_that_repeats_a_shown_note_is_dropped(make_session):
    harness, fake = await started(make_session)
    shown = CompanionItem(id="i1", kind="insight", text="The renewal term is twelve months.", confidence=0.9, transcript_range=TranscriptRange(start=1.0, end=2.0, turn_ids=[]), trigger="periodic")
    harness.session._append("item", 2.0, {"item": shown.model_dump(mode="json")})
    harness.evaluator.override = research_outcome()
    harness.say(QUESTION, 10.0, 14.0)
    await harness.settle()
    assert len(fake.requests) == 1 and researched_items(harness) == []


@pytest.mark.asyncio
async def test_status_reports_the_active_run_and_clears_when_it_ends(make_session):
    harness, fake = await started(make_session)
    fake.release = asyncio.Event()
    harness.session.request_investigation("What is the Acme renewal term?")
    for _ in range(5):
        await asyncio.sleep(0)
    assert harness.session.status().investigating == 1
    assert any(message.get("investigating") == 1 for message in harness.broadcasts if message["event_type"] == "meeting_companion_status")
    fake.release.set()
    await harness.session.wait_idle()
    assert harness.session.status().investigating == 0
    assert [message["investigating"] for message in harness.broadcasts if message["event_type"] == "meeting_companion_status"][-1] == 0


@pytest.mark.asyncio
async def test_an_explicit_request_not_found_or_failed_is_always_visible(make_session):
    harness, _fake = await started(make_session, FakeInvestigator("not_found"))
    harness.session.request_investigation("What is the Acme renewal term?")
    await harness.session.wait_idle()
    note = researched_items(harness)[0]
    assert note.kind == "context_note" and note.no_source is True and "could not find an answer to: What is the Acme renewal term?" in note.text
    failed, _fake = await started(make_session, FakeInvestigator("failed"))
    failed.session.request_investigation("What is the Acme renewal term?")
    await failed.session.wait_idle()
    assert researched_items(failed) == []
    assert failed.event_kinds("error")[-1].payload["code"] == "investigation_failed"
    timed_out, _fake = await started(make_session, FakeInvestigator("timed_out"))
    timed_out.session.request_investigation("What is the Acme renewal term?")
    await timed_out.session.wait_idle()
    assert "ran out of time" in timed_out.event_kinds("error")[-1].payload["message"]


@pytest.mark.asyncio
async def test_a_chat_message_starts_an_investigation_and_replies(make_session):
    harness, fake = await started(make_session)
    harness.session.submit_chat("Please investigate the Acme renewal term")
    await harness.session.wait_idle()
    assert fake.requests[0].origin == "chat" and fake.requests[0].question == "the Acme renewal term"
    assert harness.evaluator.requests == []
    reply = [event for event in harness.event_kinds("chat") if event.payload["role"] == "assistant"][0].payload
    assert reply["status"] == "complete" and reply["text"].startswith("Looking into: the Acme renewal term")
    assert len(researched_items(harness)) == 1


@pytest.mark.asyncio
async def test_a_chat_request_is_refused_with_a_plain_reason_when_the_switch_is_off(make_session):
    harness, fake = await started(make_session)
    harness.session.update_settings(investigate=False)
    harness.session.submit_chat("investigate the Acme renewal term")
    await harness.session.wait_idle()
    reply = [event for event in harness.event_kinds("chat") if event.payload["role"] == "assistant"][0].payload
    assert reply["status"] == "error" and "turned off" in reply["text"] and fake.requests == []


@pytest.mark.asyncio
async def test_the_per_meeting_cap_duplicates_and_busy_runs_are_refused(make_session):
    harness, fake = await started(make_session)
    for subject in SUBJECTS:
        harness.session.request_investigation(subject)
        await harness.session.wait_idle()
    with pytest.raises(InvestigationRejected, match="6 investigations"):
        harness.session.request_investigation("golf vendor contract")
    assert len(fake.requests) == 6
    other, other_fake = await started(make_session)
    other.session.request_investigation(SUBJECTS[0])
    await other.session.wait_idle()
    with pytest.raises(InvestigationRejected, match="already been investigated"):
        other.session.request_investigation("alpha budget forecast please")
    other_fake.release = asyncio.Event()
    other.session.request_investigation(SUBJECTS[1])
    await asyncio.sleep(0)
    with pytest.raises(InvestigationRejected, match="busy"):
        other.session.request_investigation(SUBJECTS[2])
    other_fake.release.set()
    await other.session.wait_idle()
    with pytest.raises(ValueError, match="Describe what to look into"):
        other.session.request_investigation("  hi ")


@pytest.mark.asyncio
async def test_paused_capacity_cancels_active_runs_and_blocks_new_ones(make_session):
    harness, fake = await started(make_session)
    fake.release = asyncio.Event()
    harness.session.request_investigation("What is the Acme renewal term?")
    await asyncio.sleep(0)
    harness.guard.state = "paused"
    harness.clock.advance(1.0)
    await harness.session.tick()
    await asyncio.wait_for(harness.session.wait_idle(), timeout=3.0)
    assert len(fake.canceled) == 1 and researched_items(harness) == [] and harness.session.status().investigating == 0
    with pytest.raises(InvestigationRejected, match="paused"):
        harness.session.request_investigation("What is the Zephyr renewal term?")


@pytest.mark.asyncio
async def test_deferred_capacity_blocks_automatic_origins_but_not_requested_ones(make_session):
    harness, fake = await started(make_session)
    harness.guard.state = "deferred"
    harness.clock.advance(1.0)
    await harness.session.tick()
    harness.evaluator.override = research_outcome()
    harness.say(QUESTION, 10.0, 14.0)
    await harness.settle()
    assert fake.requests == []
    harness.session.request_investigation("What is the Acme renewal term?")
    await harness.session.wait_idle()
    assert len(fake.requests) == 1 and fake.requests[0].origin == "explicit"


@pytest.mark.asyncio
async def test_turning_the_switch_off_cancels_the_active_run(make_session):
    harness, fake = await started(make_session)
    fake.release = asyncio.Event()
    harness.session.request_investigation("What is the Acme renewal term?")
    await asyncio.sleep(0)
    harness.session.update_settings(investigate=False)
    await asyncio.wait_for(harness.session.wait_idle(), timeout=3.0)
    assert len(fake.canceled) == 1 and researched_items(harness) == []
    assert harness.session.status().investigate is False
    harness.session.update_settings(investigate=True)
    assert harness.session.status().investigate is True


@pytest.mark.asyncio
async def test_closing_the_session_cancels_runs_and_records_no_item(make_session):
    harness, fake = await started(make_session)
    fake.release = asyncio.Event()
    harness.session.request_investigation("What is the Acme renewal term?")
    await asyncio.sleep(0)
    await asyncio.wait_for(harness.session.close(), timeout=3.0)
    assert len(fake.canceled) == 1 and harness.event_kinds("item") == []
    with pytest.raises(RuntimeError):
        harness.session.request_investigation("What is the Zephyr renewal term?")


@pytest.mark.asyncio
async def test_the_investigator_is_unavailable_without_one(make_session):
    harness = make_session()
    harness.add_member()
    await harness.session.start(run_loop=False)
    with pytest.raises(InvestigationRejected, match="not available"):
        harness.session.request_investigation("What is the Acme renewal term?")
    assert harness.session.cancel_investigation("missing") is False


def stored_start(seq, question):
    return TimelineEvent(
        id=f"e{seq}",
        seq=seq,
        kind="retrieval",
        meeting_time=float(seq),
        wall_time="w",
        payload={"purpose": "investigation", "queries": [question], "hit_count": 0, "paths": [], "duration_ms": 0, "cache": "miss"},
    )


@pytest.mark.asyncio
async def test_a_restart_restores_the_run_count_and_the_question_list(make_session, tmp_path):
    directory = tmp_path / "mic1"
    directory.mkdir()
    events = [stored_start(index + 1, subject) for index, subject in enumerate(SUBJECTS)]
    CompanionStore(directory).save(CompanionDocument(session_key="sess1", settings=CompanionSettings(enabled=True), events=events, saved_at="w"))
    harness, fake = await started(make_session)
    with pytest.raises(InvestigationRejected, match="6 investigations"):
        harness.session.request_investigation("golf vendor contract")
    partial = [stored_start(1, SUBJECTS[0])]
    CompanionStore(directory).save(CompanionDocument(session_key="sess1", settings=CompanionSettings(enabled=True), events=partial, saved_at="w"))
    again, _fake = await started(make_session)
    with pytest.raises(InvestigationRejected, match="already been investigated"):
        again.session.request_investigation("alpha budget forecast")
    again.session.request_investigation("golf vendor contract")
    await again.session.wait_idle()
    assert fake.requests == []


@pytest.mark.asyncio
async def test_start_adopts_the_stored_switch_unless_it_was_chosen(make_session, tmp_path):
    directory = tmp_path / "mic1"
    directory.mkdir()
    stored = CompanionSettings(enabled=True, investigate=False)
    CompanionStore(directory).save(CompanionDocument(session_key="sess1", settings=stored, events=[], saved_at="w"))
    inherited, _fake = await started(make_session, settings=CompanionSettings(enabled=True), investigate_explicit=False)
    assert inherited.session.settings.investigate is False
    chosen, _fake = await started(make_session, settings=CompanionSettings(enabled=True, investigate=True), investigate_explicit=True)
    assert chosen.session.settings.investigate is True
