from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import api.dependencies as dependencies_module
from api.routes.agent_tasks import run_control_routes, session_control_routes
from api.routes.agent_tasks.execution_models import ContinueSessionRequest
from api.services.agent_processing.shared import agent_run_control
from api.services.agent_processing.shared.agent_run_control import run_control_for


class _AgentTask:
    def __init__(self, status: str) -> None:
        self.status = status


class _Broadcasts:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, event: dict) -> None:
        self.events.append(event)


class _Coordinator:
    instances: list["_Coordinator"] = []
    error: Exception | None = None

    def __init__(self, *, websocket_manager, agent_task_submission_service=None) -> None:
        self.websocket_manager = websocket_manager
        self.agent_task_submission_service = agent_task_submission_service
        self.resume_calls: list[tuple[str, str]] = []
        self.__class__.instances.append(self)

    async def resume_workflow(self, *, agent_task_id: str, user_response: str):
        self.resume_calls.append((agent_task_id, user_response))
        if self.__class__.error is not None:
            raise self.__class__.error
        return SimpleNamespace(execution_results=[], final_envelope=None, todos_completed=1, overall_success=True)


def _request(submission_service=None):
    service = submission_service or SimpleNamespace(agent_task_orchestrator=None, broadcast=_Broadcasts())
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(agent_task_submission_service=service)))


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    agent_run_control._controls.clear()
    run_control_routes._resuming_agent_task_ids.clear()
    _Coordinator.instances = []
    _Coordinator.error = None
    monkeypatch.setattr(run_control_routes, "WorkflowCoordinator", _Coordinator)
    resolutions: list[dict] = []

    async def fake_resolve(agent_task_id, **kwargs):
        resolutions.append({"agent_task_id": agent_task_id, **kwargs})

    monkeypatch.setattr(run_control_routes, "resolve_latest_waiting_user_interaction", fake_resolve)
    monkeypatch.setattr(session_control_routes, "resolve_all_waiting_user_interactions", fake_resolve)
    yield resolutions
    agent_run_control._controls.clear()
    run_control_routes._resuming_agent_task_ids.clear()


def _task_status(monkeypatch, status: str) -> None:
    monkeypatch.setattr(run_control_routes, "_get_agent_task_or_raise", AsyncMock(return_value=_AgentTask(status)))


async def _drain_background_resumes() -> None:
    while run_control_routes._background_resumes:
        await asyncio.gather(*list(run_control_routes._background_resumes), return_exceptions=True)


@pytest.mark.asyncio
async def test_pause_requests_a_pause_on_a_working_run(monkeypatch):
    _task_status(monkeypatch, "processing")
    control = run_control_for("task-1")
    control.attach()

    response = await run_control_routes.pause_session(agent_task_id="task-1", request=_request())

    assert response.status == "pause_requested"
    assert control.pause_requested() is True


@pytest.mark.asyncio
async def test_pause_is_refused_when_the_run_is_not_working(monkeypatch):
    _task_status(monkeypatch, "awaiting_user_input")
    run_control_for("task-1").attach()

    with pytest.raises(HTTPException) as refused:
        await run_control_routes.pause_session(agent_task_id="task-1", request=_request())

    assert refused.value.status_code == 409
    assert refused.value.detail == "Basil can only pause a run while it is working."


@pytest.mark.asyncio
async def test_pause_is_refused_without_an_attached_loop(monkeypatch):
    _task_status(monkeypatch, "processing")

    with pytest.raises(HTTPException) as refused:
        await run_control_routes.pause_session(agent_task_id="task-1", request=_request())

    assert refused.value.status_code == 409


@pytest.mark.asyncio
async def test_note_is_queued_for_an_attached_loop(monkeypatch):
    _task_status(monkeypatch, "processing")
    control = run_control_for("task-1")
    control.attach()

    response = await run_control_routes.send_run_message(
        agent_task_id="task-1",
        request=_request(),
        body=run_control_routes.RunMessageRequest(text="  Use blue paint  "),
    )

    assert response.status == "queued"
    [note] = control.drain()
    assert note.text == "Use blue paint"
    assert response.message_id == note.message_id


@pytest.mark.asyncio
async def test_note_is_refused_when_empty_or_without_a_loop(monkeypatch):
    _task_status(monkeypatch, "processing")

    with pytest.raises(HTTPException) as empty:
        await run_control_routes.send_run_message(
            agent_task_id="task-1",
            request=_request(),
            body=run_control_routes.RunMessageRequest(text="   "),
        )
    assert empty.value.status_code == 422

    with pytest.raises(HTTPException) as unattached:
        await run_control_routes.send_run_message(
            agent_task_id="task-1",
            request=_request(),
            body=run_control_routes.RunMessageRequest(text="Hello"),
        )
    assert unattached.value.status_code == 409
    assert "can read notes" in unattached.value.detail


@pytest.mark.asyncio
async def test_note_carries_attached_paths_into_the_queued_text(monkeypatch):
    _task_status(monkeypatch, "processing")
    control = run_control_for("task-1")
    control.attach()

    await run_control_routes.send_run_message(
        agent_task_id="task-1",
        request=_request(),
        body=run_control_routes.RunMessageRequest(
            text="Start here",
            reference_paths=[" /Users/me/Projects ", "/Users/me/Projects", "", "/Users/me/notes.md"],
        ),
    )

    [note] = control.drain()
    assert note.text == (
        "Start here\n\n"
        "Attached for you to look at (local paths on the user's Mac):\n"
        "- /Users/me/Projects\n"
        "- /Users/me/notes.md"
    )


def test_attached_paths_are_validated():
    with pytest.raises(ValueError):
        run_control_routes.RunMessageRequest(text="Hi", reference_paths=["/tmp/a\nb"])
    with pytest.raises(ValueError):
        run_control_routes.RunMessageRequest(text="Hi", reference_paths=["/" + "x" * run_control_routes.MAX_REFERENCE_PATH_LENGTH])
    with pytest.raises(ValueError):
        run_control_routes.ResumeRunRequest(reference_paths=[f"/tmp/{i}" for i in range(run_control_routes.MAX_REFERENCE_PATHS + 1)])


@pytest.mark.asyncio
async def test_resume_with_only_attached_paths_still_tells_the_agent(monkeypatch, isolated_state):
    _task_status(monkeypatch, "paused")
    submission_service = SimpleNamespace(agent_task_orchestrator=None, broadcast=_Broadcasts())

    await run_control_routes.resume_session(
        agent_task_id="task-1",
        request=_request(submission_service),
        body=run_control_routes.ResumeRunRequest(reference_paths=["/Users/me/Projects"]),
    )
    await _drain_background_resumes()

    [resolution] = isolated_state
    assert resolution["response"].endswith("- /Users/me/Projects")
    [coordinator] = _Coordinator.instances
    [(_, user_response)] = coordinator.resume_calls
    assert user_response.endswith("They added: Attached for you to look at (local paths on the user's Mac):\n- /Users/me/Projects")


def test_note_longer_than_the_limit_is_rejected_by_validation():
    with pytest.raises(ValueError):
        run_control_routes.RunMessageRequest(text="x" * (run_control_routes.MAX_RUN_NOTE_LENGTH + 1))


@pytest.mark.asyncio
async def test_resume_resolves_the_pause_and_resumes_in_the_background(monkeypatch, isolated_state):
    _task_status(monkeypatch, "paused")
    submission_service = SimpleNamespace(agent_task_orchestrator=None, broadcast=_Broadcasts())

    response = await run_control_routes.resume_session(
        agent_task_id="task-1",
        request=_request(submission_service),
        body=run_control_routes.ResumeRunRequest(note="  Use blue  "),
    )
    await _drain_background_resumes()

    assert response.status == "resuming"
    [resolution] = isolated_state
    assert resolution["agent_task_id"] == "task-1"
    assert resolution["kinds"] == ("pause",)
    assert resolution["status"] == "resolved"
    assert resolution["response"] == "Use blue"
    [coordinator] = _Coordinator.instances
    assert coordinator.websocket_manager is submission_service
    [(task_id, user_response)] = coordinator.resume_calls
    assert task_id == "task-1"
    assert user_response.startswith(run_control_routes.RESUME_INSTRUCTION)
    assert user_response.endswith("They added: Use blue")
    assert "task-1" not in run_control_routes._resuming_agent_task_ids


@pytest.mark.asyncio
async def test_resume_is_refused_unless_paused_or_while_already_resuming(monkeypatch):
    _task_status(monkeypatch, "processing")
    with pytest.raises(HTTPException) as not_paused:
        await run_control_routes.resume_session(
            agent_task_id="task-1",
            request=_request(),
            body=run_control_routes.ResumeRunRequest(),
        )
    assert not_paused.value.status_code == 409
    assert not_paused.value.detail == "Only a paused run can be resumed."

    _task_status(monkeypatch, "paused")
    run_control_routes._resuming_agent_task_ids.add("task-1")
    with pytest.raises(HTTPException) as duplicate:
        await run_control_routes.resume_session(
            agent_task_id="task-1",
            request=_request(),
            body=run_control_routes.ResumeRunRequest(),
        )
    assert duplicate.value.status_code == 409
    assert duplicate.value.detail == "This run is already resuming."


@pytest.mark.asyncio
async def test_failed_resume_marks_the_task_failed_and_tells_the_ui(monkeypatch):
    _task_status(monkeypatch, "paused")
    _Coordinator.error = ValueError("No checkpoint found for agent_task_id: task-1")
    updates: list[dict] = []

    class _Knowledge:
        async def update_agent_task_status_if_active(self, **kwargs):
            updates.append(kwargs)
            return True

    monkeypatch.setattr(dependencies_module, "get_sqlite_knowledge_service", lambda: _Knowledge())
    broadcasts = _Broadcasts()

    await run_control_routes.resume_session(
        agent_task_id="task-1",
        request=_request(SimpleNamespace(agent_task_orchestrator=None, broadcast=broadcasts)),
        body=run_control_routes.ResumeRunRequest(),
    )
    await _drain_background_resumes()

    assert updates == [{
        "agent_task_id": "task-1",
        "status": "failed",
        "result_data": {"success": False, "error": "No checkpoint found for agent_task_id: task-1"},
    }]
    [event] = broadcasts.events
    assert event["event_type"] == "agent_task_progress"
    assert event["status"] == "failed"
    assert event["details"].startswith("Could not resume:")
    assert "task-1" not in run_control_routes._resuming_agent_task_ids


@pytest.mark.asyncio
async def test_continue_refuses_a_paused_task(monkeypatch):
    monkeypatch.setattr(
        session_control_routes,
        "_get_agent_task_or_raise",
        AsyncMock(return_value=_AgentTask("paused")),
    )

    with pytest.raises(HTTPException) as refused:
        await session_control_routes.continue_session(
            agent_task_id="task-1",
            request=_request(),
            body=ContinueSessionRequest(agent_task_id="task-1", user_input="Blue"),
        )

    assert refused.value.status_code == 409
    assert "use Resume" in refused.value.detail


@pytest.mark.asyncio
async def test_cancel_closes_every_waiting_interaction_on_the_canceled_tasks(isolated_state):
    submission_service = SimpleNamespace(
        broadcast=_Broadcasts(),
        cancel_agent_task_durably=AsyncMock(
            return_value={"root_task_id": "root-1", "canceled_task_ids": ["root-1", "task-1"]}
        ),
    )

    response = await session_control_routes.cancel_session(
        agent_task_id="task-1",
        request=_request(submission_service),
        body=session_control_routes.CancelSessionRequest(reason="user_canceled"),
    )

    assert response.success is True
    assert [(item["agent_task_id"], item["status"]) for item in isolated_state] == [
        ("root-1", "canceled"),
        ("task-1", "canceled"),
    ]
