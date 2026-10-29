import sqlite3
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.list_filters import (
    AgentTaskListFilters,
    build_filter_conditions,
)
from api.routes.agent_tasks import history_routes


async def _store(database, task_id, *, status="completed", origin_type=None, app_name=None, root_task_id=None,
                 previous_task_id=None, sequence=0):
    await database.store_agent_task(
        agent_task_id=task_id,
        original_prompt=f"Quarterly report {task_id}",
        transcribed_prompt=f"Quarterly report {task_id}",
        status=status,
        app_name=app_name,
        origin_type=origin_type,
        root_task_id=root_task_id,
        previous_task_id=previous_task_id,
        chain_sequence_number=sequence,
    )


def _set_activity(database, task_id, when, file_count=0):
    with sqlite3.connect(database.db_path) as conn:
        conn.execute(
            "UPDATE agent_tasks SET timestamp = ?, last_turn_timestamp = ?, file_count = ? WHERE id = ?",
            (when, when, file_count, task_id),
        )


def _ids(summaries):
    return sorted(summary["id"] for summary in summaries)


@pytest_asyncio.fixture
async def database(tmp_path):
    database = SQLiteKnowledgeService(tmp_path / "filters.db")
    await _store(database, "direct-done", app_name="Safari")
    await _store(database, "conv-failed", status="failed", origin_type="conversation", app_name="Mail")
    await _store(database, "todo-running", status="processing", origin_type="todo_workspace")
    await _store(database, "meeting-waiting", status="awaiting_user_input", origin_type="meeting", app_name="Zoom Meetings")
    await _store(database, "sched-origin", origin_type="scheduled_task")
    await _store(database, "sched-run")
    await _store(database, "multi")
    await _store(database, "multi-fu", root_task_id="multi", previous_task_id="multi", sequence=1)
    with sqlite3.connect(database.db_path) as conn:
        conn.execute(
            "INSERT INTO scheduled_agent_task_runs (id, scheduled_agent_task_id, agent_task_id, scheduled_for) "
            "VALUES ('run-1', 'sched-definition', 'sched-run', '2026-03-01 08:00:00')"
        )
    for index, task_id in enumerate(
        ["direct-done", "conv-failed", "todo-running", "meeting-waiting", "sched-origin", "sched-run", "multi", "multi-fu"]
    ):
        _set_activity(database, task_id, f"2026-03-{10 + index:02d} 12:00:00", file_count=2 if task_id == "direct-done" else 0)
    return database


async def _list(database, **filter_kwargs):
    return await database.agent_task_service.list_recent_agent_task_summaries(
        limit=50, offset=0, archived=False, filters=AgentTaskListFilters(**filter_kwargs)
    )


async def _search(database, query="quarterly", **filter_kwargs):
    return await database.agent_task_service.search_agent_task_summaries(
        query=query, limit=50, offset=0, archived=False, filters=AgentTaskListFilters(**filter_kwargs)
    )


ALL_ROOTS = ["conv-failed", "direct-done", "meeting-waiting", "multi", "sched-origin", "sched-run", "todo-running"]


@pytest.mark.asyncio
async def test_no_filters_returns_every_root_chain_in_both_views(database):
    assert _ids(await _list(database)) == ALL_ROOTS
    assert _ids(await _search(database)) == ALL_ROOTS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filter_kwargs, expected",
    [
        ({"source": "direct"}, ["direct-done", "multi", "sched-run"]),
        ({"source": "conversation"}, ["conv-failed"]),
        ({"source": "todo"}, ["todo-running"]),
        ({"source": "meeting"}, ["meeting-waiting"]),
        ({"source": "scheduled"}, ["sched-origin", "sched-run"]),
        ({"status": "completed"}, ["direct-done", "multi", "sched-origin", "sched-run"]),
        ({"status": "failed"}, ["conv-failed"]),
        ({"status": "active"}, ["meeting-waiting", "todo-running"]),
        ({"app_contains": "SAF"}, ["direct-done"]),
        ({"app_contains": "mail"}, ["conv-failed"]),
        ({"has_documents": True}, ["direct-done"]),
        ({"has_documents": False}, [task for task in ALL_ROOTS if task != "direct-done"]),
        ({"multi_turn": True}, ["multi"]),
        ({"multi_turn": False}, [task for task in ALL_ROOTS if task != "multi"]),
    ],
)
async def test_each_filter_alone_narrows_the_list_and_the_search_the_same_way(database, filter_kwargs, expected):
    assert _ids(await _list(database, **filter_kwargs)) == expected
    assert _ids(await _search(database, **filter_kwargs)) == expected


@pytest.mark.asyncio
async def test_filters_combine_with_and(database):
    assert _ids(await _list(database, source="direct", status="completed", has_documents=True)) == ["direct-done"]
    assert await _list(database, source="conversation", status="completed") == []
    assert await _search(database, source="meeting", has_documents=True) == []


@pytest.mark.asyncio
async def test_a_blank_query_keeps_every_filter_instead_of_dropping_them(database):
    kwargs = dict(
        start_date=datetime(2026, 3, 12, 0, 0, tzinfo=timezone.utc),
        end_date=datetime(2026, 3, 14, 23, 59, tzinfo=timezone.utc),
        app_contains="zoom",
    )
    assert _ids(await _search(database, query="", **kwargs)) == ["meeting-waiting"]
    assert _ids(await _search(database, query="   ", **kwargs)) == ["meeting-waiting"]
    assert _ids(await _search(database, query="!!!", **kwargs)) == ["meeting-waiting"]


@pytest.mark.asyncio
async def test_the_older_date_status_and_app_arguments_still_apply_with_a_blank_query(database):
    results = await database.agent_task_service.search_agent_task_summaries(
        query="", status="failed", app_name="Mail", start_date=datetime(2026, 3, 1, tzinfo=timezone.utc), limit=50, offset=0,
    )
    assert _ids(results) == ["conv-failed"]
    assert await database.agent_task_service.search_agent_task_summaries(
        query="", status="failed", app_name="Safari", limit=50, offset=0
    ) == []


@pytest.mark.asyncio
async def test_date_bounds_are_inclusive_and_use_last_activity(database):
    # The multi chain's last activity is its follow-up, stamped 2026-03-17, while its own row is 2026-03-16.
    with sqlite3.connect(database.db_path) as conn:
        conn.execute("UPDATE agent_tasks SET last_turn_timestamp = '2026-03-20 09:00:00' WHERE id = 'multi'")
    exactly_one_day = await _list(
        database,
        start_date=datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc),
        end_date=datetime(2026, 3, 10, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert _ids(exactly_one_day) == ["direct-done"]
    late = await _list(database, start_date=datetime(2026, 3, 19, tzinfo=timezone.utc))
    assert _ids(late) == ["multi"]
    early = await _list(database, end_date=datetime(2026, 3, 11, 23, 59, tzinfo=timezone.utc))
    assert _ids(early) == ["conv-failed", "direct-done"]


@pytest.mark.asyncio
async def test_date_bounds_honor_the_time_zone_offset_and_the_stored_iso_format(database):
    with sqlite3.connect(database.db_path) as conn:
        conn.execute("UPDATE agent_tasks SET last_turn_timestamp = '2026-03-10T23:30:00.000Z' WHERE id = 'direct-done'")
    start = datetime.fromisoformat("2026-03-11T00:00:00+01:00")  # 2026-03-10 23:00 UTC
    assert "direct-done" in _ids(await _list(database, start_date=start))
    later = datetime.fromisoformat("2026-03-11T00:45:00+01:00")  # 2026-03-10 23:45 UTC
    assert "direct-done" not in _ids(await _list(database, start_date=later))


@pytest.mark.asyncio
async def test_filters_respect_the_archived_scope(database):
    await database.agent_task_service.archive_agent_task_chain("direct-done")
    assert await _list(database, source="direct", has_documents=True) == []
    archived = await database.agent_task_service.list_recent_agent_task_summaries(
        limit=50, offset=0, archived=True, filters=AgentTaskListFilters(has_documents=True)
    )
    assert _ids(archived) == ["direct-done"]


@pytest.mark.asyncio
async def test_pagination_applies_after_filtering(database):
    filters = AgentTaskListFilters(status="completed")
    first = await database.agent_task_service.list_recent_agent_task_summaries(limit=2, offset=0, archived=False, filters=filters)
    second = await database.agent_task_service.list_recent_agent_task_summaries(limit=2, offset=2, archived=False, filters=filters)
    third = await database.agent_task_service.list_recent_agent_task_summaries(limit=2, offset=4, archived=False, filters=filters)
    assert len(first) == 2 and len(second) == 2 and third == []
    assert _ids(first + second) == ["direct-done", "multi", "sched-origin", "sched-run"]


@pytest.mark.asyncio
async def test_percent_and_underscore_in_the_app_text_are_literal(database):
    assert await _list(database, app_contains="%") == []
    assert await _list(database, app_contains="_") == []


def test_an_unsupported_source_is_rejected_before_it_reaches_sql():
    with pytest.raises(ValueError):
        build_filter_conditions(AgentTaskListFilters(source="unknown"))


@pytest.mark.asyncio
async def test_history_routes_pass_the_filters_through(database):
    listed = await history_routes.get_agent_task_history(
        limit=50, offset=0, status="active", archived=False, source="todo", knowledge_service=database
    )
    assert [item.id for item in listed.agentTasks] == ["todo-running"]

    searched = await history_routes.search_agent_task_history(
        query="quarterly", status=None, app="zoom", days=None, limit=50, offset=0, archived=False,
        turns="single", has_documents=False, knowledge_service=database,
    )
    assert [item.id for item in searched.agentTasks] == ["meeting-waiting"]

    scheduled = await history_routes.get_agent_task_history(
        limit=50, offset=0, status=None, archived=False, source="scheduled", knowledge_service=database
    )
    assert sorted(item.id for item in scheduled.agentTasks) == ["sched-origin", "sched-run"]
