"""In-memory reconciliation session store: round-trip, single-active, decisions."""

import pytest

from api.services.skills.reconciliation.reconciliation_session import (
    DECISION_ACCEPTED,
    KIND_KEEP_NEW,
    STATUS_ANALYZING,
    ProposedAction,
    ReconciliationSessionStore,
    SessionSnapshot,
)


def _snapshot(pending=None, saved=None) -> SessionSnapshot:
    return SessionSnapshot(
        captured_at="2026-07-01T00:00:00+00:00",
        pending_candidates=pending or [],
        saved_skills=saved or [],
    )


def test_create_then_load_round_trip():
    store = ReconciliationSessionStore()
    session = store.create(_snapshot(pending=[{"id": "c1"}, {"id": "c2"}]))

    assert session.status == STATUS_ANALYZING
    assert session.progress["total"] == 2
    assert store.load() is session
    assert store.require() is session


def test_second_create_is_rejected_until_cleared():
    store = ReconciliationSessionStore()
    store.create(_snapshot())

    with pytest.raises(RuntimeError):
        store.create(_snapshot())

    # After clearing, a fresh session may start (mirrors "close then reopen").
    store.clear()
    assert store.load() is None
    store.create(_snapshot())
    assert store.load() is not None


def test_append_and_decide_action():
    store = ReconciliationSessionStore()
    store.create(_snapshot())
    action = ProposedAction(
        id="action-1",
        kind=KIND_KEEP_NEW,
        source_candidate_ids=["c1"],
        merged_title="Original",
        merged_when_to_use="original when",
    )
    store.append_action(action)

    updated = store.set_action_decision(
        "action-1",
        DECISION_ACCEPTED,
        user_edited={"title": "Edited Title"},
    )
    assert updated.decision == DECISION_ACCEPTED

    # effective_payload resolves the user's edit over the model's merged value.
    payload = updated.effective_payload()
    assert payload["title"] == "Edited Title"
    assert payload["when_to_use"] == "original when"


def test_decide_unknown_action_raises():
    store = ReconciliationSessionStore()
    store.create(_snapshot())
    with pytest.raises(ValueError):
        store.set_action_decision("nope", DECISION_ACCEPTED)


def test_decide_with_unsupported_decision_raises():
    store = ReconciliationSessionStore()
    store.create(_snapshot())
    store.append_action(ProposedAction(id="a1", kind=KIND_KEEP_NEW))
    with pytest.raises(ValueError):
        store.set_action_decision("a1", "maybe")
