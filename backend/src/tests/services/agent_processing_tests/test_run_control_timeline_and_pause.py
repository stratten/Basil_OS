from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import api.dependencies as dependencies_module
from api.services.agent_processing.lifecycle.execution_graph.agent_loop_run_control import (
    USER_PAUSE_PROMPT,
    UserPauseRequest,
)
from api.services.agent_processing.lifecycle.finalization.task_state_persistence import handle_checkpoint_request
from api.services.agent_processing.lifecycle.runtime import user_interaction_timeline
from api.services.agent_processing.lifecycle.runtime.user_interaction_timeline import (
    build_user_interaction_entry,
    record_user_interaction_entry,
    user_interaction_entry_id,
)


class _Mutations:
    def __init__(self, store: "_KnowledgeService") -> None:
        self._store = store

    async def update_execution_timeline(self, agent_task_id, timeline):
        self._store.records[agent_task_id].execution_timeline = list(timeline)


class _KnowledgeService:
    def __init__(self) -> None:
        self.records = {"task-1": SimpleNamespace(execution_timeline=[])}
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


def _title(kind: str, status: str) -> str:
    return build_user_interaction_entry(interaction_id="x", kind=kind, prompt="p", status=status)["title"]


def test_guidance_and_pause_titles_read_in_plain_language():
    assert _title("guidance", "resolved") == "Basil received your note"
    assert _title("guidance", "canceled") == "Basil finished before reading your note"
    assert _title("pause", "waiting") == "You paused Basil"
    assert _title("pause", "resolved") == "You resumed the run"
    assert _title("pause", "canceled") == "The paused run was stopped"
    assert _title("clarification", "answered") == "You answered"


@pytest.mark.asyncio
async def test_record_user_interaction_entry_persists_and_announces_a_final_status(monkeypatch):
    knowledge = _KnowledgeService()
    monkeypatch.setattr(dependencies_module, "get_sqlite_knowledge_service", lambda: knowledge)
    broadcasts = _Broadcasts()

    await record_user_interaction_entry(
        "task-1",
        interaction_id="note_1",
        kind="guidance",
        prompt="Use blue paint",
        status="resolved",
        asked_at="2026-10-05T10:00:00+00:00",
        broadcast=broadcasts,
    )

    [entry] = knowledge.timeline()
    interaction = entry["metadata"]["user_interaction"]
    assert entry["id"] == user_interaction_entry_id("note_1")
    assert interaction["kind"] == "guidance"
    assert interaction["status"] == "resolved"
    assert interaction["asked_at"] == "2026-10-05T10:00:00+00:00"
    assert interaction["responded_at"]
    assert [event["event_type"] for event in broadcasts.events] == ["agent_task_step_detail"]


@pytest.mark.asyncio
async def test_record_user_interaction_entry_never_raises(monkeypatch):
    knowledge = _KnowledgeService()
    monkeypatch.setattr(dependencies_module, "get_sqlite_knowledge_service", lambda: knowledge)

    await record_user_interaction_entry("task-1", interaction_id="x", kind="bogus", prompt="p", status="resolved")

    assert knowledge.timeline() == []


def _interaction(interaction_id, kind, status, prompt="", response=None):
    return build_user_interaction_entry(
        interaction_id=interaction_id,
        kind=kind,
        prompt=prompt,
        status=status,
        response=response,
    )


def test_user_run_notes_keep_read_notes_and_resume_notes_in_order():
    timeline = [
        {"type": "step", "title": "Thinking"},
        _interaction("n1", "guidance", "resolved", prompt="Stop at 20 instead"),
        _interaction("n2", "guidance", "canceled", prompt="Never read"),
        _interaction("c1", "clarification", "answered", prompt="Which color?", response="Blue"),
        _interaction("p1", "pause", "resolved", prompt=USER_PAUSE_PROMPT, response="Add DONE on the last line"),
        _interaction("p2", "pause", "resolved", prompt=USER_PAUSE_PROMPT),
        _interaction("p3", "pause", "waiting", prompt=USER_PAUSE_PROMPT),
    ]

    assert user_interaction_timeline.user_run_notes_from_timeline(timeline) == [
        "Stop at 20 instead",
        "Add DONE on the last line",
    ]


@pytest.mark.asyncio
async def test_finalizer_judges_against_notes_the_user_sent(monkeypatch):
    from api.services.agent_processing.lifecycle.finalization import result_finalizer_tool

    timeline = [_interaction("n1", "guidance", "resolved", prompt="Stop at 20 instead")]

    async def fake_load(agent_task_id):
        assert agent_task_id == "task-1"
        return timeline

    captured: dict = {}

    class _StopAfterEvaluation(Exception):
        pass

    async def fake_evaluate(**kwargs):
        captured.update(kwargs)
        raise _StopAfterEvaluation()

    monkeypatch.setattr(user_interaction_timeline, "_load_timeline", fake_load)
    monkeypatch.setattr(result_finalizer_tool, "evaluate_finalizer_with_llm", fake_evaluate)

    with pytest.raises(_StopAfterEvaluation):
        await result_finalizer_tool.finalize_agent_task_result(
            original_prompt="Count to 30",
            agent_task_id="task-1",
            active_app=None,
            steps=[],
            standardized_messages=["Counted to 20"],
            llm_model=object(),
            evaluation_context="Root task id: root-1",
        )

    context = captured["evaluation_context"]
    assert context.startswith("NOTES THE USER SENT DURING THIS RUN")
    assert "- Stop at 20 instead" in context
    assert context.endswith("Root task id: root-1")


@pytest.mark.asyncio
async def test_finalizer_context_is_unchanged_without_notes(monkeypatch):
    from api.services.agent_processing.lifecycle.finalization import result_finalizer_tool

    async def fake_load(agent_task_id):
        return []

    captured: dict = {}

    class _StopAfterEvaluation(Exception):
        pass

    async def fake_evaluate(**kwargs):
        captured.update(kwargs)
        raise _StopAfterEvaluation()

    monkeypatch.setattr(user_interaction_timeline, "_load_timeline", fake_load)
    monkeypatch.setattr(result_finalizer_tool, "evaluate_finalizer_with_llm", fake_evaluate)

    with pytest.raises(_StopAfterEvaluation):
        await result_finalizer_tool.finalize_agent_task_result(
            original_prompt="Count to 30",
            agent_task_id="task-1",
            active_app=None,
            steps=[],
            standardized_messages=["Counted to 30"],
            llm_model=object(),
            evaluation_context=None,
        )

    assert captured["evaluation_context"] is None


class _PauseKnowledge:
    def __init__(self) -> None:
        self.updates: list[dict] = []
        self.agent_task_service = SimpleNamespace(
            _queries=SimpleNamespace(get_agent_task=self._get),
            update_agent_task_status_if_active=self._update,
        )

    async def _get(self, agent_task_id):
        return SimpleNamespace(result_data=json.dumps({"keep": 1}))

    async def _update(self, **kwargs):
        self.updates.append(kwargs)
        return True


@pytest.mark.asyncio
async def test_user_pause_is_saved_as_paused_not_as_a_question(monkeypatch):
    knowledge = _PauseKnowledge()
    monkeypatch.setattr(dependencies_module, "get_sqlite_knowledge_service", lambda: knowledge)
    asked: list[dict] = []

    async def fake_asked(agent_task_id, **kwargs):
        asked.append({"agent_task_id": agent_task_id, **kwargs})

    monkeypatch.setattr(user_interaction_timeline, "record_user_interaction_asked", fake_asked)
    broadcasts = _Broadcasts()
    state = SimpleNamespace(
        context={"agent_task_id": "task-1", "root_task_id": "root-1"},
        user_agent_task="Paint the wall",
        available_tools=None,
    )
    coordinator = SimpleNamespace(_websocket_manager=SimpleNamespace(broadcast=broadcasts))
    pause = UserPauseRequest()

    updates = await handle_checkpoint_request(
        pause,
        state,
        coordinator,
        [{"iteration": 1, "text": "Thinking", "is_complete": True}],
    )

    [update] = knowledge.updates
    assert update["agent_task_id"] == "task-1"
    assert update["status"] == "paused"
    assert update["result_data"]["keep"] == 1
    assert update["result_data"]["paused_by_user"] is True
    assert update["result_data"]["checkpoint_data"]["prompt"] == USER_PAUSE_PROMPT
    assert update["result_data"]["thinking_history"][0]["text"] == "Thinking"
    assert [(item["kind"], item["interaction_id"]) for item in asked] == [
        ("pause", pause.checkpoint_data["checkpoint_id"])
    ]
    event_types = [event["event_type"] for event in broadcasts.events]
    assert event_types == ["agent_task_paused"]
    assert broadcasts.events[0]["root_task_id"] == "root-1"
    [result] = updates["tool_execution_results"]
    assert result["status"] == "awaiting_user_input"
    assert result["paused_by_user"] is True
