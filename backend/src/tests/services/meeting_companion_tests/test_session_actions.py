import asyncio

import pytest

from api.services.meeting_companion import session as session_module
from api.services.meeting_companion.chat import ChatResult
from api.services.meeting_companion.context_search import RootRejected
from api.services.meeting_companion.session import UNSET
from api.services.meeting_companion.store import CompanionStore
from api.services.meeting_companion.watches import WatchRejected

QUESTION = "How does the retry policy handle timeouts in billing?"


class FakeChat:
    def __init__(self, pieces=("The retry policy ", "caps at five attempts."), *, hang=False, error=None):
        self.requests = []
        self.pieces = pieces
        self.hang = hang
        self.error = error
        self.active = 0
        self.max_active = 0

    async def stream_answer(self, request, on_delta):
        self.requests.append(request)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            for piece in self.pieces:
                await on_delta(piece)
                await asyncio.sleep(0)
            if self.hang:
                await asyncio.Event().wait()
            if self.error:
                return ChatResult(error=self.error)
            return ChatResult(text="".join(self.pieces), deltas=list(self.pieces))
        finally:
            self.active -= 1


async def started(make_session, **kwargs):
    harness = make_session(**kwargs)
    harness.add_member()
    await harness.session.start(run_loop=False)
    return harness


@pytest.mark.asyncio
async def test_feedback_updates_derived_state_and_rejects_unknown_input(make_session):
    harness = await started(make_session)
    harness.say(QUESTION, 1.0, 4.0)
    await harness.settle()
    item_id = harness.session.snapshot("mic1").items[0].id
    assert harness.session.record_feedback(item_id, "pinned") is True
    assert harness.session.snapshot("mic1").items[0].pinned is True
    assert harness.session.record_feedback(item_id, "dismissed") is True
    item = harness.session.snapshot("mic1").items[0]
    assert item.dismissed is True and item.pinned is False
    assert harness.session.record_feedback("missing", "pinned") is False
    with pytest.raises(ValueError):
        harness.session.record_feedback(item_id, "exploded")


@pytest.mark.asyncio
async def test_settings_changes_record_one_status_event_each_and_noops_record_none(make_session):
    harness = await started(make_session)
    before = len(harness.event_kinds("status"))
    harness.session.update_settings()
    harness.session.update_settings(mode="active")
    harness.session.update_settings(model_id=None)
    assert len(harness.event_kinds("status")) == before
    harness.session.update_settings(mode="passive")
    harness.session.update_settings(model_id="model-a")
    statuses = harness.event_kinds("status")
    assert len(statuses) == before + 2
    assert statuses[-1].payload["mode"] == "passive" and statuses[-1].payload["model_id"] == "model-a"
    harness.session.update_settings(model_id=None)
    assert harness.session.settings.model_id is None and len(harness.event_kinds("status")) == before + 3
    assert harness.session.update_settings(model_id=UNSET).model_id is None
    await harness.session.wait_idle()


@pytest.mark.asyncio
async def test_passive_mode_answers_questions_but_ignores_statements(make_session):
    harness = await started(make_session)
    harness.session.update_settings(mode="passive")
    for index, text in enumerate(["We should review the billing migration plan carefully.", "The invoice export still needs a second owner.", "Latency numbers look better after the cache change."]):
        harness.say(text, index * 5.0, index * 5.0 + 4.0)
    harness.clock.advance(50.0)
    await harness.settle()
    assert harness.evaluator.requests == []
    harness.say("How does the invoice export pick an owner?", 20.0, 24.0)
    await harness.settle()
    assert [request.trigger for request in harness.evaluator.requests] == ["question"]


@pytest.mark.asyncio
async def test_watch_fires_on_matching_line_records_trigger_and_respects_cooldown(make_session):
    harness = await started(make_session)
    watch = harness.session.create_watch("billing", "show me the endpoint")
    assert watch.keywords == ["billing"] and watch.active is True
    harness.say("The billing endpoint is slow today.", 1.0, 4.0)
    await harness.settle()
    assert [request.trigger for request in harness.evaluator.requests] == ["watch"]
    assert harness.evaluator.requests[0].watch.id == watch.id
    triggered = [event for event in harness.event_kinds("watch") if event.payload["state"] == "triggered"]
    assert len(triggered) == 1 and harness.session.snapshot("mic1").watches[0].last_triggered_at is not None
    assert harness.event_kinds("item")[0].payload["item"]["trigger"] == "watch"
    harness.clock.advance(11.0)
    harness.say("Billing numbers are still rising quickly.", 20.0, 23.0)
    await harness.settle()
    assert len(harness.evaluator.requests) == 1


@pytest.mark.asyncio
async def test_canceled_watch_never_fires_and_cancel_is_idempotent(make_session):
    harness = await started(make_session)
    watch = harness.session.create_watch("billing", "show me the endpoint")
    assert harness.session.cancel_watch(watch.id) is True
    assert harness.session.cancel_watch(watch.id) is False
    assert harness.session.cancel_watch("missing") is False
    harness.say("The billing endpoint is slow today.", 1.0, 4.0)
    await harness.settle()
    assert harness.evaluator.requests == []
    assert harness.session.snapshot("mic1").watches[0].active is False


@pytest.mark.asyncio
async def test_watch_limit_and_validation(make_session):
    harness = await started(make_session)
    for topic in ("ledger", "invoice", "payroll", "refund", "tariff", "escrow", "audit", "budget"):
        harness.session.create_watch(topic, "show me the owner")
    with pytest.raises(WatchRejected, match="at most 8"):
        harness.session.create_watch("shipping", "show me the owner")
    first = harness.session.snapshot("mic1").watches[0]
    harness.session.cancel_watch(first.id)
    assert harness.session.create_watch("shipping", "show me the owner").topic == "shipping"
    with pytest.raises(WatchRejected):
        harness.session.create_watch("ok", "x")


@pytest.mark.asyncio
async def test_roots_attach_dedupe_limit_and_detach(make_session, project, tmp_path):
    harness = await started(make_session)
    root = harness.session.attach_root(str(project))
    assert root.kind == "folder" and root.display_name == "proj" and harness.context.has_roots() is True
    assert harness.session.attach_root(str(project)).id == root.id
    assert len(harness.session.snapshot("mic1").roots) == 1
    for index in range(4):
        folder = tmp_path / f"extra{index}"
        folder.mkdir()
        harness.session.attach_root(str(folder))
    extra = tmp_path / "extra-over"
    extra.mkdir()
    with pytest.raises(RootRejected, match="At most 5"):
        harness.session.attach_root(str(extra))
    with pytest.raises(RootRejected, match="absolute"):
        harness.session.attach_root("relative/path")
    with pytest.raises(RootRejected, match="does not exist"):
        harness.session.attach_root(str(tmp_path / "missing"))
    assert harness.session.detach_root(root.id) is True
    assert harness.session.detach_root(root.id) is False
    assert root.id not in [candidate.id for candidate in harness.session.snapshot("mic1").roots]
    await harness.session.wait_idle()


@pytest.mark.asyncio
async def test_chat_streams_deltas_persists_both_messages_and_keeps_history(make_session):
    chat = FakeChat()
    harness = await started(make_session, chat_service=chat)
    harness.say("We are talking about the billing retries.", 1.0, 4.0)
    first_id = harness.session.submit_chat("What is the retry limit?")
    await harness.session.wait_idle()
    deltas = [message for message in harness.broadcasts if message["event_type"] == "meeting_companion_chat_delta"]
    assert [message["text_delta"] for message in deltas] == ["The retry policy ", "caps at five attempts."]
    assert all(message["done"] is False and message["truncated"] is False for message in deltas)
    assert all(message["message_id"] == first_id for message in deltas)
    messages = harness.session.snapshot("mic1").chat
    assert [(message.role, message.text) for message in messages] == [
        ("user", "What is the retry limit?"),
        ("assistant", "The retry policy caps at five attempts."),
    ]
    assert messages[1].id == first_id and messages[1].status == "complete"
    assert chat.requests[0].history == [] and chat.requests[0].has_roots is False
    assert any("billing retries" in turn.text for turn in chat.requests[0].window_turns)
    harness.session.submit_chat("And the backoff?")
    await harness.session.wait_idle()
    assert [message.text for message in chat.requests[1].history] == ["What is the retry limit?", "The retry policy caps at five attempts."]


@pytest.mark.asyncio
async def test_chat_requests_are_serialized(make_session):
    chat = FakeChat()
    harness = await started(make_session, chat_service=chat)
    harness.session.submit_chat("First question about billing?")
    harness.session.submit_chat("Second question about invoices?")
    await harness.session.wait_idle()
    assert chat.max_active == 1 and len(chat.requests) == 2
    assert [message.role for message in harness.session.snapshot("mic1").chat] == ["user", "user", "assistant", "assistant"]


@pytest.mark.asyncio
async def test_chat_error_is_persisted_as_an_error_message(make_session):
    chat = FakeChat(pieces=(), error="model_unavailable: no key")
    harness = await started(make_session, chat_service=chat)
    harness.session.submit_chat("What is the retry limit?")
    await harness.session.wait_idle()
    reply = harness.session.snapshot("mic1").chat[-1]
    assert reply.role == "assistant" and reply.status == "error" and reply.text == "I couldn't answer that right now."


@pytest.mark.asyncio
async def test_chat_message_that_parses_as_a_watch_creates_one_and_does_not_call_the_model(make_session):
    chat = FakeChat()
    harness = await started(make_session, chat_service=chat)
    harness.session.submit_chat("when billing comes up, show me the endpoint")
    await harness.session.wait_idle()
    assert chat.requests == []
    snapshot = harness.session.snapshot("mic1")
    assert [watch.topic for watch in snapshot.watches] == ["billing"]
    assert snapshot.chat[-1].status == "complete" and "billing" in snapshot.chat[-1].text


@pytest.mark.asyncio
async def test_chat_validation_and_closed_session(make_session):
    harness = await started(make_session, chat_service=FakeChat())
    with pytest.raises(ValueError):
        harness.session.submit_chat("   ")
    with pytest.raises(ValueError):
        harness.session.submit_chat("x" * 4001)
    await harness.session.close()
    with pytest.raises(RuntimeError):
        harness.session.submit_chat("Hello?")


@pytest.mark.asyncio
async def test_chat_with_attached_context_passes_the_pack_and_logs_retrieval(make_session, project, attach_project):
    chat = FakeChat()
    harness = await started(make_session, chat_service=chat)
    attach_project(harness.context, project)
    await harness.context.rebuild_vocabulary()
    harness.session.submit_chat("how does the retry policy handle timeouts")
    await harness.session.wait_idle()
    request = chat.requests[0]
    assert request.has_roots is True and request.pack is not None and request.pack.hit_count >= 1
    assert "chat" in [event.payload["purpose"] for event in harness.event_kinds("retrieval")]


@pytest.mark.asyncio
async def test_remove_member_flushes_its_partial_utterance_and_moves_the_anchor(make_session):
    harness = await started(make_session)
    harness.add_member("sys1", role="other", speaker="Zoom", start_epoch=1000.0)
    harness.say("We should look at the invoice", 1.0, 3.0, meeting_id="sys1", speaker="Zoom")
    assert harness.session.pending_line_count() == 0
    assert harness.session.remove_member("sys1") == 1
    assert harness.session.pending_line_count() == 1
    assert harness.session.has_member("sys1") is False and harness.session.meeting_ids() == ["mic1", "sys1"]
    assert harness.session.remove_member("mic1") == 0


@pytest.mark.asyncio
async def test_close_persists_final_status_flushes_and_is_idempotent(make_session, tmp_path):
    harness = await started(make_session)
    harness.say(QUESTION, 1.0, 4.0)
    await harness.settle()
    await harness.session.close()
    assert harness.session.status().live is False
    stored = CompanionStore(tmp_path / "mic1").load()
    assert stored is not None and stored.events[-1].kind == "status" and any(event.kind == "item" for event in stored.events)
    assert harness.broadcasts[-1]["event_type"] == "meeting_companion_status" and harness.broadcasts[-1]["live"] is False
    count = len(harness.session.events())
    await harness.session.close()
    assert len(harness.session.events()) == count


@pytest.mark.asyncio
async def test_close_with_final_enabled_false_marks_the_companion_off(make_session, tmp_path):
    harness = await started(make_session)
    await harness.session.close(final_enabled=False)
    stored = CompanionStore(tmp_path / "mic1").load()
    assert stored.settings.enabled is False and stored.events[-1].payload["enabled"] is False
    assert harness.session.status().enabled is False


@pytest.mark.asyncio
async def test_close_with_discard_writes_nothing(make_session, tmp_path):
    harness = await started(make_session)
    harness.say(QUESTION, 1.0, 4.0)
    await harness.session.close(discard=True)
    assert not (tmp_path / "mic1" / "companion.json").exists()
    assert harness.broadcasts[-1]["live"] is False


@pytest.mark.asyncio
async def test_close_cancels_an_in_flight_evaluation_quietly(make_session):
    harness = make_session()
    harness.evaluator.release = asyncio.Event()
    harness.add_member()
    await harness.session.start(run_loop=False)
    harness.say(QUESTION, 1.0, 4.0)
    await harness.session.tick()
    await asyncio.sleep(0)
    assert harness.session.status().evaluating is True
    await harness.session.close()
    assert harness.session.status().evaluating is False
    assert harness.event_kinds("item") == [] and harness.event_kinds("error") == []


@pytest.mark.asyncio
async def test_close_lets_a_pending_chat_answer_finish(make_session):
    chat = FakeChat()
    harness = await started(make_session, chat_service=chat)
    harness.session.submit_chat("What is the retry limit?")
    await harness.session.close()
    reply = [message for message in harness.session.snapshot("mic1").chat if message.role == "assistant"][0]
    assert reply.text == "The retry policy caps at five attempts." and reply.truncated is False


@pytest.mark.asyncio
async def test_close_persists_partial_text_when_a_chat_outlives_the_grace_period(make_session, monkeypatch, tmp_path):
    monkeypatch.setattr(session_module, "CHAT_CLOSE_GRACE_SECONDS", 0.05)
    chat = FakeChat(hang=True)
    harness = await started(make_session, chat_service=chat)
    harness.session.submit_chat("What is the retry limit?")
    await asyncio.sleep(0.02)
    await harness.session.close()
    reply = [message for message in harness.session.snapshot("mic1").chat if message.role == "assistant"][0]
    assert reply.text == "The retry policy caps at five attempts." and reply.truncated is True and reply.status == "complete"
    stored = CompanionStore(tmp_path / "mic1").load()
    assert any(event.kind == "chat" and event.payload.get("truncated") is True for event in stored.events)


@pytest.mark.asyncio
async def test_evaluation_crash_is_contained_and_recorded(make_session):
    harness = await started(make_session)
    harness.evaluator.raise_error = RuntimeError("boom")
    harness.say(QUESTION, 1.0, 4.0)
    await harness.settle()
    assert harness.session.status().evaluating is False
    errors = harness.event_kinds("error")
    assert len(errors) == 1 and errors[0].payload["message"] == "boom"
    harness.evaluator.raise_error = None
    harness.clock.advance(11.0)
    harness.say("What about the invoice export timeout?", 20.0, 23.0)
    await harness.settle()
    assert len(harness.evaluator.requests) == 2 and len(harness.event_kinds("item")) == 1
