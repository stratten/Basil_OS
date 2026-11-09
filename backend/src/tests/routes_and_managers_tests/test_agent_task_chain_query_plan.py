"""The per-chain row fetches must stay index-driven and return exactly what the old COALESCE form returned."""

import sqlite3
from pathlib import Path

import pytest
import pytest_asyncio

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService

COALESCE_QUERY = """
    SELECT id FROM agent_tasks
    WHERE COALESCE(root_task_id, id) = ?
    ORDER BY chain_sequence_number ASC, timestamp ASC, id ASC
"""
INDEXED_QUERY = """
    SELECT id FROM agent_tasks
    WHERE root_task_id = ? OR (root_task_id IS NULL AND id = ?)
    ORDER BY chain_sequence_number ASC, timestamp ASC, id ASC
"""
SOURCE_ROOT = Path(__file__).resolve().parents[2] / "api" / "core" / "knowledge" / "sqlite" / "sqlite_knowledge_service_component_services"
FILES_THAT_MUST_USE_THE_INDEXED_FORM = [
    SOURCE_ROOT / "agent_tasks" / "mutations" / "root_summary.py",
    SOURCE_ROOT / "agent_tasks" / "search_matches.py",
    SOURCE_ROOT / "schema_management" / "agent_tasks" / "summary_backfill.py",
]


@pytest_asyncio.fixture
async def database_path(tmp_path):
    path = tmp_path / "chain_query_plan.db"
    database = SQLiteKnowledgeService(path)
    for chain in ("a", "b", "c"):
        previous = None
        for sequence in range(3):
            task_id = f"{chain}{sequence}"
            await database.store_agent_task(
                agent_task_id=task_id,
                original_prompt=f"prompt {task_id}",
                transcribed_prompt=f"prompt {task_id}",
                status="completed",
                root_task_id=None if sequence == 0 else f"{chain}0",
                previous_task_id=previous,
                chain_sequence_number=sequence,
            )
            previous = task_id
    await database.store_agent_task(
        agent_task_id="solo",
        original_prompt="solo",
        transcribed_prompt="solo",
        status="completed",
    )
    return path


def _plan(connection, query, parameters):
    return [row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + query, parameters).fetchall()]


@pytest.mark.asyncio
async def test_indexed_form_returns_the_same_ids_in_the_same_order_for_every_task_id(database_path):
    connection = sqlite3.connect(database_path)
    all_ids = [row[0] for row in connection.execute("SELECT id FROM agent_tasks").fetchall()]
    assert len(all_ids) == 10

    for task_id in all_ids + ["does-not-exist"]:
        old = connection.execute(COALESCE_QUERY, (task_id,)).fetchall()
        new = connection.execute(INDEXED_QUERY, (task_id, task_id)).fetchall()
        assert new == old, task_id
    assert [row[0] for row in connection.execute(INDEXED_QUERY, ("a0", "a0")).fetchall()] == ["a0", "a1", "a2"]
    assert [row[0] for row in connection.execute(INDEXED_QUERY, ("solo", "solo")).fetchall()] == ["solo"]
    connection.close()


@pytest.mark.asyncio
async def test_indexed_form_never_scans_the_whole_table_while_the_old_form_does(database_path):
    connection = sqlite3.connect(database_path)

    old_plan = _plan(connection, COALESCE_QUERY, ("a0",))
    new_plan = _plan(connection, INDEXED_QUERY, ("a0", "a0"))

    assert any(detail.startswith("SCAN agent_tasks") for detail in old_plan), old_plan
    assert not any(detail.startswith("SCAN agent_tasks") for detail in new_plan), new_plan
    assert any("USING" in detail and "INDEX" in detail for detail in new_plan), new_plan
    connection.close()


@pytest.mark.parametrize("path", FILES_THAT_MUST_USE_THE_INDEXED_FORM, ids=lambda path: path.name)
def test_the_three_per_chain_fetches_use_the_indexed_form(path):
    source = path.read_text()

    assert "COALESCE(root_task_id, id) = ?" not in source
    assert "root_task_id = ? OR (root_task_id IS NULL AND id = ?)" in source
