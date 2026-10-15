import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_tasks.migrations import (
    migrate_agent_tasks_table,
)
from api.routes.agent_tasks import core_routes, history_routes


async def _store(database, task_id, *, status="completed", root_task_id=None, previous_task_id=None, sequence=0, prompt=None):
    await database.store_agent_task(
        agent_task_id=task_id,
        original_prompt=prompt or f"Request {task_id}",
        transcribed_prompt=prompt or f"Request {task_id}",
        status=status,
        root_task_id=root_task_id,
        previous_task_id=previous_task_id,
        chain_sequence_number=sequence,
    )


def _archived_at(database, task_id):
    with sqlite3.connect(database.db_path) as conn:
        return conn.execute("SELECT archived_at FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()[0]


def _ids(summaries):
    return [summary["id"] for summary in summaries]


@pytest.fixture
def database(tmp_path):
    return SQLiteKnowledgeService(tmp_path / "archive.db")


def test_migration_adds_archived_at_and_its_index_idempotently(tmp_path):
    database = SQLiteKnowledgeService(tmp_path / "legacy.db")
    with sqlite3.connect(database.db_path) as conn:
        conn.execute("DROP INDEX IF EXISTS idx_agent_tasks_archived")
        conn.execute("ALTER TABLE agent_tasks DROP COLUMN archived_at")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_tasks)")}
        assert "archived_at" not in columns

        conn.row_factory = sqlite3.Row
        migrate_agent_tasks_table(conn)
        migrate_agent_tasks_table(conn)

        columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_tasks)")}
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(agent_tasks)")}
    assert "archived_at" in columns
    assert "idx_agent_tasks_archived" in indexes


def test_a_fresh_database_already_has_the_column_and_leaves_existing_rows_unarchived(tmp_path):
    database = SQLiteKnowledgeService(tmp_path / "fresh.db")
    with sqlite3.connect(database.db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(agent_tasks)")}
    assert "archived_at" in columns


@pytest.mark.asyncio
async def test_list_filters_archived_true_false_and_any(database):
    await _store(database, "kept")
    await _store(database, "shelved")

    assert await database.agent_task_service.archive_agent_task_chain("shelved") == "ok"

    service = database.agent_task_service
    assert _ids(await service.list_recent_agent_task_summaries(archived=False)) == ["kept"]
    assert _ids(await service.list_recent_agent_task_summaries(archived=True)) == ["shelved"]
    assert sorted(_ids(await service.list_recent_agent_task_summaries())) == ["kept", "shelved"]
    archived_summary = (await service.list_recent_agent_task_summaries(archived=True))[0]
    assert archived_summary["archived_at"] is not None
    assert (await service.list_recent_agent_task_summaries(archived=False))[0]["archived_at"] is None


@pytest.mark.asyncio
async def test_search_filters_archived_and_the_default_still_finds_archived_chains_for_recall(database):
    await _store(database, "kept", prompt="Quarterly budget review")
    await _store(database, "shelved", prompt="Quarterly budget archive")
    await database.agent_task_service.archive_agent_task_chain("shelved")
    service = database.agent_task_service

    assert _ids(await service.search_agent_task_summaries(query="quarterly", archived=False)) == ["kept"]
    assert _ids(await service.search_agent_task_summaries(query="quarterly", archived=True)) == ["shelved"]
    assert sorted(_ids(await service.search_agent_task_summaries(query="quarterly"))) == ["kept", "shelved"]
    assert _ids(await service.search_agent_task_summaries(query="  ", archived=True)) == ["shelved"]


@pytest.mark.asyncio
async def test_archiving_a_multi_turn_chain_marks_only_the_root_and_works_from_any_turn(database):
    await _store(database, "root")
    await _store(database, "leaf", root_task_id="root", previous_task_id="root", sequence=1)

    assert await database.agent_task_service.archive_agent_task_chain("leaf") == "ok"

    assert _archived_at(database, "root") is not None
    assert _archived_at(database, "leaf") is None
    assert await database.agent_task_service.list_recent_agent_task_summaries(archived=False) == []
    chain = await database.agent_task_service.get_agent_task_chain("root")
    assert [task.id for task in chain] == ["root", "leaf"]

    assert await database.agent_task_service.unarchive_agent_task_chain("leaf") == "ok"
    assert _archived_at(database, "root") is None
    assert _ids(await database.agent_task_service.list_recent_agent_task_summaries(archived=False)) == ["root"]


@pytest.mark.asyncio
async def test_archiving_twice_keeps_the_original_timestamp_and_unarchiving_an_unarchived_chain_is_a_no_op(database):
    await _store(database, "root")

    await database.agent_task_service.archive_agent_task_chain("root")
    first = _archived_at(database, "root")
    with sqlite3.connect(database.db_path) as conn:
        conn.execute("UPDATE agent_tasks SET archived_at = '2026-01-01 00:00:00' WHERE id = 'root'")
    await database.agent_task_service.archive_agent_task_chain("root")

    assert first is not None
    assert _archived_at(database, "root") == "2026-01-01 00:00:00"
    await database.agent_task_service.unarchive_agent_task_chain("root")
    assert await database.agent_task_service.unarchive_agent_task_chain("root") == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["processing", "routing", "awaiting_user_input", "paused", "capturing"])
async def test_a_chain_whose_latest_turn_is_active_cannot_be_archived(database, status):
    await _store(database, "root")
    await _store(database, "leaf", status=status, root_task_id="root", previous_task_id="root", sequence=1)

    assert await database.agent_task_service.archive_agent_task_chain("root") == "active"
    assert _archived_at(database, "root") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["completed", "failed", "canceled"])
async def test_a_chain_whose_latest_turn_is_terminal_can_be_archived(database, status):
    await _store(database, "root", status=status)

    assert await database.agent_task_service.archive_agent_task_chain("root") == "ok"


@pytest.mark.asyncio
async def test_unknown_tasks_report_not_found(database):
    assert await database.agent_task_service.archive_agent_task_chain("missing") == "not_found"
    assert await database.agent_task_service.unarchive_agent_task_chain("missing") == "not_found"


@pytest.mark.asyncio
async def test_a_new_follow_up_row_returns_the_archived_chain_to_the_main_list(database):
    await _store(database, "root")
    await database.agent_task_service.archive_agent_task_chain("root")
    assert _archived_at(database, "root") is not None

    await _store(database, "leaf", status="processing", root_task_id="root", previous_task_id="root", sequence=1)

    assert _archived_at(database, "root") is None
    assert _ids(await database.agent_task_service.list_recent_agent_task_summaries(archived=False)) == ["root"]


@pytest.mark.asyncio
async def test_status_updates_and_summary_recomputation_never_unarchive(database):
    await _store(database, "root", status="processing")
    with sqlite3.connect(database.db_path) as conn:
        conn.execute("UPDATE agent_tasks SET archived_at = '2026-01-01 00:00:00' WHERE id = 'root'")

    await database.agent_task_service.update_agent_task_status(agent_task_id="root", status="completed")
    await database.agent_task_service.update_execution_timeline("root", [{"type": "step", "content": "Done"}])

    assert _archived_at(database, "root") == "2026-01-01 00:00:00"


@pytest.mark.asyncio
async def test_archive_routes_return_ok_404_and_409(database):
    knowledge_service = SimpleNamespace(agent_task_service=database.agent_task_service)
    await _store(database, "done")
    await _store(database, "running", status="processing")

    archived = await core_routes.archive_agent_task("done", knowledge_service=knowledge_service)
    assert archived.success is True
    assert _archived_at(database, "done") is not None

    with pytest.raises(HTTPException) as active:
        await core_routes.archive_agent_task("running", knowledge_service=knowledge_service)
    assert active.value.status_code == 409
    assert active.value.detail == "Stop the task before archiving it."

    with pytest.raises(HTTPException) as missing:
        await core_routes.archive_agent_task("missing", knowledge_service=knowledge_service)
    assert missing.value.status_code == 404

    restored = await core_routes.unarchive_agent_task("done", knowledge_service=knowledge_service)
    assert restored.success is True
    assert _archived_at(database, "done") is None

    with pytest.raises(HTTPException) as missing_unarchive:
        await core_routes.unarchive_agent_task("missing", knowledge_service=knowledge_service)
    assert missing_unarchive.value.status_code == 404


@pytest.mark.asyncio
async def test_history_route_returns_unarchived_by_default_and_archived_on_request(database):
    await _store(database, "kept")
    await _store(database, "shelved")
    await database.agent_task_service.archive_agent_task_chain("shelved")

    default_response = await history_routes.get_agent_task_history(
        limit=50, offset=0, status=None, archived=False, knowledge_service=database
    )
    archived_response = await history_routes.get_agent_task_history(
        limit=50, offset=0, status=None, archived=True, knowledge_service=database
    )

    assert [item.id for item in default_response.agentTasks] == ["kept"]
    assert default_response.agentTasks[0].archived_at is None
    assert [item.id for item in archived_response.agentTasks] == ["shelved"]
    assert archived_response.agentTasks[0].archived_at is not None
    assert archived_response.agentTasks[0].model_dump()["archived_at"].endswith("Z")


@pytest.mark.asyncio
async def test_history_search_route_scopes_to_archived_chains(database):
    await _store(database, "kept", prompt="Quarterly budget review")
    await _store(database, "shelved", prompt="Quarterly budget archive")
    await database.agent_task_service.archive_agent_task_chain("shelved")

    kwargs = dict(
        query="quarterly", status=None, app=None, days=None, limit=50, offset=0, knowledge_service=database
    )
    default_response = await history_routes.search_agent_task_history(archived=False, **kwargs)
    archived_response = await history_routes.search_agent_task_history(archived=True, **kwargs)

    assert [item.id for item in default_response.agentTasks] == ["kept"]
    assert [item.id for item in archived_response.agentTasks] == ["shelved"]


@pytest.mark.asyncio
async def test_clarification_route_unarchives_before_adding_the_clarification():
    calls = []
    knowledge_service = SimpleNamespace(
        agent_task_service=SimpleNamespace(
            unarchive_agent_task_chain=AsyncMock(side_effect=lambda task_id: calls.append(("unarchive", task_id)) or "ok"),
        )
    )
    submission_service = SimpleNamespace(
        add_clarification=AsyncMock(side_effect=lambda **kwargs: calls.append(("clarify", kwargs["agent_task_id"])) or {"success": True})
    )

    response = await core_routes.add_clarification(
        "task-1",
        core_routes.AgentTaskClarificationRequest(agent_task_id="task-1", clarification_text="Use Q3"),
        service=submission_service,
        knowledge_service=knowledge_service,
    )

    assert response.success is True
    assert calls == [("unarchive", "task-1"), ("clarify", "task-1")]


@pytest.mark.asyncio
async def test_new_work_still_proceeds_when_the_unarchive_step_fails():
    knowledge_service = SimpleNamespace(
        agent_task_service=SimpleNamespace(unarchive_agent_task_chain=AsyncMock(side_effect=RuntimeError("database is locked")))
    )
    submission_service = SimpleNamespace(add_clarification=AsyncMock(return_value={"success": True}))

    response = await core_routes.add_clarification(
        "task-1",
        core_routes.AgentTaskClarificationRequest(agent_task_id="task-1", clarification_text="Use Q3"),
        service=submission_service,
        knowledge_service=knowledge_service,
    )

    assert response.success is True
    submission_service.add_clarification.assert_awaited_once()
