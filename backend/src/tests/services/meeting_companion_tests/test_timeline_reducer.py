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
            {"id": item.id, "text": item.text, "pinned": item.pinned, "dismissed": item.dismissed, "watch_id": item.watch_id}
            for item in derived.items
        ],
        "watches": [
            {"id": watch.id, "active": watch.active, "last_triggered_at": watch.last_triggered_at} for watch in derived.watches
        ],
        "root_ids": [root.id for root in derived.roots],
        "chat": [
            {"id": message.id, "role": message.role, "text": message.text, "status": message.status, "truncated": message.truncated}
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
