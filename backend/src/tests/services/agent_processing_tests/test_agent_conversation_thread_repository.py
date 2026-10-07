"""The conversation thread table: schema, upsert, read, and cleanup with the task chain."""

import sqlite3

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.mutations.delete_operations import (
    delete_agent_task,
)


async def _store(database, task_id, *, root_task_id=None, previous_task_id=None, sequence=0):
    await database.store_agent_task(
        agent_task_id=task_id,
        original_prompt=f"Request {task_id}",
        transcribed_prompt=f"Request {task_id}",
        status="completed",
        root_task_id=root_task_id,
        previous_task_id=previous_task_id,
        chain_sequence_number=sequence,
    )


async def _save(repo, task_id, root_task_id, *, family="f", count=1, messages_json="[]"):
    await repo.save_thread(
        agent_task_id=task_id,
        root_task_id=root_task_id,
        model_family=family,
        model_id="",
        format_version=1,
        message_count=count,
        messages_json=messages_json,
    )


def test_schema_creates_the_thread_table_and_index(tmp_path):
    database = SQLiteKnowledgeService(tmp_path / "threads.db")

    with sqlite3.connect(str(database.db_path)) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(agent_conversation_threads)")]
        indexes = [row[1] for row in conn.execute("PRAGMA index_list(agent_conversation_threads)")]

    assert columns == [
        "agent_task_id",
        "root_task_id",
        "model_family",
        "model_id",
        "format_version",
        "message_count",
        "messages_json",
        "created_at",
        "updated_at",
    ]
    assert "idx_agent_conversation_threads_root" in indexes


@pytest.mark.asyncio
async def test_thread_rows_upsert_and_read_back(tmp_path):
    database = SQLiteKnowledgeService(tmp_path / "threads.db")
    repo = database.agent_conversation_thread_repository

    await _save(repo, "t1", "t1", family="anthropic-chat", count=2)
    await _save(repo, "t1", "t1", family="neutral", count=4, messages_json='[{"type": "human"}]')
    row = await repo.get_thread("t1")

    assert row["model_family"] == "neutral"
    assert row["message_count"] == 4
    assert row["messages_json"] == '[{"type": "human"}]'
    assert row["created_at"] <= row["updated_at"]
    assert await repo.get_thread("missing") is None
    assert await repo.delete_threads([]) == 0
    assert await repo.delete_threads(["t1"]) == 1


@pytest.mark.asyncio
async def test_deleting_a_task_chain_deletes_its_threads_only(tmp_path):
    database = SQLiteKnowledgeService(tmp_path / "threads.db")
    repo = database.agent_conversation_thread_repository
    await _store(database, "root")
    await _store(database, "child", root_task_id="root", previous_task_id="root", sequence=1)
    await _store(database, "other")
    for task_id, root_task_id in (("root", "root"), ("child", "root"), ("other", "other")):
        await _save(repo, task_id, root_task_id)

    assert await delete_agent_task(str(database.db_path), "root", cascade=True) is True

    assert await repo.get_thread("root") is None
    assert await repo.get_thread("child") is None
    assert await repo.get_thread("other") is not None
