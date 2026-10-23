import asyncio

import pytest

from api.services.meeting_companion.evaluator import EvaluationOutcome
from api.services.meeting_companion.models import CompanionSettings, TimelineEvent
from api.services.meeting_companion.store import CompanionDocument, CompanionStore

QUESTION = "How does the retry policy handle timeouts in billing?"


@pytest.mark.asyncio
async def test_question_fires_one_evaluation_and_item_is_stamped_with_range_end(make_session):
    harness = make_session()
    harness.add_member()
    await harness.session.start(run_loop=False)
    harness.say(QUESTION, 10.0, 14.0)
    await harness.settle()
    assert len(harness.evaluator.requests) == 1
    request = harness.evaluator.requests[0]
    assert request.trigger == "question"
    assert [turn.text for turn in request.new_turns] == [QUESTION]
    items = harness.event_kinds("item")
    assert len(items) == 1 and items[0].meeting_time == pytest.approx(14.0)
    snapshot = harness.session.snapshot("mic1")
    assert [item.text for item in snapshot.items] == ["Default answer."]
    assert snapshot.status.live is True and snapshot.last_seq == harness.session.events()[-1].seq
    kinds = {message["event_type"] for message in harness.broadcasts}
    assert {"meeting_companion_event", "meeting_companion_status"} <= kinds
    assert all(message["session_key"] == "sess1" and message["meeting_ids"] == ["mic1"] for message in harness.broadcasts)


@pytest.mark.asyncio
async def test_interim_blank_and_unknown_member_segments_are_ignored(make_session):
    harness = make_session()
    await harness.session.start(run_loop=False)
    harness.add_member()
    harness.say("Hello there everyone today.", 0.0, 2.0, interim=True)
    harness.say("   ", 2.0, 3.0)
    harness.say("Hello from a recorder we do not know.", 3.0, 5.0, meeting_id="ghost")
    assert harness.session.pending_line_count() == 0
    harness.say("Hello there everyone today.", 6.0, 8.0)
    assert harness.session.pending_line_count() == 1


@pytest.mark.asyncio
async def test_seeding_is_history_only_and_live_duplicates_are_dropped(make_session):
    harness = make_session()
    await harness.session.start(run_loop=False)
    existing = [{"start": 5.0, "end": 9.0, "text": QUESTION, "speaker": "Zoom", "is_interim": False}]
    harness.add_member(existing=existing)
    assert harness.session.pending_line_count() == 0
    harness.say(QUESTION, 5.0, 9.0)
    assert harness.session.pending_line_count() == 0
    await harness.settle()
    assert harness.evaluator.requests == []
    harness.say("Okay what about the second thing we planned?", 20.0, 22.0)
    await harness.settle()
    assert len(harness.evaluator.requests) == 1
    assert any("retry policy" in turn.text for turn in harness.evaluator.requests[0].window_turns)


@pytest.mark.asyncio
async def test_seeding_ignores_lines_older_than_the_seed_window(make_session):
    harness = make_session()
    await harness.session.start(run_loop=False)
    existing = [
        {"start": 0.0, "end": 4.0, "text": "An ancient remark about the quarterly roadmap.", "is_interim": False},
        {"start": 400.0, "end": 404.0, "text": "A recent remark about the invoice export.", "is_interim": False},
    ]
    harness.add_member(existing=existing)
    harness.say("What did we decide about the invoice export?", 410.0, 413.0)
    await harness.settle()
    texts = [turn.text for turn in harness.evaluator.requests[0].window_turns]
    assert not any("ancient" in text for text in texts) and any("invoice export" in text for text in texts)


@pytest.mark.asyncio
async def test_deferred_capacity_blocks_periodic_but_allows_questions_and_records_status(make_session):
    harness = make_session()
    harness.guard.state = "deferred"
    harness.guard.reason = "Transcription is 9s behind."
    await harness.session.start(run_loop=False)
    harness.add_member()
    lines = ["We should review the billing migration plan carefully.", "The invoice export still needs a second owner.", "Latency numbers look better after the cache change."]
    for index, text in enumerate(lines):
        harness.say(text, index * 5.0, index * 5.0 + 4.0)
    harness.clock.advance(50.0)
    await harness.settle()
    assert harness.evaluator.requests == []
    harness.say("How does the invoice export pick an owner?", 20.0, 24.0)
    await harness.settle()
    assert [request.trigger for request in harness.evaluator.requests] == ["question"]
    statuses = harness.event_kinds("status")
    assert statuses[-1].payload["capacity"] == "deferred" and statuses[-1].payload["reason"] == "Transcription is 9s behind."


@pytest.mark.asyncio
async def test_paused_capacity_blocks_everything_then_recovers(make_session):
    harness = make_session()
    await harness.session.start(run_loop=False)
    harness.add_member()
    harness.guard.state = "paused"
    harness.say(QUESTION, 1.0, 4.0)
    harness.clock.advance(1.0)
    await harness.settle()
    assert harness.evaluator.requests == []
    harness.guard.state = "ok"
    harness.clock.advance(1.0)
    await harness.settle()
    assert [request.trigger for request in harness.evaluator.requests] == ["question"]
    assert [event.payload["capacity"] for event in harness.event_kinds("status")] == ["ok", "paused", "ok"]


@pytest.mark.asyncio
async def test_evaluation_errors_are_recorded_once_per_interval(make_session):
    harness = make_session()
    harness.evaluator.override = EvaluationOutcome(error="model_unavailable: no key")
    await harness.session.start(run_loop=False)
    harness.add_member()
    harness.say(QUESTION, 1.0, 4.0)
    await harness.settle()
    harness.clock.advance(11.0)
    harness.say("What is the timeout for invoice retries?", 20.0, 23.0)
    await harness.settle()
    errors = harness.event_kinds("error")
    assert len(errors) == 1 and errors[0].payload["code"] == "evaluation_failed" and errors[0].payload["message"].startswith("model_unavailable")
    harness.clock.advance(31.0)
    harness.say("What is the limit for invoice exports?", 60.0, 63.0)
    await harness.settle()
    assert len(harness.event_kinds("error")) == 2
    assert harness.event_kinds("item") == []


@pytest.mark.asyncio
async def test_stale_result_is_dropped_but_conversation_state_is_kept(make_session):
    harness = make_session()
    harness.evaluator.advance_during = 80.0
    await harness.session.start(run_loop=False)
    harness.add_member()
    harness.say(QUESTION, 1.0, 4.0)
    await harness.settle()
    assert harness.event_kinds("item") == [] and harness.event_kinds("error") == []
    assert harness.session.conversation_state_text() == "Billing retries were discussed."
    harness.evaluator.advance_during = 0.0
    harness.say("What about the invoice export timeout?", 90.0, 93.0)
    await harness.settle()
    assert harness.evaluator.requests[1].conversation_state == "Billing retries were discussed."
    assert len(harness.event_kinds("item")) == 1


@pytest.mark.asyncio
async def test_only_one_evaluation_is_in_flight(make_session):
    harness = make_session()
    harness.evaluator.release = asyncio.Event()
    await harness.session.start(run_loop=False)
    harness.add_member()
    harness.say(QUESTION, 1.0, 4.0)
    await harness.session.tick()
    await asyncio.sleep(0)
    assert len(harness.evaluator.requests) == 1 and harness.session.status().evaluating is True
    harness.clock.advance(11.0)
    harness.say("What about the invoice export timeout?", 20.0, 23.0)
    await harness.session.tick()
    await asyncio.sleep(0)
    assert len(harness.evaluator.requests) == 1
    harness.evaluator.release.set()
    await harness.session.wait_idle()
    assert harness.session.status().evaluating is False
    harness.clock.advance(11.0)
    await harness.settle()
    assert len(harness.evaluator.requests) == 2


@pytest.mark.asyncio
async def test_prefetch_logs_one_retrieval_and_skips_an_unchanged_topic(make_session, project, attach_project):
    harness = make_session()
    await harness.session.start(run_loop=False)
    harness.add_member()
    attach_project(harness.context, project)
    await harness.context.rebuild_vocabulary()
    harness.say("Honestly the retry policy handle timeouts badly in this service.", 1.0, 5.0)
    await harness.settle()
    retrievals = harness.event_kinds("retrieval")
    assert len(retrievals) == 1
    assert retrievals[0].payload["purpose"] == "prefetch" and retrievals[0].payload["hit_count"] >= 1
    assert any(path.endswith("retry_policy.py") for path in retrievals[0].payload["paths"])
    harness.clock.advance(7.0)
    await harness.settle()
    assert len(harness.event_kinds("retrieval")) == 1


@pytest.mark.asyncio
async def test_answer_evaluation_uses_retrieved_context_and_logs_it(make_session, project, attach_project):
    harness = make_session()
    await harness.session.start(run_loop=False)
    harness.add_member()
    attach_project(harness.context, project)
    await harness.context.rebuild_vocabulary()
    harness.say("How does the retry policy handle timeouts in billing?", 1.0, 4.0)
    await harness.settle()
    request = harness.evaluator.requests[0]
    assert request.has_roots is True and request.pack is not None and request.pack.hit_count >= 1
    assert "answer" in [event.payload["purpose"] for event in harness.event_kinds("retrieval")]


@pytest.mark.asyncio
async def test_start_restores_roots_and_detaches_ones_that_vanished(make_session, project, tmp_path):
    directory = tmp_path / "mic1"
    directory.mkdir()
    events = [
        TimelineEvent(id="e1", seq=1, kind="source", meeting_time=1.0, wall_time="w", payload={"root_id": "r1", "state": "attached", "path": str(project), "display_name": "proj", "kind": "folder"}),
        TimelineEvent(id="e2", seq=2, kind="source", meeting_time=2.0, wall_time="w", payload={"root_id": "r2", "state": "attached", "path": str(tmp_path / "gone"), "display_name": "gone", "kind": "folder"}),
    ]
    CompanionStore(directory).save(CompanionDocument(session_key="sess1", settings=CompanionSettings(enabled=True), events=events, saved_at="w"))
    harness = make_session()
    harness.add_member()
    await harness.session.start(run_loop=False)
    await harness.session.wait_idle()
    assert harness.context.has_roots() is True
    snapshot = harness.session.snapshot("mic1")
    assert [root.id for root in snapshot.roots] == ["r1"]
    detached = [event for event in harness.event_kinds("source") if event.payload["state"] == "detached"]
    assert [event.payload["root_id"] for event in detached] == ["r2"]
    assert snapshot.last_seq == harness.session.events()[-1].seq and snapshot.last_seq > 2


@pytest.mark.asyncio
async def test_start_adopts_stored_mode_and_model_unless_explicit(make_session, tmp_path):
    directory = tmp_path / "mic1"
    directory.mkdir()
    stored = CompanionSettings(enabled=True, mode="passive", model_id="stored-model")
    CompanionStore(directory).save(CompanionDocument(session_key="sess1", settings=stored, events=[], saved_at="w"))
    inherited = make_session(settings=CompanionSettings(enabled=True), mode_explicit=False, model_explicit=False)
    inherited.add_member()
    await inherited.session.start(run_loop=False)
    assert inherited.session.settings.mode == "passive" and inherited.session.settings.model_id == "stored-model"
    explicit = make_session(settings=CompanionSettings(enabled=True, mode="active", model_id="chosen"), mode_explicit=True, model_explicit=True)
    explicit.add_member()
    await explicit.session.start(run_loop=False)
    assert explicit.session.settings.mode == "active" and explicit.session.settings.model_id == "chosen"


@pytest.mark.asyncio
async def test_tick_flushes_events_to_the_anchor_directory(make_session, tmp_path):
    harness = make_session()
    await harness.session.start(run_loop=False)
    harness.add_member()
    harness.say(QUESTION, 1.0, 4.0)
    await harness.settle()
    harness.clock.advance(3.0)
    await harness.session.tick()
    stored = CompanionStore(tmp_path / "mic1").load()
    assert stored is not None and any(event.kind == "item" for event in stored.events)


@pytest.mark.asyncio
async def test_two_members_share_one_timeline_clock(make_session):
    harness = make_session()
    await harness.session.start(run_loop=False)
    harness.add_member("mic1", start_epoch=1000.0)
    harness.add_member("sys1", role="other", speaker="Zoom", start_epoch=1012.0)
    harness.say("How does the invoice export pick an owner?", 3.0, 6.0, meeting_id="sys1", speaker="Zoom")
    await harness.settle()
    item = harness.event_kinds("item")[0]
    assert item.meeting_time == pytest.approx(18.0)
    assert harness.session.meeting_ids() == ["mic1", "sys1"]


@pytest.mark.asyncio
async def test_listener_failure_and_broadcast_failure_do_not_break_the_session(make_session):
    harness = make_session()

    async def failing(message):
        raise RuntimeError("socket closed")

    harness.session._broadcast_fn = failing
    await harness.session.start(run_loop=False)
    harness.add_member()
    harness.say(QUESTION, 1.0, 4.0)
    await harness.settle()
    assert len(harness.event_kinds("item")) == 1


@pytest.mark.asyncio
async def test_item_records_the_time_from_decision_to_display(make_session):
    harness = make_session()
    harness.add_member()
    await harness.session.start(run_loop=False)
    harness.evaluator.advance_during = 4.0
    harness.say(QUESTION, 10.0, 14.0)
    await harness.settle()
    assert harness.event_kinds("item")[0].payload["item"]["latency_ms"] == 4000
