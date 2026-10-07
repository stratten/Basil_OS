from __future__ import annotations

from types import SimpleNamespace

import pytest

import api.dependencies as dependencies_module
from api.services.agent_processing.lifecycle.finalization.task_state_persistence import (
    merge_thinking_histories,
    normalize_thinking_history,
)
from api.services.agent_processing.lifecycle.runtime.checkpoint_workflow_service import (
    USER_DISMISSED_CHECKPOINT_RESPONSE,
    checkpoint_interaction_status,
)
from api.services.agent_processing.lifecycle.runtime import user_interaction_timeline
from api.services.agent_processing.lifecycle.runtime.user_interaction_timeline import (
    USER_INTERACTION_DETAIL_KIND,
    build_user_interaction_entry,
    checkpoint_interaction_kind,
    record_user_interaction_asked,
    record_user_interaction_resolved,
    resolve_all_waiting_user_interactions,
    resolve_latest_waiting_user_interaction,
    user_interaction_entry_id,
)


@pytest.fixture(autouse=True)
def _clear_announced_requests():
    user_interaction_timeline._pending_asked.clear()
    yield
    user_interaction_timeline._pending_asked.clear()


class _Mutations:
    def __init__(self, store: "_KnowledgeService") -> None:
        self._store = store

    async def update_execution_timeline(self, agent_task_id, timeline):
        self._store.records[agent_task_id].execution_timeline = list(timeline)


class _KnowledgeService:
    def __init__(self, timeline=None) -> None:
        self.records = {"task-1": SimpleNamespace(execution_timeline=list(timeline or []))}
        self.agent_task_service = SimpleNamespace(_mutations=_Mutations(self))

    async def get_agent_task(self, agent_task_id):
        return self.records.get(agent_task_id)

    def timeline(self):
        return self.records["task-1"].execution_timeline


class _Broadcasts:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, event: dict) -> None:
        self.events.append(event)


@pytest.fixture
def knowledge(monkeypatch):
    service = _KnowledgeService(
        [
            {"id": "before", "type": "step", "content": "Searching"},
            {"id": "after", "type": "step", "content": "Reading"},
        ]
    )
    monkeypatch.setattr(dependencies_module, "get_sqlite_knowledge_service", lambda: service)
    return service


def _interaction(entry):
    return entry["metadata"]["user_interaction"]


def test_entry_carries_the_exchange_in_metadata_and_no_phase():
    entry = build_user_interaction_entry(
        interaction_id="cp-1",
        kind="clarification",
        prompt="Which hotel did you mean?",
        input_type="choice",
        options=["La Fantaisie", "", "Le Fantome"],
    )

    assert entry["id"] == user_interaction_entry_id("cp-1")
    assert entry["detail_kind"] == USER_INTERACTION_DETAIL_KIND
    assert entry["title"] == "Basil asked you a question"
    assert "phase" not in entry
    assert "progress_phase" not in entry["metadata"]
    assert _interaction(entry) == {
        "interaction_id": "cp-1",
        "kind": "clarification",
        "status": "waiting",
        "prompt": "Which hotel did you mean?",
        "asked_at": entry["timestamp"],
        "input_type": "choice",
        "options": ["La Fantaisie", "Le Fantome"],
    }


def test_entry_rejects_unknown_kind_and_status():
    with pytest.raises(ValueError):
        build_user_interaction_entry(interaction_id="x", kind="chat", prompt="Hi")
    with pytest.raises(ValueError):
        build_user_interaction_entry(interaction_id="x", kind="approval", prompt="Hi", status="maybe")


def test_hidden_response_never_stores_the_text():
    entry = build_user_interaction_entry(
        interaction_id="input-1",
        kind="command_input",
        prompt="Password:",
        status="answered",
        response="hunter2",
        response_hidden=True,
    )

    assert _interaction(entry)["response_hidden"] is True
    assert "response" not in _interaction(entry)
    assert "hunter2" not in repr(entry)


@pytest.mark.asyncio
async def test_ask_then_answer_updates_one_entry_in_its_original_position(knowledge):
    broadcasts = _Broadcasts()
    await record_user_interaction_asked(
        "task-1",
        interaction_id="cp-1",
        kind="clarification",
        prompt="Which hotel?",
        broadcast=broadcasts,
    )
    knowledge.timeline().append({"id": "later", "type": "step", "content": "Searching shops"})

    await record_user_interaction_resolved(
        "task-1",
        interaction_id="cp-1",
        status="answered",
        response="La Fantaisie in the 9th",
        broadcast=broadcasts,
    )

    ids = [entry["id"] for entry in knowledge.timeline()]
    assert ids == ["before", "after", user_interaction_entry_id("cp-1"), "later"]
    resolved = _interaction(knowledge.timeline()[2])
    assert resolved["status"] == "answered"
    assert resolved["response"] == "La Fantaisie in the 9th"
    assert resolved["prompt"] == "Which hotel?"
    assert resolved["responded_at"] >= resolved["asked_at"]
    assert [event["event_type"] for event in broadcasts.events] == ["agent_task_step_detail"] * 2
    assert broadcasts.events[0]["agent_task_id"] == "task-1"
    assert _interaction(broadcasts.events[1]["timeline_entry"])["status"] == "answered"


@pytest.mark.asyncio
async def test_resolving_an_unrecorded_request_is_a_no_op(knowledge):
    broadcasts = _Broadcasts()
    await record_user_interaction_resolved(
        "task-1", interaction_id="missing", status="approved", broadcast=broadcasts
    )

    assert [entry["id"] for entry in knowledge.timeline()] == ["before", "after"]
    assert broadcasts.events == []


@pytest.mark.asyncio
async def test_answer_still_reaches_the_ui_when_another_writer_dropped_the_waiting_entry(knowledge):
    broadcasts = _Broadcasts()
    await record_user_interaction_asked(
        "task-1",
        interaction_id="cred-1",
        kind="credential",
        prompt="Keychain access required",
        broadcast=broadcasts,
    )
    asked_at = _interaction(knowledge.timeline()[-1])["asked_at"]
    knowledge.records["task-1"].execution_timeline = [
        entry for entry in knowledge.timeline() if entry.get("detail_kind") != USER_INTERACTION_DETAIL_KIND
    ]

    await record_user_interaction_resolved(
        "task-1", interaction_id="cred-1", status="approved", broadcast=broadcasts
    )

    resolved = _interaction(knowledge.timeline()[-1])
    assert (resolved["kind"], resolved["status"], resolved["prompt"], resolved["asked_at"]) == (
        "credential",
        "approved",
        "Keychain access required",
        asked_at,
    )
    assert _interaction(broadcasts.events[-1]["timeline_entry"])["status"] == "approved"
    assert len(broadcasts.events) == 2


@pytest.mark.asyncio
async def test_a_resolved_request_is_not_resolved_again_from_memory(knowledge):
    broadcasts = _Broadcasts()
    await record_user_interaction_asked("task-1", interaction_id="cp-1", kind="clarification", prompt="Q")
    await record_user_interaction_resolved(
        "task-1", interaction_id="cp-1", status="answered", response="A", broadcast=broadcasts
    )

    assert await resolve_all_waiting_user_interactions("task-1", broadcast=broadcasts) == 0
    await resolve_latest_waiting_user_interaction(
        "task-1", kinds=("clarification",), status="dismissed", broadcast=broadcasts
    )

    assert _interaction(knowledge.timeline()[-1])["status"] == "answered"
    assert len(broadcasts.events) == 1


@pytest.mark.asyncio
async def test_cancel_and_resume_also_close_requests_whose_saved_entry_was_dropped(knowledge):
    for interaction_id in ("cp-1", "cp-2"):
        await record_user_interaction_asked(
            "task-1", interaction_id=interaction_id, kind="clarification", prompt=f"Question {interaction_id}"
        )
    knowledge.records["task-1"].execution_timeline = [
        entry for entry in knowledge.timeline() if entry.get("detail_kind") != USER_INTERACTION_DETAIL_KIND
    ]

    await resolve_latest_waiting_user_interaction(
        "task-1", kinds=("clarification",), status="answered", response="Yes"
    )
    assert await resolve_all_waiting_user_interactions("task-1") == 1

    statuses = {
        _interaction(entry)["interaction_id"]: _interaction(entry)["status"]
        for entry in knowledge.timeline()
        if entry.get("detail_kind") == USER_INTERACTION_DETAIL_KIND
    }
    assert statuses == {"cp-2": "answered", "cp-1": "canceled"}


@pytest.mark.asyncio
async def test_resume_resolves_only_the_newest_waiting_checkpoint(knowledge):
    for interaction_id, kind in (("cp-1", "clarification"), ("ap-1", "approval"), ("cp-2", "clarification")):
        await record_user_interaction_asked(
            "task-1", interaction_id=interaction_id, kind=kind, prompt=f"Question {interaction_id}"
        )

    await resolve_latest_waiting_user_interaction(
        "task-1",
        kinds=("clarification", "provider_target"),
        status="dismissed",
    )

    statuses = {
        _interaction(entry)["interaction_id"]: _interaction(entry)["status"]
        for entry in knowledge.timeline()
        if entry.get("detail_kind") == USER_INTERACTION_DETAIL_KIND
    }
    assert statuses == {"cp-1": "waiting", "ap-1": "waiting", "cp-2": "dismissed"}


@pytest.mark.asyncio
async def test_persistence_failures_never_raise(monkeypatch):
    def broken():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(dependencies_module, "get_sqlite_knowledge_service", broken)

    await record_user_interaction_asked("task-1", interaction_id="cp-1", kind="clarification", prompt="Q")
    await record_user_interaction_resolved("task-1", interaction_id="cp-1", status="answered")
    await resolve_latest_waiting_user_interaction("task-1", kinds=("clarification",), status="answered")


def test_checkpoint_kind_and_status_mapping():
    assert checkpoint_interaction_kind({"metadata": {"source": "provider_target_authorization"}}) == "provider_target"
    assert checkpoint_interaction_kind({"metadata": None}) == "clarification"
    assert checkpoint_interaction_status(USER_DISMISSED_CHECKPOINT_RESPONSE, None) == "dismissed"
    assert checkpoint_interaction_status("Yes", None) == "answered"
    assert checkpoint_interaction_status("Yes", {"status": "authorized"}) == "approved"
    assert checkpoint_interaction_status("No", {"status": "rejected"}) == "denied"
    assert checkpoint_interaction_status("", {"status": "canceled"}) == "canceled"
    assert checkpoint_interaction_status("Which one?", {"status": "clarification_received"}) == "answered"


def test_thinking_history_keeps_recorded_at_and_merges_across_a_pause():
    prior = [
        {"iteration": 1, "text": "Looking up the hotel", "is_complete": True, "recorded_at": "2026-10-04T23:39:00+00:00"},
        {"iteration": 2, "text": "Hotel is ambiguous", "is_complete": True},
    ]
    current = [
        {"iteration": 1, "text": "Searching shops near La Fantaisie", "is_complete": True, "recorded_at": "2026-10-04T23:45:00+00:00"},
        {"iteration": 3, "text": "Narrowing to cat shirts", "is_complete": True},
    ]

    merged = merge_thinking_histories(prior, current)

    assert [(segment["iteration"], segment["text"]) for segment in merged] == [
        (1, "Looking up the hotel"),
        (2, "Hotel is ambiguous"),
        (3, "Searching shops near La Fantaisie"),
        (5, "Narrowing to cat shirts"),
    ]
    assert merged[0]["recorded_at"] == "2026-10-04T23:39:00+00:00"
    assert "recorded_at" not in merged[1]
    assert merge_thinking_histories(None, current) == normalize_thinking_history(current)
    assert merge_thinking_histories(prior, None) == normalize_thinking_history(prior)
