import json
from pathlib import Path

from api.services.meeting_companion.models import TimelineEvent
from api.services.meeting_companion.timeline import build_snapshot, reduce_timeline, stored_status
from api.services.meeting_companion.models import CompanionSettings

FIXTURE = Path(__file__).parent / "fixtures" / "timeline_parity.json"


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def comparable(derived):
    return {
        "items": [
            {"id": item.id, "text": item.text, "pinned": item.pinned, "dismissed": item.dismissed, "watch_id": item.watch_id, "seq": item.seq}
            for item in derived.items
        ],
        "watches": [
            {"id": watch.id, "active": watch.active, "last_triggered_at": watch.last_triggered_at} for watch in derived.watches
        ],
        "root_ids": [root.id for root in derived.roots],
        "chat": [
            {"id": message.id, "role": message.role, "text": message.text, "status": message.status, "truncated": message.truncated, "seq": message.seq}
            for message in derived.chat
        ],
        "retrieval_count": len(derived.retrievals),
        "status": derived.status,
        "last_error": derived.last_error,
        "last_seq": derived.last_seq,
    }


def test_fixture_reduces_to_expected_state():
    fixture = load_fixture()
    events = [TimelineEvent.model_validate(raw) for raw in fixture["events"]]
    assert comparable(reduce_timeline(events)) == fixture["expected"]


def test_reducer_is_idempotent_for_replayed_events():
    fixture = load_fixture()
    events = [TimelineEvent.model_validate(raw) for raw in fixture["events"]]
    replayed = comparable(reduce_timeline(events + events))
    once = comparable(reduce_timeline(events))
    replayed.pop("retrieval_count")
    once.pop("retrieval_count")
    assert replayed == once


def test_empty_timeline_is_empty_state():
    derived = reduce_timeline([])
    assert derived.items == [] and derived.last_seq == 0 and derived.status is None


def test_dismiss_then_pin_leaves_pinned_only():
    fixture = load_fixture()
    events = [TimelineEvent.model_validate(raw) for raw in fixture["events"][:4]]
    extra = [
        TimelineEvent(id="x1", seq=5, kind="feedback", meeting_time=30, wall_time="w", payload={"item_id": "i1", "action": "dismissed"}),
        TimelineEvent(id="x2", seq=6, kind="feedback", meeting_time=31, wall_time="w", payload={"item_id": "i1", "action": "pinned"}),
    ]
    item = reduce_timeline(events + extra).items[0]
    assert item.pinned is True and item.dismissed is False


def test_error_event_is_surfaced_as_last_error():
    events = [TimelineEvent(id="e", seq=1, kind="error", meeting_time=1, wall_time="w", payload={"code": "model_failed", "message": "boom"})]
    assert reduce_timeline(events).last_error == {"code": "model_failed", "message": "boom"}


def test_stored_status_and_snapshot_for_a_meeting_that_is_not_live():
    fixture = load_fixture()
    events = [TimelineEvent.model_validate(raw) for raw in fixture["events"]]
    derived = reduce_timeline(events)
    status = stored_status(derived, CompanionSettings(enabled=True, mode="passive", model_id="m"))
    assert status.live is False and status.capacity == "ok" and status.mode == "active"
    snapshot = build_snapshot(meeting_id="m1", session_key="s1", status=status, derived=derived)
    assert snapshot.last_seq == 18 and len(snapshot.items) == 3


def _item_payload(item_id: str, seq_in_payload: int = 0) -> dict:
    return {
        "item": {
            "id": item_id,
            "kind": "insight",
            "text": f"text {item_id}",
            "confidence": 0.5,
            "transcript_range": {"start": 1.0, "end": 2.0, "turn_ids": []},
            "trigger": "periodic",
            "seq": seq_in_payload,
        }
    }


def _event(seq: int, kind: str, payload: dict) -> TimelineEvent:
    return TimelineEvent(id=f"e{seq}", seq=seq, kind=kind, meeting_time=float(seq), wall_time="2026-01-01T00:00:00.000000Z", payload=payload)


def test_items_and_chat_carry_the_seq_of_the_event_that_created_them():
    derived = reduce_timeline(
        [
            _event(4, "item", _item_payload("i1", seq_in_payload=99)),
            _event(5, "chat", {"message_id": "m1", "role": "user", "text": "hi"}),
            _event(6, "chat", {"message_id": "m1", "role": "user", "text": "hi again"}),
            _event(7, "item", _item_payload("i2")),
        ]
    )
    assert [(item.id, item.seq) for item in derived.items] == [("i1", 4), ("i2", 7)]
    assert [(message.id, message.seq, message.text) for message in derived.chat] == [("m1", 5, "hi again")]


def test_restored_feedback_clears_dismissal_and_ignores_unknown_items():
    derived = reduce_timeline(
        [
            _event(1, "item", _item_payload("i1")),
            _event(2, "feedback", {"item_id": "i1", "action": "dismissed"}),
            _event(3, "feedback", {"item_id": "i1", "action": "restored"}),
            _event(4, "feedback", {"item_id": "missing", "action": "restored"}),
        ]
    )
    assert derived.items[0].dismissed is False
    assert derived.items[0].pinned is False


def test_items_saved_before_seq_existed_still_load_and_get_their_event_seq():
    payload = _item_payload("i1")
    payload["item"].pop("seq")
    derived = reduce_timeline([_event(9, "item", payload)])
    assert derived.items[0].seq == 9
    assert derived.items[0].reply_to_message_id is None
