import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from api.services.meeting_companion.models import CompanionGlobalSettings, CompanionItem, TimelineEvent, TranscriptRange
from api.services.meeting_companion.store import CompanionGlobalSettingsStore
from api.services.meeting_companion.timeline import reduce_timeline

FIXTURE = Path(__file__).parent / "fixtures" / "timeline_parity_proposals.json"


def comparable(derived):
    return {
        "items": [{"id": item.id, "kind": item.kind, "dismissed": item.dismissed} for item in derived.items],
        "proposals": [
            {
                "item_id": item.id,
                "state": item.proposal.state,
                "todo_id": item.proposal.todo_id,
                "agent_task_id": item.proposal.agent_task_id,
                "error": item.proposal.error,
                "auto_started": item.proposal.auto_started,
            }
            for item in derived.items
            if item.proposal is not None
        ],
        "last_seq": derived.last_seq,
    }


def test_proposal_fixture_reduces_to_expected_state():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    events = [TimelineEvent.model_validate(raw) for raw in fixture["events"]]
    assert comparable(reduce_timeline(events)) == fixture["expected"]


def proposal_item(item_id="i1", pinned=False):
    return {
        "id": item_id,
        "kind": "proposal",
        "text": "Add a reminder",
        "confidence": 0.9,
        "transcript_range": {"start": 1.0, "end": 2.0, "turn_ids": []},
        "trigger": "investigation",
        "pinned": pinned,
        "proposal": {"proposal_id": "pr-1", "action": "todo", "title": "Add a reminder", "instruction": "Add a reminder please"},
    }


def event(seq, kind, payload):
    return TimelineEvent(id=f"e{seq}", seq=seq, kind=kind, meeting_time=float(seq), wall_time="w", payload=payload)


def test_a_dismissed_proposal_is_hidden_and_unpinned():
    derived = reduce_timeline(
        [
            event(1, "item", {"item": proposal_item(pinned=True)}),
            event(2, "proposal", {"item_id": "i1", "proposal_id": "pr-1", "state": "dismissed"}),
        ]
    )
    item = derived.items[0]
    assert item.dismissed is True and item.pinned is False and item.proposal.state == "dismissed"


def test_a_failure_keeps_the_todo_and_a_later_start_clears_the_error():
    derived = reduce_timeline(
        [
            event(1, "item", {"item": proposal_item()}),
            event(2, "proposal", {"item_id": "i1", "proposal_id": "pr-1", "state": "failed", "todo_id": "t-1"}),
        ]
    )
    failed = derived.items[0].proposal
    assert failed.state == "failed" and failed.todo_id == "t-1" and failed.error == "The action could not be started."
    started = reduce_timeline(
        [
            event(1, "item", {"item": proposal_item()}),
            event(2, "proposal", {"item_id": "i1", "proposal_id": "pr-1", "state": "failed", "todo_id": "t-1", "error": "Worker busy."}),
            event(3, "proposal", {"item_id": "i1", "proposal_id": "pr-1", "state": "started", "todo_id": "t-1", "agent_task_id": "a-1"}),
        ]
    ).items[0].proposal
    assert started.state == "started" and started.error is None and started.agent_task_id == "a-1" and started.auto_started is False


def test_a_proposal_event_for_a_plain_item_or_a_missing_item_changes_nothing():
    plain = {"id": "i2", "kind": "answer", "text": "Plain.", "confidence": 0.9, "transcript_range": {"start": 1.0, "end": 2.0, "turn_ids": []}, "trigger": "question"}
    derived = reduce_timeline(
        [
            event(1, "item", {"item": plain}),
            event(2, "proposal", {"item_id": "i2", "proposal_id": "x", "state": "started"}),
            event(3, "proposal", {"item_id": "nope", "proposal_id": "x", "state": "started"}),
        ]
    )
    assert derived.items[0].proposal is None and derived.items[0].dismissed is False and derived.last_seq == 3


def test_items_without_a_proposal_keep_the_old_shape():
    item = CompanionItem(id="i1", kind="insight", text="Retries changed.", confidence=0.8, transcript_range=TranscriptRange(start=1.0, end=2.0, turn_ids=[]), trigger="periodic")
    assert item.proposal is None and item.model_dump(mode="json")["proposal"] is None


def test_global_settings_default_to_suggestions_only_and_reject_unsafe_capabilities():
    defaults = CompanionGlobalSettings()
    assert defaults.proposal_mode == "suggestion_only" and defaults.auto_execute_capabilities == []
    assert defaults.proposal_capabilities == ["todo", "agent_task", "assistant_session"]
    with pytest.raises(ValidationError):
        CompanionGlobalSettings(auto_execute_capabilities=["assistant_session"])
    with pytest.raises(ValidationError):
        CompanionGlobalSettings(proposal_mode="always")


def test_a_saved_settings_file_from_before_proposals_still_loads(tmp_path):
    path = tmp_path / "global.json"
    path.write_text(json.dumps({"auto_enable": True, "default_mode": "passive", "screen_share_note_dismissed": False, "next_focus": "budget"}), encoding="utf-8")
    loaded = CompanionGlobalSettingsStore(path).load()
    assert loaded.auto_enable is True and loaded.next_focus == "budget" and loaded.proposal_mode == "suggestion_only" and loaded.auto_execute_capabilities == []
