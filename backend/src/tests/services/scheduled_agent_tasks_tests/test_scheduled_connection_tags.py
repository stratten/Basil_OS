"""A scheduled task can be tied to Connections (MCP), the way it can be given reference files."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

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
    scheduled_connection_tags as tags,
    scheduled_run_execution as sre,
)


def _record(connection_id="conn-gmail", name="Gmail", *, enabled=True, status="healthy", description=None):
    return SimpleNamespace(
        id=connection_id,
        friendly_name=name,
        enabled=enabled,
        last_connection_status=status,
        description=description,
    )


@pytest.fixture
def connections(monkeypatch):
    """The registered connections the helpers see. Replace the list inside a test to change them."""
    registered = [_record(), _record("conn-slack", "Slack", description="Acme workspace")]
    monkeypatch.setattr(tags, "_connection_records", lambda: list(registered))
    return registered


# --- storage -------------------------------------------------------------------------------------


def _create_tables(path: str) -> None:
    connection = sqlite3.connect(path)
    for statement in get_schema_statements():
        if "create table if not exists scheduled_agent_task" in statement.lower():
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


def test_a_schedule_stores_unique_connection_ids_in_the_order_given(repository):
    created = _create(repository, connection_ids=["conn-slack", " conn-gmail ", "conn-slack", "", "   "])

    assert created["connection_ids"] == ["conn-slack", "conn-gmail"]
    assert asyncio.run(repository.get_scheduled_agent_task(created["id"]))["connection_ids"] == ["conn-slack", "conn-gmail"]


def test_a_schedule_without_connections_reads_back_as_an_empty_list(repository):
    assert _create(repository)["connection_ids"] == []
    assert _create(repository, connection_ids=None)["connection_ids"] == []


def test_update_leaves_the_connections_alone_replaces_them_or_clears_them(repository):
    schedule_id = _create(repository, connection_ids=["conn-gmail"])["id"]

    untouched = asyncio.run(repository.update_scheduled_agent_task(schedule_id, title="Renamed"))
    assert untouched["connection_ids"] == ["conn-gmail"]

    replaced = asyncio.run(repository.update_scheduled_agent_task(schedule_id, connection_ids=["conn-slack"]))
    assert replaced["connection_ids"] == ["conn-slack"]

    cleared = asyncio.run(repository.update_scheduled_agent_task(schedule_id, connection_ids=[]))
    assert cleared["connection_ids"] == []


def test_connection_ids_do_not_disturb_reference_paths_or_the_model(repository):
    created = _create(repository, reference_paths=["/tmp/a.txt"], model_id="claude-haiku", connection_ids=["conn-gmail"])

    assert created["reference_paths"] == ["/tmp/a.txt"]
    assert created["model_id"] == "claude-haiku"
    assert created["connection_ids"] == ["conn-gmail"]


def test_existing_databases_gain_the_column_and_keep_their_schedules(tmp_path):
    path = str(tmp_path / "old.db")
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE scheduled_agent_tasks (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, agent_task_text TEXT NOT NULL, schedule_type TEXT NOT NULL,
            schedule_config TEXT NOT NULL, timezone TEXT DEFAULT 'UTC', is_active BOOLEAN DEFAULT TRUE,
            source_type TEXT DEFAULT 'manual', reference_paths TEXT NOT NULL DEFAULT '[]', model_id TEXT,
            next_run_at TIMESTAMP, last_run_at TIMESTAMP, last_status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE scheduled_agent_task_runs (
            id TEXT PRIMARY KEY, scheduled_agent_task_id TEXT NOT NULL, agent_task_id TEXT,
            scheduled_for TIMESTAMP NOT NULL, started_at TIMESTAMP, completed_at TIMESTAMP,
            status TEXT NOT NULL DEFAULT 'scheduled', error_message TEXT, notice TEXT,
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

    old = asyncio.run(ScheduledAgentTaskRepository(path).get_scheduled_agent_task("old-1"))
    assert old["connection_ids"] == []
    assert old["title"] == "Old"


# --- checking the tagged connections ------------------------------------------------------------


def test_normalize_drops_blanks_and_duplicates_and_non_strings():
    assert tags.normalize_connection_ids(["a", " a ", "", None, 3, "b"]) == ["a", "b"]
    assert tags.normalize_connection_ids(None) == []


def test_unknown_ids_are_the_ones_no_connection_matches(connections):
    assert tags.unknown_connection_ids(["conn-gmail", "conn-gone"]) == ["conn-gone"]
    assert tags.unknown_connection_ids([]) == []


def test_usable_connections_have_no_blocker_and_are_listed_for_the_prompt(connections):
    assessment = tags.assess_connection_tags(["conn-gmail", "conn-slack"])

    assert tags.connection_tag_blocker(assessment) is None
    assert [record.friendly_name for record in assessment.records] == ["Gmail", "Slack"]


def test_a_removed_connection_blocks_the_run(connections):
    assessment = tags.assess_connection_tags(["conn-gmail", "conn-gone"])

    blocker = tags.connection_tag_blocker(assessment)
    assert "conn-gone" in blocker
    assert "removed" in blocker
    assert [record.id for record in assessment.records] == ["conn-gmail"]


def test_a_switched_off_connection_blocks_the_run(connections):
    connections[0].enabled = False

    blocker = tags.connection_tag_blocker(tags.assess_connection_tags(["conn-gmail"]))

    assert blocker == "The Gmail connection is switched off. Turn it on in Settings, or edit the schedule."


@pytest.mark.parametrize("status", ["needs_reconnect", "token_unavailable"])
def test_a_connection_that_needs_signing_in_again_blocks_the_run(connections, status):
    connections[1].last_connection_status = status

    blocker = tags.connection_tag_blocker(tags.assess_connection_tags(["conn-slack"]))

    assert blocker == "The Slack connection needs to be signed in again. Reconnect it in Settings."


@pytest.mark.parametrize("status", [None, "healthy", "error"])
def test_other_statuses_do_not_block_the_run(connections, status):
    connections[0].last_connection_status = status

    assert tags.connection_tag_blocker(tags.assess_connection_tags(["conn-gmail"])) is None


def test_every_problem_is_reported_in_one_message(connections):
    connections[0].enabled = False

    blocker = tags.connection_tag_blocker(tags.assess_connection_tags(["conn-gmail", "conn-gone"]))

    assert "Gmail connection is switched off" in blocker
    assert "removed" in blocker


def test_the_prompt_block_names_each_connection_with_its_id_and_description(connections):
    block = tags.render_connection_tag_block(tags.assess_connection_tags(["conn-gmail", "conn-slack"]).records)

    assert block.startswith("CONNECTIONS FOR THIS SCHEDULE:")
    assert "- Gmail: connection_id `conn-gmail`" in block
    assert "- Slack (Acme workspace): connection_id `conn-slack`" in block
    assert "approval policy still applies" in block
    # A failing connection must be reported, never silently replaced by local Mail or AppleScript.
    assert "Do not route around these connections" in block
    assert "AppleScript" in block
    assert "user_action_required" in block


def test_no_connections_means_no_prompt_block():
    assert tags.render_connection_tag_block([]) == ""


# --- routes --------------------------------------------------------------------------------------


@pytest.fixture
def stub_service(monkeypatch):
    service = SimpleNamespace(
        create_scheduled_agent_task=AsyncMock(side_effect=lambda **kwargs: _item(kwargs["connection_ids"])),
        update_scheduled_agent_task=AsyncMock(side_effect=lambda _id, updates: _item(updates.get("connection_ids"))),
    )
    monkeypatch.setattr(schedule_routes, "ScheduledAgentTaskService", lambda: service)
    return service


def _item(connection_ids=None):
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
        "connection_ids": connection_ids or [],
        "model_id": None,
        "created_at": "2026-10-19T12:00:00",
        "updated_at": "2026-10-19T12:00:00",
    }


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
async def test_create_passes_cleaned_known_connection_ids_to_the_service(connections, stub_service):
    created = await schedule_routes.create_scheduled_agent_task(
        _create_request(connection_ids=[" conn-gmail ", "conn-gmail", "conn-slack"])
    )

    assert stub_service.create_scheduled_agent_task.await_args.kwargs["connection_ids"] == ["conn-gmail", "conn-slack"]
    assert created.connection_ids == ["conn-gmail", "conn-slack"]


@pytest.mark.asyncio
async def test_create_without_connections_passes_an_empty_list(connections, stub_service):
    created = await schedule_routes.create_scheduled_agent_task(_create_request())

    assert stub_service.create_scheduled_agent_task.await_args.kwargs["connection_ids"] == []
    assert created.connection_ids == []


@pytest.mark.asyncio
async def test_an_unknown_connection_is_refused_on_create_and_update(connections, stub_service):
    with pytest.raises(HTTPException) as on_create:
        await schedule_routes.create_scheduled_agent_task(_create_request(connection_ids=["conn-gone"]))
    with pytest.raises(HTTPException) as on_update:
        await schedule_routes.update_scheduled_agent_task(
            "schedule-1", ScheduledAgentTaskUpdateRequest(connection_ids=["conn-gmail", "conn-gone"])
        )

    assert on_create.value.status_code == 422
    assert on_update.value.status_code == 422
    stub_service.create_scheduled_agent_task.assert_not_awaited()
    stub_service.update_scheduled_agent_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_distinguishes_leave_alone_from_clear(connections, stub_service):
    await schedule_routes.update_scheduled_agent_task("schedule-1", ScheduledAgentTaskUpdateRequest(title="Renamed"))
    left_alone = stub_service.update_scheduled_agent_task.await_args.args[1]
    await schedule_routes.update_scheduled_agent_task("schedule-1", ScheduledAgentTaskUpdateRequest(connection_ids=[]))
    cleared = stub_service.update_scheduled_agent_task.await_args.args[1]
    await schedule_routes.update_scheduled_agent_task(
        "schedule-1", ScheduledAgentTaskUpdateRequest(connection_ids=["conn-slack"])
    )
    chosen = stub_service.update_scheduled_agent_task.await_args.args[1]

    assert "connection_ids" not in left_alone
    assert cleared["connection_ids"] == []
    assert chosen["connection_ids"] == ["conn-slack"]


def test_the_response_model_defaults_to_no_connections():
    assert ScheduledAgentTaskItem(**_item(["conn-gmail"])).connection_ids == ["conn-gmail"]
    legacy = _item()
    legacy.pop("connection_ids")
    assert ScheduledAgentTaskItem(**legacy).connection_ids == []


# --- running a schedule ----------------------------------------------------------------------------


def _runner_harness(monkeypatch, *, connection_ids):
    submission_service = SimpleNamespace(
        process_agent_task_direct=AsyncMock(return_value={"success": False, "message": "stop here"}),
        broadcast=AsyncMock(),
    )
    monkeypatch.setattr("api.main.app", SimpleNamespace(state=SimpleNamespace(agent_task_submission_service=submission_service)))
    monkeypatch.setattr(sre, "_prevent_idle_system_sleep_for_scheduled_run", lambda **_kwargs: nullcontext())
    finalize = AsyncMock(return_value={"status": "failed", "next_run_at": None})
    monkeypatch.setattr(sre.scheduled_run_lifecycle, "finalize_run_after_execution", finalize)
    schedule = {
        "is_active": True,
        "agent_task_text": "Check my inbox",
        "title": "Check email",
        "reference_paths": [],
        "model_id": None,
    }
    if connection_ids is not None:
        schedule["connection_ids"] = connection_ids
    repo = SimpleNamespace(
        get_scheduled_run=AsyncMock(return_value={"status": "scheduled"}),
        get_scheduled_agent_task=AsyncMock(return_value=schedule),
        update_scheduled_run=AsyncMock(),
        claim_scheduled_run=AsyncMock(return_value=True),
    )
    return SimpleNamespace(submission=submission_service, repo=repo, finalize=finalize)


@pytest.mark.asyncio
async def test_a_run_tells_the_agent_which_connections_to_use_and_keeps_the_prompt_as_written(monkeypatch, connections):
    harness = _runner_harness(monkeypatch, connection_ids=["conn-gmail"])

    await sre.execute_scheduled_run(harness.repo, SimpleNamespace(), "schedule-1", "run-1")

    kwargs = harness.submission.process_agent_task_direct.await_args.kwargs
    assert kwargs["agent_task"].startswith("Check my inbox\n\nCONNECTIONS FOR THIS SCHEDULE:")
    assert "connection_id `conn-gmail`" in kwargs["agent_task"]
    assert kwargs["display_prompt_markdown"] == "Check my inbox"
    assert kwargs["origin_type"] == "scheduled_task"
    # The run keeps the connections it was told to use, so its own view can list them.
    assert kwargs["connection_ids"] == ["conn-gmail"]


@pytest.mark.asyncio
async def test_a_run_with_no_tagged_connections_submits_the_prompt_unchanged(monkeypatch, connections):
    for connection_ids in (None, []):
        harness = _runner_harness(monkeypatch, connection_ids=connection_ids)

        await sre.execute_scheduled_run(harness.repo, SimpleNamespace(), "schedule-1", "run-1")

        kwargs = harness.submission.process_agent_task_direct.await_args.kwargs
        assert kwargs["agent_task"] == "Check my inbox"
        assert "display_prompt_markdown" not in kwargs
        assert "connection_ids" not in kwargs


@pytest.mark.asyncio
async def test_a_run_fails_with_a_plain_message_when_a_tagged_connection_is_unusable(monkeypatch, connections):
    connections[0].enabled = False
    harness = _runner_harness(monkeypatch, connection_ids=["conn-gmail", "conn-slack"])

    await sre.execute_scheduled_run(harness.repo, SimpleNamespace(), "schedule-1", "run-1")

    harness.submission.process_agent_task_direct.assert_not_awaited()
    kwargs = harness.finalize.await_args.kwargs
    assert kwargs["success"] is False
    assert kwargs["error_message"] == "The Gmail connection is switched off. Turn it on in Settings, or edit the schedule."


@pytest.mark.asyncio
async def test_a_failed_connection_lookup_neither_blocks_the_run_nor_changes_the_prompt(monkeypatch):
    def unavailable():
        raise RuntimeError("preferences unavailable")

    monkeypatch.setattr(tags, "_connection_records", unavailable)
    harness = _runner_harness(monkeypatch, connection_ids=["conn-gmail"])

    await sre.execute_scheduled_run(harness.repo, SimpleNamespace(), "schedule-1", "run-1")

    kwargs = harness.submission.process_agent_task_direct.await_args.kwargs
    assert kwargs["agent_task"] == "Check my inbox"
    assert "display_prompt_markdown" not in kwargs
    assert "connection_ids" not in kwargs


# --- showing a run's connections beside its reference files ---------------------------------------


def _task(artifacts):
    return SimpleNamespace(accumulated_artifacts=artifacts)


def test_a_runs_connections_are_listed_with_their_current_names(connections):
    from api.routes.agent_tasks.utils import extract_connection_references

    references = extract_connection_references(_task({"connection_ids": ["conn-slack", "conn-gmail"], "reference_paths": ["/tmp/a.md"]}))

    assert references == [{"id": "conn-slack", "name": "Slack"}, {"id": "conn-gmail", "name": "Gmail"}]


def test_a_removed_connection_stays_listed_without_a_name(connections):
    from api.routes.agent_tasks.utils import extract_connection_references

    assert extract_connection_references(_task({"connection_ids": ["conn-gone"]})) == [{"id": "conn-gone", "name": None}]


@pytest.mark.parametrize("artifacts", [None, {}, {"connection_ids": []}, {"connection_ids": "conn-gmail"}, {"connection_ids": [None, "", 3]}, "not a dict"])
def test_a_run_without_usable_connection_ids_lists_none(connections, artifacts):
    from api.routes.agent_tasks.utils import extract_connection_references

    assert extract_connection_references(_task(artifacts)) == []


def test_an_unreadable_connection_list_keeps_the_ids_and_drops_only_the_names(monkeypatch):
    from api.routes.agent_tasks.utils import extract_connection_references

    def unavailable():
        raise RuntimeError("preferences unavailable")

    monkeypatch.setattr(tags, "_connection_records", unavailable)

    assert extract_connection_references(_task({"connection_ids": ["conn-gmail"]})) == [{"id": "conn-gmail", "name": None}]


def test_the_history_models_default_to_no_connection_references():
    from api.routes.agent_tasks.models import AgentTaskChainItem, AgentTaskDetailResponse, ConnectionReferenceResponse

    assert AgentTaskChainItem.model_fields["connection_references"].default == []
    assert AgentTaskDetailResponse.model_fields["connection_references"].default == []
    assert ConnectionReferenceResponse(id="conn-gmail").name is None
