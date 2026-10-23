"""A scheduled task can pin the reasoning model its runs use."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import api.services.reasoning_model_catalog as catalog
from api.core.knowledge.sqlite.schema import get_schema_statements
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.scheduling_migrations import (
    migrate_scheduled_agent_tasks_tables,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.scheduling.repository import (
    ScheduledAgentTaskRepository,
)
from api.routes.agent_tasks import schedule_routes
from api.routes.agent_tasks.models import (
    ScheduledAgentTaskCreateRequest,
    ScheduledAgentTaskItem,
    ScheduledAgentTaskUpdateRequest,
)
from api.services.scheduled_agent_tasks.scheduled_agent_task_service_components import (
    scheduled_run_execution as sre,
)

LOCAL_MODEL = "Qwen-qwen35-4b-q4km"


# --- storage -------------------------------------------------------------------------------------


def _create_tables(path: str) -> None:
    connection = sqlite3.connect(path)
    for statement in get_schema_statements():
        lowered = statement.lower()
        if "create table if not exists scheduled_agent_task" in lowered:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute(statement)
    connection.commit()
    connection.close()


@pytest.fixture
def repository(tmp_path):
    path = str(tmp_path / "schedules.db")
    _create_tables(path)
    return ScheduledAgentTaskRepository(path)


def _create(repository, **overrides):
    values = {
        "title": "Check email",
        "agent_task_text": "Check my inbox",
        "schedule_type": "recurring",
        "schedule_config": {"mode": "interval", "minutes": 15},
        "timezone": "UTC",
        "next_run_at": None,
    }
    values.update(overrides)
    return asyncio.run(repository.create_scheduled_agent_task(**values))


def test_a_schedule_stores_the_model_it_was_given(repository):
    created = _create(repository, model_id=f"  {LOCAL_MODEL}  ")

    assert created["model_id"] == LOCAL_MODEL
    assert asyncio.run(repository.get_scheduled_agent_task(created["id"]))["model_id"] == LOCAL_MODEL


def test_a_schedule_without_a_model_reads_back_as_none(repository):
    assert _create(repository)["model_id"] is None
    assert _create(repository, model_id="   ")["model_id"] is None


def test_update_leaves_the_model_alone_changes_it_or_clears_it(repository):
    created = _create(repository, model_id=LOCAL_MODEL)
    schedule_id = created["id"]

    untouched = asyncio.run(repository.update_scheduled_agent_task(schedule_id, title="Renamed"))
    assert untouched["model_id"] == LOCAL_MODEL

    changed = asyncio.run(repository.update_scheduled_agent_task(schedule_id, model_id="claude-haiku"))
    assert changed["model_id"] == "claude-haiku"

    cleared = asyncio.run(repository.update_scheduled_agent_task(schedule_id, model_id=""))
    assert cleared["model_id"] is None


def test_a_run_can_carry_a_notice_that_is_not_an_error(repository):
    schedule = _create(repository)
    run = asyncio.run(repository.create_scheduled_run(schedule["id"], "2026-10-19T12:00:00+00:00"))
    run_id = run["id"] if isinstance(run, dict) else run

    updated = asyncio.run(repository.update_scheduled_run(run_id, notice="Ran with the default model."))

    assert updated["notice"] == "Ran with the default model."
    assert updated["error_message"] is None


def test_existing_databases_gain_the_new_columns_and_keep_their_schedules(tmp_path):
    path = str(tmp_path / "old.db")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE scheduled_agent_tasks (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, agent_task_text TEXT NOT NULL, schedule_type TEXT NOT NULL,
            schedule_config TEXT NOT NULL, timezone TEXT DEFAULT 'UTC', is_active BOOLEAN DEFAULT TRUE,
            source_type TEXT DEFAULT 'manual', reference_paths TEXT NOT NULL DEFAULT '[]', next_run_at TIMESTAMP,
            last_run_at TIMESTAMP, last_status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE scheduled_agent_task_runs (
            id TEXT PRIMARY KEY, scheduled_agent_task_id TEXT NOT NULL, agent_task_id TEXT,
            scheduled_for TIMESTAMP NOT NULL, started_at TIMESTAMP, completed_at TIMESTAMP,
            status TEXT NOT NULL DEFAULT 'scheduled', error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        "INSERT INTO scheduled_agent_tasks (id, title, agent_task_text, schedule_type, schedule_config) "
        "VALUES ('old-1', 'Old', 'Do it', 'recurring', '{}')"
    )
    connection.commit()

    migrate_scheduled_agent_tasks_tables(connection)
    connection.commit()
    connection.close()

    repository = ScheduledAgentTaskRepository(path)
    old = asyncio.run(repository.get_scheduled_agent_task("old-1"))
    assert old["model_id"] is None
    assert old["title"] == "Old"


# --- routes --------------------------------------------------------------------------------------


@pytest.fixture
def stub_service(monkeypatch):
    service = SimpleNamespace(
        create_scheduled_agent_task=AsyncMock(side_effect=lambda **kwargs: _item(model_id=kwargs["model_id"])),
        update_scheduled_agent_task=AsyncMock(side_effect=lambda _id, updates: _item(model_id=updates.get("model_id"))),
    )
    monkeypatch.setattr(schedule_routes, "ScheduledAgentTaskService", lambda: service)
    return service


def _item(model_id=None):
    return {
        "id": "schedule-1",
        "title": "Check email",
        "agent_task_text": "Check my inbox",
        "schedule_type": "recurring",
        "schedule_config": {"mode": "interval", "minutes": 15},
        "timezone": "UTC",
        "is_active": True,
        "source_type": "manual",
        "reference_paths": [],
        "model_id": model_id or None,
        "created_at": "2026-10-19T12:00:00",
        "updated_at": "2026-10-19T12:00:00",
    }


def _available(monkeypatch, *model_ids: str) -> None:
    async def is_available(model_id: str) -> bool:
        return model_id in model_ids

    monkeypatch.setattr(schedule_routes, "is_reasoning_model_available", is_available)


def _create_request(**overrides):
    values = {
        "title": "Check email",
        "agent_task_text": "Check my inbox",
        "schedule_type": "recurring",
        "schedule_config": {"mode": "interval", "minutes": 15},
    }
    values.update(overrides)
    return ScheduledAgentTaskCreateRequest(**values)


@pytest.mark.asyncio
async def test_create_passes_an_available_model_to_the_service(monkeypatch, stub_service):
    _available(monkeypatch, LOCAL_MODEL)

    created = await schedule_routes.create_scheduled_agent_task(_create_request(model_id=f" {LOCAL_MODEL} "))

    assert stub_service.create_scheduled_agent_task.await_args.kwargs["model_id"] == LOCAL_MODEL
    assert created.model_id == LOCAL_MODEL


@pytest.mark.asyncio
async def test_create_without_a_model_uses_the_default(monkeypatch, stub_service):
    _available(monkeypatch)

    created = await schedule_routes.create_scheduled_agent_task(_create_request())

    assert stub_service.create_scheduled_agent_task.await_args.kwargs["model_id"] is None
    assert created.model_id is None


@pytest.mark.asyncio
async def test_an_unavailable_model_is_refused_on_create_and_update(monkeypatch, stub_service):
    _available(monkeypatch, "claude-haiku")

    with pytest.raises(HTTPException) as on_create:
        await schedule_routes.create_scheduled_agent_task(_create_request(model_id=LOCAL_MODEL))
    with pytest.raises(HTTPException) as on_update:
        await schedule_routes.update_scheduled_agent_task(
            "schedule-1", ScheduledAgentTaskUpdateRequest(model_id=LOCAL_MODEL)
        )

    assert on_create.value.status_code == 422
    assert on_update.value.status_code == 422
    stub_service.create_scheduled_agent_task.assert_not_awaited()
    stub_service.update_scheduled_agent_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_distinguishes_leave_alone_from_clear_to_default(monkeypatch, stub_service):
    _available(monkeypatch, LOCAL_MODEL)

    await schedule_routes.update_scheduled_agent_task("schedule-1", ScheduledAgentTaskUpdateRequest(title="Renamed"))
    left_alone = stub_service.update_scheduled_agent_task.await_args.args[1]
    await schedule_routes.update_scheduled_agent_task("schedule-1", ScheduledAgentTaskUpdateRequest(model_id=""))
    cleared = stub_service.update_scheduled_agent_task.await_args.args[1]
    await schedule_routes.update_scheduled_agent_task("schedule-1", ScheduledAgentTaskUpdateRequest(model_id=LOCAL_MODEL))
    chosen = stub_service.update_scheduled_agent_task.await_args.args[1]

    assert "model_id" not in left_alone
    assert cleared["model_id"] == ""
    assert chosen["model_id"] == LOCAL_MODEL


def test_the_response_models_carry_the_model_and_notice():
    assert ScheduledAgentTaskItem(**_item(LOCAL_MODEL)).model_id == LOCAL_MODEL
    assert ScheduledAgentTaskItem(**_item()).model_id is None


# --- the catalog -----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalog_accepts_only_listed_models(monkeypatch):
    from api.routes.settings_routes.api_models import reasoning_routes

    response = SimpleNamespace(models=[{"id": LOCAL_MODEL}, SimpleNamespace(id="claude-haiku")])
    monkeypatch.setattr(reasoning_routes, "get_api_reasoning_models", AsyncMock(return_value=response))
    monkeypatch.setattr("api.core.services.model_service.get_model_service", lambda: object())

    assert await catalog.is_reasoning_model_available(LOCAL_MODEL) is True
    assert await catalog.is_reasoning_model_available(" claude-haiku ") is True
    assert await catalog.is_reasoning_model_available("not-installed") is False
    assert await catalog.is_reasoning_model_available("") is False


# --- running a schedule ----------------------------------------------------------------------------


def _runner_harness(monkeypatch, *, model_id, submission_result=None):
    submission_service = SimpleNamespace(
        process_agent_task_direct=AsyncMock(return_value=submission_result or {"success": False, "message": "stop here"}),
        broadcast=AsyncMock(),
    )
    monkeypatch.setattr("api.main.app", SimpleNamespace(state=SimpleNamespace(agent_task_submission_service=submission_service)))
    monkeypatch.setattr(sre, "_prevent_idle_system_sleep_for_scheduled_run", lambda **_kwargs: nullcontext())
    finalize = AsyncMock(return_value={"status": "failed", "next_run_at": None})
    monkeypatch.setattr(sre.scheduled_run_lifecycle, "finalize_run_after_execution", finalize)
    repo = SimpleNamespace(
        get_scheduled_run=AsyncMock(return_value={"status": "scheduled"}),
        get_scheduled_agent_task=AsyncMock(
            return_value={
                "is_active": True,
                "agent_task_text": "Check my inbox",
                "title": "Check email",
                "reference_paths": [],
                "model_id": model_id,
            }
        ),
        update_scheduled_run=AsyncMock(),
    )
    return SimpleNamespace(submission=submission_service, repo=repo, finalize=finalize)


def _catalog_says(monkeypatch, available):
    async def check(_model_id):
        if isinstance(available, Exception):
            raise available
        return available

    monkeypatch.setattr(catalog, "is_reasoning_model_available", check)


def _notices(repo):
    return [call.kwargs["notice"] for call in repo.update_scheduled_run.await_args_list if "notice" in call.kwargs]


@pytest.mark.asyncio
async def test_a_run_uses_the_chosen_model_when_it_is_available(monkeypatch):
    harness = _runner_harness(monkeypatch, model_id=LOCAL_MODEL)
    _catalog_says(monkeypatch, True)

    await sre.execute_scheduled_run(harness.repo, SimpleNamespace(), "schedule-1", "run-1")

    assert harness.submission.process_agent_task_direct.await_args.kwargs["model_id"] == LOCAL_MODEL
    assert _notices(harness.repo) == []


@pytest.mark.asyncio
async def test_a_run_falls_back_to_the_default_model_and_says_so(monkeypatch):
    harness = _runner_harness(monkeypatch, model_id=LOCAL_MODEL)
    _catalog_says(monkeypatch, False)

    await sre.execute_scheduled_run(harness.repo, SimpleNamespace(), "schedule-1", "run-1")

    assert harness.submission.process_agent_task_direct.await_args.kwargs["model_id"] is None
    [notice] = _notices(harness.repo)
    assert LOCAL_MODEL in notice
    assert "default model" in notice


@pytest.mark.asyncio
async def test_a_schedule_without_a_model_runs_on_the_default_with_no_notice(monkeypatch):
    harness = _runner_harness(monkeypatch, model_id=None)
    _catalog_says(monkeypatch, RuntimeError("must not be consulted"))

    await sre.execute_scheduled_run(harness.repo, SimpleNamespace(), "schedule-1", "run-1")

    assert harness.submission.process_agent_task_direct.await_args.kwargs["model_id"] is None
    assert _notices(harness.repo) == []


@pytest.mark.asyncio
async def test_a_failed_availability_check_does_not_change_the_chosen_model(monkeypatch):
    harness = _runner_harness(monkeypatch, model_id=LOCAL_MODEL)
    _catalog_says(monkeypatch, RuntimeError("settings unavailable"))

    await sre.execute_scheduled_run(harness.repo, SimpleNamespace(), "schedule-1", "run-1")

    assert harness.submission.process_agent_task_direct.await_args.kwargs["model_id"] == LOCAL_MODEL
    assert _notices(harness.repo) == []


# --- a paused task ends the run attempt ------------------------------------------------------------


def _status_event(agent_task_id, status, result_data=None):
    return SimpleNamespace(
        event_type="status_changed",
        agent_task_id=agent_task_id,
        new_status=status,
        agent_task_data={"result_data": result_data or {}},
    )


@pytest.mark.asyncio
async def test_a_paused_task_ends_the_run_instead_of_waiting_for_the_timeout(monkeypatch):
    harness = _runner_harness(monkeypatch, model_id=None, submission_result={"success": True})

    async def pause_the_task(**kwargs):
        sre.handle_agent_task_event(
            _status_event(kwargs["agent_task_id"], "paused", {"paused_for_connection_loss": True})
        )
        return {"success": True}

    harness.submission.process_agent_task_direct.side_effect = pause_the_task

    await sre.execute_scheduled_run(harness.repo, SimpleNamespace(), "schedule-1", "run-1")

    kwargs = harness.finalize.await_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["error_message"] == (
        "Paused because the connection to the model was lost. Open the task to resume it."
    )


def test_a_plain_pause_gets_a_plain_message():
    assert sre._paused_run_message({"result_data": {"paused_by_user": True}}) == (
        "Paused before finishing. Open the task to resume it."
    )
    assert sre._paused_run_message({"result_data": '{"paused_for_connection_loss": true}'}).startswith(
        "Paused because the connection"
    )
    assert sre._paused_run_message({}) == "Paused before finishing. Open the task to resume it."


@pytest.mark.asyncio
async def test_other_in_flight_statuses_still_keep_the_run_waiting():
    future = asyncio.get_running_loop().create_future()
    sre._PENDING_AGENT_TASK_COMPLETIONS["task-x"] = future
    try:
        sre.handle_agent_task_event(_status_event("task-x", "processing"))
        assert future.done() is False
        sre.handle_agent_task_event(_status_event("task-x", "paused"))
        assert future.result()["status"] == "paused"
    finally:
        sre._PENDING_AGENT_TASK_COMPLETIONS.pop("task-x", None)


# --- active runs for the mini panel ----------------------------------------------------------------


def _add_agent_tasks_table(path: str, rows: dict[str, str]) -> None:
    connection = sqlite3.connect(path)
    for statement in get_schema_statements():
        if "create table if not exists agent_tasks (" in " ".join(statement.lower().split()):
            connection.execute(statement)
    connection.executemany(
        "INSERT INTO agent_tasks (id, timestamp, original_prompt, transcribed_prompt, status) "
        "VALUES (?, '2026-10-22 12:00:00', 'p', 'p', ?)",
        list(rows.items()),
    )
    connection.commit()
    connection.close()


def _start_run(repository, schedule_id: str, agent_task_id: str | None, minute: int):
    run = asyncio.run(repository.create_scheduled_run(schedule_id, f"2026-10-22T12:{minute:02d}:00+00:00"))
    run_id = run["id"] if isinstance(run, dict) else run
    asyncio.run(repository.update_scheduled_run(run_id, status="running", agent_task_id=agent_task_id))
    return run_id


def test_active_runs_report_the_status_of_their_agent_task(tmp_path):
    path = str(tmp_path / "active.db")
    _create_tables(path)
    _add_agent_tasks_table(path, {"task-waiting": "awaiting_user_input", "task-working": "processing"})
    repository = ScheduledAgentTaskRepository(path)
    schedule = _create(repository)
    waiting = _start_run(repository, schedule["id"], "task-waiting", 0)
    working = _start_run(repository, schedule["id"], "task-working", 1)
    unlinked = _start_run(repository, schedule["id"], None, 2)

    by_run = {item["run_id"]: item for item in asyncio.run(repository.list_active_runs())}

    assert by_run[waiting]["agent_task_status"] == "awaiting_user_input"
    assert by_run[working]["agent_task_status"] == "processing"
    assert by_run[unlinked]["agent_task_status"] is None
    assert by_run[unlinked]["title"] == "Check email"
