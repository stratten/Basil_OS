import pytest

from api.services.meeting_companion.evaluation_ledger import (
    DROP_CONFIDENCE_FLOOR,
    DROP_DUPLICATE,
    DROP_EMPTY,
    DROP_OVER_CAP,
    KEPT,
    CandidateRecord,
    GateWaitCounter,
    build_evaluation_payload,
    clean_considered,
)
from api.services.meeting_companion.evaluator import CompanionEvaluationResponse, materialize_items
from api.services.meeting_companion.evaluator import EvaluatedItem
from api.services.meeting_companion.evaluator import EvaluationOutcome
from api.services.meeting_companion.models import CompanionSettings, TimelineEvent
from api.services.meeting_companion.timeline import MAX_DERIVED_EVALUATIONS, build_snapshot, reduce_timeline, stored_status
from api.services.meeting_companion.models import CompanionSnapshot

from .test_evaluator import counter_ids, item, make_request

QUESTION = "How does the retry policy handle timeouts in billing?"


def test_every_candidate_gets_a_kept_or_drop_reason():
    already = ["The retry policy caps backoff at thirty seconds."]
    response = CompanionEvaluationResponse(
        considered="Weighed a duplicate, a weak note and two good ones.",
        items=[
            item("The retry policy caps its backoff at thirty seconds.", kind="insight"),
            item("   ", kind="insight"),
            item("Weak guess about something unrelated to anything.", kind="insight", confidence=0.2),
            item("Timeouts are configured per upstream service.", kind="insight"),
            item("Retries are logged with a correlation identifier.", kind="insight"),
            item("A third distinct note about deployment windows.", kind="insight"),
        ],
    )
    records = []
    items, dropped = materialize_items(
        response, make_request(trigger="periodic", already_shown=already), id_factory=counter_ids(), records=records
    )
    assert [record.outcome for record in records] == [DROP_DUPLICATE, DROP_EMPTY, DROP_CONFIDENCE_FLOOR, KEPT, KEPT, DROP_OVER_CAP]
    assert dropped == 4 and len(items) == 2
    assert all(entry.rationale == "Weighed a duplicate, a weak note and two good ones." for entry in items)


def test_records_are_optional():
    response = CompanionEvaluationResponse(items=[item("Timeouts are configured per upstream service.", kind="insight")])
    items, dropped = materialize_items(response, make_request(), id_factory=counter_ids())
    assert len(items) == 1 and dropped == 0 and items[0].rationale == ""


def test_considered_is_single_spaced_capped_and_defaults_to_empty():
    assert clean_considered("  one\n\n two   three ") == "one two three"
    assert len(clean_considered("x" * 500)) == 200
    assert clean_considered(None) == ""
    assert CompanionEvaluationResponse().considered == ""


def test_gate_waits_count_reasons_ignore_idle_and_reset_when_taken():
    counter = GateWaitCounter()
    for reason in ("idle", "few lines", "few lines", "pacing", ""):
        counter.note(reason)
    assert counter.take() == {"few lines": 2, "pacing": 1}
    assert counter.take() == {}


def test_payload_truncates_candidates_and_error():
    candidates = [CandidateRecord("insight", "word " * 100, 0.55555, KEPT) for _ in range(9)]
    payload = build_evaluation_payload(
        trigger="periodic",
        new_lines=4,
        considered="Because.",
        candidates=candidates,
        kept=0,
        latency_ms=812,
        finish_reason="stop",
        model_id=None,
        error="e" * 900,
        gate_waits={"waiting": 3},
    )
    assert len(payload["candidates"]) == 6
    assert len(payload["candidates"][0]["text"]) == 160 and payload["candidates"][0]["confidence"] == 0.556
    assert len(payload["error"]) == 300 and payload["discarded"] is None
    assert build_evaluation_payload(
        trigger="x", new_lines=0, considered="", candidates=[], kept=0, latency_ms=0, finish_reason=None, model_id=None, error=None, gate_waits={}
    )["error"] is None


def evaluation_event(seq, **payload):
    return TimelineEvent(id=f"ev-{seq}", seq=seq, kind="evaluation", meeting_time=float(seq), wall_time="2026-01-01T00:00:00Z", payload=payload)


def test_reducer_collects_evaluations_and_counts_past_the_cap():
    events = [evaluation_event(index, trigger="periodic", considered="c") for index in range(1, MAX_DERIVED_EVALUATIONS + 6)]
    derived = reduce_timeline(events)
    assert derived.evaluation_total == MAX_DERIVED_EVALUATIONS + 5
    assert len(derived.evaluations) == MAX_DERIVED_EVALUATIONS
    assert derived.evaluations[-1].seq == MAX_DERIVED_EVALUATIONS + 5
    snapshot = build_snapshot(meeting_id="m", session_key="s", status=stored_status(derived, CompanionSettings()), derived=derived)
    assert snapshot.evaluation_total == derived.evaluation_total and len(snapshot.evaluations) == MAX_DERIVED_EVALUATIONS


def test_snapshot_from_a_file_without_the_new_fields_still_loads():
    legacy = {
        "meeting_id": "m",
        "session_key": "s",
        "status": {"live": False},
    }
    snapshot = CompanionSnapshot.model_validate(legacy)
    assert snapshot.evaluations == [] and snapshot.evaluation_total == 0


@pytest.mark.asyncio
async def test_a_silent_evaluation_still_writes_a_ledger_event(make_session):
    harness = make_session()
    harness.evaluator.override = EvaluationOutcome(
        items=[],
        conversation_state="Scheduling chat.",
        considered="Small talk about scheduling, nothing to add.",
        candidates=[CandidateRecord("insight", "Weak idea.", 0.3, DROP_CONFIDENCE_FLOOR)],
        latency_ms=420,
        finish_reason="stop",
    )
    await harness.session.start(run_loop=False)
    harness.add_member()
    harness.say("Hello team.", 1.0, 2.0)
    harness.say("Okay.", 2.0, 3.0)
    await harness.settle()
    harness.say(QUESTION, 10.0, 14.0)
    await harness.settle()
    events = harness.event_kinds("evaluation")
    assert len(events) == 1 and harness.event_kinds("item") == []
    payload = events[0].payload
    assert payload["trigger"] == "question" and payload["kept"] == 0
    assert payload["considered"] == "Small talk about scheduling, nothing to add."
    assert payload["candidates"][0]["outcome"] == DROP_CONFIDENCE_FLOOR
    assert payload["latency_ms"] == 420 and payload["discarded"] is None
    snapshot = harness.session.snapshot("mic1")
    assert snapshot.evaluation_total == 1 and snapshot.items == []


@pytest.mark.asyncio
async def test_gate_waits_since_the_previous_evaluation_are_carried_on_the_next_event(make_session):
    harness = make_session()
    await harness.session.start(run_loop=False)
    harness.add_member()
    harness.say("We should keep going with the plan.", 1.0, 3.0)
    harness.clock.advance(1.0)
    await harness.session.tick()
    harness.clock.advance(1.0)
    await harness.session.tick()
    harness.say(QUESTION, 10.0, 14.0)
    await harness.settle()
    payload = harness.event_kinds("evaluation")[0].payload
    assert payload["gate_waits"].get("few lines", 0) >= 2
    assert harness.event_kinds("item")[0].payload["item"]["rationale"] == ""


@pytest.mark.asyncio
async def test_an_error_outcome_is_recorded_in_the_ledger_with_its_error(make_session):
    harness = make_session()
    harness.evaluator.override = EvaluationOutcome(error="timeout", latency_ms=60000)
    await harness.session.start(run_loop=False)
    harness.add_member()
    harness.say(QUESTION, 1.0, 4.0)
    await harness.settle()
    payload = harness.event_kinds("evaluation")[0].payload
    assert payload["error"] == "timeout" and payload["kept"] == 0


@pytest.mark.asyncio
async def test_a_stale_result_is_ledgered_as_discarded(make_session):
    harness = make_session()
    harness.evaluator.advance_during = 200.0
    await harness.session.start(run_loop=False)
    harness.add_member()
    harness.say(QUESTION, 1.0, 4.0)
    await harness.settle()
    payload = harness.event_kinds("evaluation")[0].payload
    assert payload["discarded"] == "stale" and harness.event_kinds("item") == []


def test_evaluated_item_contract_is_unchanged():
    assert set(EvaluatedItem.model_fields) == {"kind", "text", "confidence", "pack_ids", "source_turn_ids"}


def test_the_prompt_asks_for_a_rationale_even_when_silent():
    from api.services.meeting_companion.evaluator import CompanionEvaluator

    prompt = CompanionEvaluator().build_prompt(make_request())
    assert "considered is one or two plain sentences" in prompt and "including when items is empty" in prompt
