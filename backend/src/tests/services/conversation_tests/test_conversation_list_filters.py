import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.core.knowledge.sqlite import conversation_repository as repository_module
from api.core.knowledge.sqlite.conversation_list_filters import (
    ConversationListFilters,
    build_conversation_filter_conditions,
)
from api.core.knowledge.sqlite.conversation_repository import ConversationRepository


@pytest.fixture
def repository(tmp_path):
    return ConversationRepository(tmp_path / "conversation-filters.db")


def seed_conversation(repository, conversation_id, updated_at, user_messages=1, title=None):
    with repository_module.get_sync_connection(repository.db_path) as connection:
        connection.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conversation_id, title or f"Title {conversation_id}", updated_at, updated_at),
        )
        messages = [("system", "hidden")]
        for index in range(user_messages):
            messages.append(("user", f"question {index} for {conversation_id}"))
            messages.append(("assistant", f"answer {index} for {conversation_id}"))
        for index, (role, content) in enumerate(messages):
            connection.execute(
                "INSERT INTO conversation_messages (id, conversation_id, role, content, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (f"{conversation_id}-m{index}", conversation_id, role, content, updated_at),
            )


def seed_task(repository, task_id, conversation_id, status, when, root_task_id=None):
    root = root_task_id or task_id
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "INSERT INTO agent_tasks (id, original_prompt, transcribed_prompt, status, origin_type, origin_id, "
            "root_task_id, timestamp, last_interaction_timestamp) VALUES (?, 'prompt', 'prompt', ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                status,
                "conversation" if root_task_id is None else None,
                conversation_id if root_task_id is None else None,
                root,
                when,
                when,
            ),
        )


@pytest.fixture
def seeded(repository):
    seed_conversation(repository, "plain-single", "2026-03-01 09:00:00", user_messages=1)
    seed_conversation(repository, "plain-multi", "2026-03-02 09:00:00", user_messages=3)
    seed_conversation(repository, "working", "2026-03-03 09:00:00", user_messages=1)
    seed_task(repository, "task-working", "working", "processing", "2026-03-03 09:00:00")
    seed_conversation(repository, "broken", "2026-03-04 09:00:00", user_messages=2)
    seed_task(repository, "task-broken", "broken", "failed", "2026-03-04 09:00:00")
    seed_conversation(repository, "done", "2026-03-05 09:00:00", user_messages=1)
    seed_task(repository, "task-done", "done", "completed", "2026-03-05 09:00:00")
    seed_conversation(repository, "recovered", "2026-03-06 09:00:00", user_messages=1)
    seed_task(repository, "task-recovered-1", "recovered", "failed", "2026-03-06 09:00:00")
    seed_task(repository, "task-recovered-2", "recovered", "completed", "2026-03-06 10:00:00", root_task_id="task-recovered-1")
    seed_conversation(repository, "retry-running", "2026-03-07 09:00:00", user_messages=1)
    seed_task(repository, "task-retry-1", "retry-running", "failed", "2026-03-07 09:00:00")
    seed_task(repository, "task-retry-2", "retry-running", "processing", "2026-03-07 10:00:00", root_task_id="task-retry-1")
    return repository


async def page_ids(repository, **filters):
    page = await repository.list_conversation_page(
        query=filters.pop("query", None),
        limit=50,
        filters=ConversationListFilters(**filters),
    )
    return sorted(item["id"] for item in page["conversations"])


ALL_IDS = sorted(["plain-single", "plain-multi", "working", "broken", "done", "recovered", "retry-running"])


@pytest.mark.asyncio
async def test_no_filters_returns_every_conversation(seeded):
    assert await page_ids(seeded) == ALL_IDS


@pytest.mark.asyncio
async def test_agent_work_none_and_any_partition_the_list(seeded):
    none_ids = await page_ids(seeded, agent_work="none")
    any_ids = await page_ids(seeded, agent_work="any")
    assert none_ids == ["plain-multi", "plain-single"]
    assert any_ids == sorted(["working", "broken", "done", "recovered", "retry-running"])
    assert sorted(none_ids + any_ids) == ALL_IDS


@pytest.mark.asyncio
async def test_agent_work_active_includes_a_running_follow_up_of_a_failed_chain(seeded):
    assert await page_ids(seeded, agent_work="active") == ["retry-running", "working"]


@pytest.mark.asyncio
async def test_agent_work_failed_requires_the_latest_finished_task_to_have_failed_and_nothing_running(seeded):
    assert await page_ids(seeded, agent_work="failed") == ["broken"]


@pytest.mark.asyncio
async def test_length_single_and_multi_count_user_messages_and_ignore_system_and_assistant_messages(seeded):
    assert await page_ids(seeded, length="multi") == ["broken", "plain-multi"]
    assert await page_ids(seeded, length="single") == sorted(
        ["plain-single", "working", "done", "recovered", "retry-running"]
    )


@pytest.mark.asyncio
async def test_conversation_with_no_user_message_counts_as_single(repository):
    with repository_module.get_sync_connection(repository.db_path) as connection:
        connection.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at) VALUES ('empty', 'Empty', '2026-03-01 09:00:00', '2026-03-01 09:00:00')"
        )
    assert await page_ids(repository, length="single") == ["empty"]
    assert await page_ids(repository, length="multi") == []


@pytest.mark.asyncio
async def test_date_range_is_inclusive_and_normalized_to_utc(seeded):
    start = datetime(2026, 3, 2, 9, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 3, 4, 9, 0, 0, tzinfo=timezone.utc)
    assert await page_ids(seeded, start_date=start, end_date=end) == ["broken", "plain-multi", "working"]
    assert await page_ids(seeded, start_date=end + timedelta(seconds=1), end_date=end + timedelta(days=1)) == ["done"]
    plus_two = timezone(timedelta(hours=2))
    assert await page_ids(
        seeded,
        start_date=datetime(2026, 3, 2, 11, 0, 0, tzinfo=plus_two),
        end_date=datetime(2026, 3, 2, 11, 0, 0, tzinfo=plus_two),
    ) == ["plain-multi"]


@pytest.mark.asyncio
async def test_start_after_end_returns_nothing(seeded):
    assert await page_ids(
        seeded,
        start_date=datetime(2026, 4, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 3, 1, tzinfo=timezone.utc),
    ) == []


@pytest.mark.asyncio
async def test_filters_combine_with_each_other_and_with_the_search_text(seeded):
    assert await page_ids(seeded, agent_work="any", length="multi") == ["broken"]
    assert await page_ids(seeded, agent_work="none", length="multi", query="plain-multi") == ["plain-multi"]
    assert await page_ids(seeded, agent_work="any", query="plain-multi") == []


@pytest.mark.asyncio
async def test_cursor_stays_valid_across_filtered_pages(seeded):
    filters = ConversationListFilters(agent_work="any")
    first = await seeded.list_conversation_page(query=None, limit=2, filters=filters)
    second = await seeded.list_conversation_page(query=None, limit=2, cursor=first["next_cursor"], filters=filters)
    third = await seeded.list_conversation_page(query=None, limit=2, cursor=second["next_cursor"], filters=filters)
    ids = [item["id"] for page in (first, second, third) for item in page["conversations"]]
    assert ids == ["retry-running", "recovered", "done", "broken", "working"]
    assert [first["has_more"], second["has_more"], third["has_more"]] == [True, True, False]


def test_unsupported_values_are_rejected_by_the_builder():
    with pytest.raises(ValueError):
        build_conversation_filter_conditions(ConversationListFilters(agent_work="sideways"))
    with pytest.raises(ValueError):
        build_conversation_filter_conditions(ConversationListFilters(length="huge"))


def test_empty_filters_add_no_conditions():
    assert build_conversation_filter_conditions(None) == ([], [])
    assert build_conversation_filter_conditions(ConversationListFilters()) == ([], [])


def _route_client():
    from api.services.conversation import conversation_routes

    captured = {}

    class FakeService:
        async def list_conversation_page(self, **kwargs):
            captured.update(kwargs)
            return {"conversations": [], "has_more": False, "next_cursor": None}

    class FakeSqlite:
        async def list_latest_agent_task_status_by_origins(self, origin_type, ids):
            return {}

    app = FastAPI()
    app.include_router(conversation_routes.router, prefix="/api/v1")
    app.dependency_overrides[conversation_routes.get_conversation_service] = lambda: FakeService()
    app.dependency_overrides[conversation_routes._get_sqlite_knowledge_service] = lambda: FakeSqlite()
    return TestClient(app), captured


def test_page_route_passes_the_filters_through():
    client, captured = _route_client()
    response = client.get(
        "/api/v1/conversation/page",
        params={
            "start_date": "2026-03-02T00:00:00Z",
            "end_date": "2026-03-03T23:59:59Z",
            "agent_work": "failed",
            "length": "multi",
        },
    )
    assert response.status_code == 200
    filters = captured["filters"]
    assert filters.agent_work == "failed"
    assert filters.length == "multi"
    assert filters.start_date.isoformat() == "2026-03-02T00:00:00+00:00"
    assert filters.end_date.isoformat() == "2026-03-03T23:59:59+00:00"


def test_page_route_rejects_unknown_filter_values():
    client, _ = _route_client()
    assert client.get("/api/v1/conversation/page", params={"agent_work": "sideways"}).status_code == 422
    assert client.get("/api/v1/conversation/page", params={"length": "huge"}).status_code == 422
