"""A scheduled run takes its agent task's own status and outcome, exactly as the UI reads any agent task."""

from __future__ import annotations

import asyncio
import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.events import AgentTaskEvent
from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components import (
    scheduled_run_execution as sre,
)
from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components.scheduled_run_outcome import (
    read_task_result,
    read_task_result_fields,
    with_task_result_fields,
)

PARTIAL_MESSAGE = "Partial result: I tried multiple ways to complete the request, but some operations failed."


def _task(status: str, outcome: str | None = None, verification: str | None = None, message: str | None = None) -> dict:
    result_data: dict = {}
    if outcome is not None or verification is not None:
        result_data["finalizer_result"] = {"result_payload": {}}
        if outcome is not None:
            result_data["finalizer_result"]["outcome"] = outcome
        if verification is not None:
            result_data["finalizer_result"]["result_payload"]["verification_status"] = verification
    if message is not None:
        result_data["message"] = message
    return {"status": status, "result_data": result_data}


# --- reading a task the way the UI does ----------------------------------------------------------


def test_a_task_saved_as_failed_with_a_partial_outcome_is_a_partial_result() -> None:
    reading = read_task_result(_task("failed", "partial", "resolved", PARTIAL_MESSAGE))

    assert reading.outcome == "partial"
    assert reading.is_final is True
    assert reading.message == PARTIAL_MESSAGE


def test_a_completed_task_with_a_success_outcome_succeeded() -> None:
    assert read_task_result(_task("completed", "success", "resolved")).outcome == "success"


def test_a_failed_task_without_a_finalizer_result_failed() -> None:
    reading = read_task_result(_task("failed"))

    assert reading.outcome == "failed"
    assert reading.is_final is True


def test_a_failure_outcome_is_a_failure_even_when_the_task_row_says_completed() -> None:
    assert read_task_result(_task("completed", "failure", "resolved")).outcome == "failed"


def test_completed_with_warnings_is_partial_like_the_ui_treats_it() -> None:
    assert read_task_result(_task("completed", "completed_with_warnings", "resolved")).outcome == "partial"


def test_a_result_still_being_verified_is_not_final() -> None:
    assert read_task_result(_task("failed", "partial", "pending")).is_final is False
    assert read_task_result(_task("completed", "success", "pending")).is_final is False


def test_a_paused_or_canceled_task_is_final_even_if_verification_never_resolved() -> None:
    assert read_task_result(_task("paused", "partial", "pending")).is_final is True
    assert read_task_result(_task("canceled", None, "pending")).is_final is True


def test_result_data_stored_as_json_text_is_read_the_same() -> None:
    task = _task("failed", "partial", "resolved", PARTIAL_MESSAGE)
    task["result_data"] = json.dumps(task["result_data"])

    assert read_task_result(task).outcome == "partial"


def test_malformed_or_missing_result_data_reads_as_the_plain_status() -> None:
    assert read_task_result({"status": "completed", "result_data": "{not json"}).outcome == "success"
    assert read_task_result({"status": "failed", "result_data": None}).outcome == "failed"
    assert read_task_result(None).task_status is None


def test_a_run_row_is_enriched_with_task_fields_and_loses_the_raw_result() -> None:
    row = {
        "id": "run-1",
        "status": "failed",
        "agent_task_status": "failed",
        "agent_task_result_data": _task("failed", "partial", "resolved")["result_data"],
    }

    enriched = with_task_result_fields(row)

    assert "agent_task_result_data" not in enriched
    assert enriched["agent_task_status"] == "failed"
    assert enriched["outcome"] == "partial"
    assert enriched["verification_status"] == "resolved"
    assert enriched["id"] == "run-1"


def test_a_run_without_an_agent_task_has_no_task_fields() -> None:
    assert read_task_result_fields(None, None) == {
        "agent_task_status": None,
        "outcome": None,
        "verification_status": None,
    }


# --- the run waits for the verified result -------------------------------------------------------


def _event(event_type: str, agent_task_id: str, task: dict, new_status: str | None = None) -> AgentTaskEvent:
    return AgentTaskEvent(
        agent_task_id=agent_task_id,
        event_type=event_type,
        new_status=new_status,
        agent_task_data=task,
    )


@pytest.fixture
def waiting_run():
    loop = asyncio.new_event_loop()
    future = loop.create_future()
    sre._PENDING_AGENT_TASK_COMPLETIONS["task-1"] = future
    yield future
    sre._PENDING_AGENT_TASK_COMPLETIONS.pop("task-1", None)
    handle = sre._VERIFICATION_RECHECKS.pop("task-1", None)
    if handle is not None:
        handle.cancel()
    loop.close()


def test_a_provisional_result_does_not_end_the_run(waiting_run) -> None:
    sre.handle_agent_task_event(
        _event("status_changed", "task-1", _task("failed", "partial", "pending", PARTIAL_MESSAGE), "failed")
    )

    assert waiting_run.done() is False


def test_the_verified_result_ends_the_run_even_when_the_status_did_not_change(waiting_run) -> None:
    sre.handle_agent_task_event(_event("status_changed", "task-1", _task("failed", "partial", "pending"), "failed"))
    sre.handle_agent_task_event(_event("updated", "task-1", _task("failed", "partial", "resolved", PARTIAL_MESSAGE)))

    assert waiting_run.done() is True
    assert waiting_run.result()["status"] == "failed"
    assert read_task_result(waiting_run.result()["agent_task_data"]).outcome == "partial"


def test_a_result_upgraded_by_verification_ends_the_run_as_a_success(waiting_run) -> None:
    sre.handle_agent_task_event(_event("status_changed", "task-1", _task("failed", "partial", "pending"), "failed"))
    sre.handle_agent_task_event(
        _event("status_changed", "task-1", _task("completed", "success", "resolved"), "completed")
    )

    assert waiting_run.result()["status"] == "completed"
    assert read_task_result(waiting_run.result()["agent_task_data"]).outcome == "success"


def test_a_task_that_is_not_run_ending_keeps_the_run_waiting(waiting_run) -> None:
    sre.handle_agent_task_event(_event("status_changed", "task-1", _task("processing"), "processing"))
    sre.handle_agent_task_event(_event("created", "task-1", _task("failed", "failure", "resolved"), "failed"))

    assert waiting_run.done() is False


def test_a_paused_task_ends_the_run_without_waiting_for_verification(waiting_run) -> None:
    sre.handle_agent_task_event(_event("status_changed", "task-1", _task("paused", None, "pending"), "paused"))

    assert waiting_run.result()["status"] == "paused"


# --- a whole run ---------------------------------------------------------------------------------


def _run_harness(monkeypatch: pytest.MonkeyPatch, events_for):
    """Run execute_scheduled_run with a fake submission service that emits ``events_for(agent_task_id)`` after submitting."""
    broadcasts = AsyncMock()

    async def submit(**kwargs):
        agent_task_id = kwargs["agent_task_id"]
        loop = asyncio.get_running_loop()
        for delay, event in events_for(agent_task_id):
            loop.call_later(delay, sre.handle_agent_task_event, event)
        return {"success": True}

    submission_service = SimpleNamespace(process_agent_task_direct=AsyncMock(side_effect=submit), broadcast=broadcasts)
    monkeypatch.setattr("api.main.app", SimpleNamespace(state=SimpleNamespace(agent_task_submission_service=submission_service)))
    monkeypatch.setattr(sre, "_prevent_idle_system_sleep_for_scheduled_run", lambda **_kwargs: nullcontext())
    finalize = AsyncMock(side_effect=lambda *a, **kw: {"status": "completed" if kw["success"] else "failed", "next_run_at": None})
    monkeypatch.setattr(sre.scheduled_run_lifecycle, "finalize_run_after_execution", finalize)
    repo = SimpleNamespace(
        get_scheduled_run=AsyncMock(return_value={"status": "scheduled", "notice": None}),
        get_scheduled_agent_task=AsyncMock(
            return_value={"is_active": True, "agent_task_text": "Do the thing", "title": "Daily check", "reference_paths": []}
        ),
        update_scheduled_run=AsyncMock(),
    )
    return repo, broadcasts, finalize


def _completion_broadcast(broadcasts: AsyncMock) -> dict:
    events = [call.args[0] for call in broadcasts.await_args_list]
    return next(event for event in events if event["event_type"] == "scheduled_agent_task_run_completed")


@pytest.mark.asyncio
async def test_a_partial_result_finishes_the_run_as_completed_with_a_notice_and_a_partial_outcome(monkeypatch) -> None:
    def events(agent_task_id):
        return [(0.01, _event("status_changed", agent_task_id, _task("failed", "partial", "resolved", PARTIAL_MESSAGE), "failed"))]

    repo, broadcasts, finalize = _run_harness(monkeypatch, events)

    await sre.execute_scheduled_run(repo, SimpleNamespace(), "schedule-1", "run-1")

    finalize_kwargs = finalize.await_args.kwargs
    assert finalize_kwargs["success"] is True
    assert finalize_kwargs["error_message"] is None
    repo.update_scheduled_run.assert_any_await("run-1", notice=PARTIAL_MESSAGE)
    completion = _completion_broadcast(broadcasts)
    assert completion["status"] == "completed"
    assert completion["agent_task_status"] == "failed"
    assert completion["outcome"] == "partial"


@pytest.mark.asyncio
async def test_a_provisional_failure_that_verification_upgrades_finishes_the_run_as_a_success(monkeypatch) -> None:
    def events(agent_task_id):
        return [
            (0.01, _event("status_changed", agent_task_id, _task("failed", "partial", "pending", PARTIAL_MESSAGE), "failed")),
            (0.05, _event("status_changed", agent_task_id, _task("completed", "success", "resolved"), "completed")),
        ]

    repo, broadcasts, finalize = _run_harness(monkeypatch, events)

    await sre.execute_scheduled_run(repo, SimpleNamespace(), "schedule-1", "run-1")

    assert finalize.await_args.kwargs["success"] is True
    assert finalize.await_args.kwargs["error_message"] is None
    notices = [call for call in repo.update_scheduled_run.await_args_list if "notice" in call.kwargs]
    assert notices == []
    completion = _completion_broadcast(broadcasts)
    assert completion["agent_task_status"] == "completed"
    assert completion["outcome"] == "success"


@pytest.mark.asyncio
async def test_a_real_failure_still_finishes_the_run_as_failed_with_the_task_message(monkeypatch) -> None:
    def events(agent_task_id):
        task = _task("failed", "failure", "resolved", "Could not reach the server.")
        return [(0.01, _event("status_changed", agent_task_id, task, "failed"))]

    repo, broadcasts, finalize = _run_harness(monkeypatch, events)

    await sre.execute_scheduled_run(repo, SimpleNamespace(), "schedule-1", "run-1")

    assert finalize.await_args.kwargs["success"] is False
    assert finalize.await_args.kwargs["error_message"] == "Could not reach the server."
    assert _completion_broadcast(broadcasts)["outcome"] == "failed"


@pytest.mark.asyncio
async def test_a_partial_result_keeps_the_model_notice_already_on_the_run(monkeypatch) -> None:
    def events(agent_task_id):
        return [(0.01, _event("status_changed", agent_task_id, _task("failed", "partial", "resolved", PARTIAL_MESSAGE), "failed"))]

    repo, _broadcasts, _finalize = _run_harness(monkeypatch, events)
    repo.get_scheduled_run = AsyncMock(return_value={"status": "scheduled", "notice": "Ran with the default model."})

    await sre.execute_scheduled_run(repo, SimpleNamespace(), "schedule-1", "run-1")

    repo.update_scheduled_run.assert_any_await("run-1", notice=f"Ran with the default model. {PARTIAL_MESSAGE}")
