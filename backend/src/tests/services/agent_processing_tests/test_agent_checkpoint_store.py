"""Agent checkpoint write mode and startup pruning."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TypedDict

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, StateGraph

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.agent_processing.lifecycle.runtime.agent_checkpoint_store import (
    ExitDurabilityGraph,
    agent_checkpoint_database_path,
    prune_agent_checkpoints,
)


class _CounterState(TypedDict):
    value: int


def _counter_graph() -> StateGraph:
    graph = StateGraph(_CounterState)
    graph.add_node("first", lambda state: {"value": state["value"] + 1})
    graph.add_node("second", lambda state: {"value": state["value"] + 1})
    graph.set_entry_point("first")
    graph.add_edge("first", "second")
    graph.add_edge("second", END)
    return graph


def _thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _write_checkpoint_threads(checkpoint_db: Path, thread_ids: list[str]) -> None:
    with closing(sqlite3.connect(str(checkpoint_db), check_same_thread=False)) as conn:
        app = _counter_graph().compile(checkpointer=SqliteSaver(conn))
        for thread_id in thread_ids:
            app.invoke({"value": 0}, config=_thread_config(thread_id))


def _checkpoint_thread_ids(checkpoint_db: Path) -> set[str]:
    with closing(sqlite3.connect(str(checkpoint_db))) as conn:
        return {row[0] for row in conn.execute("SELECT thread_id FROM checkpoints UNION SELECT thread_id FROM writes")}


async def _store_task(service: SQLiteKnowledgeService, task_id: str, status: str, days_since_update: int) -> None:
    await service.store_agent_task(
        agent_task_id=task_id,
        original_prompt="Prompt",
        transcribed_prompt="Prompt",
        status=status,
    )
    with closing(sqlite3.connect(service.db_path)) as conn:
        conn.execute(
            "UPDATE agent_tasks SET updated_at = datetime('now', ?) WHERE id = ?",
            (f"-{days_since_update} days", task_id),
        )
        conn.commit()


class _RecordingGraph:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.marker = "passthrough"

    def astream(self, *args, **kwargs):
        self.calls.append(("astream", kwargs))
        return "stream"

    async def ainvoke(self, *args, **kwargs):
        self.calls.append(("ainvoke", kwargs))
        return {"done": True}


@pytest.mark.asyncio
async def test_exit_durability_wrapper_defaults_and_respects_explicit_mode() -> None:
    recorder = _RecordingGraph()
    graph = ExitDurabilityGraph(recorder)

    assert graph.astream({"value": 0}) == "stream"
    assert await graph.ainvoke({"value": 0}, durability="sync") == {"done": True}
    assert graph.marker == "passthrough"
    assert recorder.calls == [("astream", {"durability": "exit"}), ("ainvoke", {"durability": "sync"})]


@pytest.mark.asyncio
async def test_exit_durability_persists_only_the_final_checkpoint(tmp_path: Path) -> None:
    checkpoint_db = tmp_path / "checkpoints.sqlite"
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_db)) as saver:
        app = ExitDurabilityGraph(_counter_graph().compile(checkpointer=saver))
        result = await app.ainvoke({"value": 0}, config=_thread_config("exit-thread"))
        chunks = [chunk async for chunk in app.astream({"value": 5}, config=_thread_config("stream-thread"))]
        state = await app.aget_state(_thread_config("exit-thread"))

    assert result == {"value": 2}
    assert len(chunks) == 2
    assert state.values == {"value": 2}
    with closing(sqlite3.connect(str(checkpoint_db))) as conn:
        counts = dict(conn.execute("SELECT thread_id, COUNT(*) FROM checkpoints GROUP BY thread_id").fetchall())
        pending_writes = conn.execute("SELECT COUNT(*) FROM writes").fetchone()[0]
    assert counts == {"exit-thread": 1, "stream-thread": 1}
    assert pending_writes == 0


def test_checkpoint_path_follows_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert agent_checkpoint_database_path() == tmp_path / ".basil" / "agent_checkpoints.sqlite"


@pytest.mark.asyncio
async def test_prune_deletes_expired_terminal_and_orphan_threads_only(tmp_path: Path) -> None:
    service = SQLiteKnowledgeService(tmp_path / "knowledge.sqlite3")
    await _store_task(service, "old-completed", "completed", 8)
    await _store_task(service, "old-failed", "failed", 30)
    await _store_task(service, "old-canceled", "canceled", 8)
    await _store_task(service, "recent-completed", "completed", 1)
    await _store_task(service, "old-waiting", "awaiting_user_input", 30)
    await _store_task(service, "old-delegation", "awaiting_provider_delegation", 30)
    checkpoint_db = tmp_path / "checkpoints.sqlite"
    _write_checkpoint_threads(
        checkpoint_db,
        [
            "old-completed",
            "old-failed",
            "old-canceled",
            "recent-completed",
            "old-waiting",
            "old-delegation",
            "session_deadbeef",
        ],
    )

    result = prune_agent_checkpoints(
        checkpoint_db,
        Path(service.db_path),
        vacuum_min_free_bytes=0,
        vacuum_min_free_fraction=0.0,
    )

    assert result.skipped_reason is None
    assert result.threads_before == 7
    assert result.deleted_terminal_threads == 3
    assert result.deleted_orphan_threads == 1
    assert result.vacuumed is True
    assert _checkpoint_thread_ids(checkpoint_db) == {"recent-completed", "old-waiting", "old-delegation"}


@pytest.mark.asyncio
async def test_prune_keeps_everything_when_the_knowledge_database_has_no_agent_tasks(tmp_path: Path) -> None:
    knowledge_db = tmp_path / "empty.sqlite3"
    with closing(sqlite3.connect(str(knowledge_db))) as conn:
        conn.execute("CREATE TABLE unrelated (id TEXT)")
        conn.commit()
    checkpoint_db = tmp_path / "checkpoints.sqlite"
    _write_checkpoint_threads(checkpoint_db, ["task-a", "session_cafe"])

    result = prune_agent_checkpoints(checkpoint_db, knowledge_db)

    assert result.skipped_reason == "agent_tasks table does not exist"
    assert _checkpoint_thread_ids(checkpoint_db) == {"task-a", "session_cafe"}


def test_prune_skips_missing_databases(tmp_path: Path) -> None:
    missing_checkpoints = prune_agent_checkpoints(tmp_path / "none.sqlite", tmp_path / "knowledge.sqlite3")
    assert missing_checkpoints.skipped_reason == "checkpoint database does not exist"

    checkpoint_db = tmp_path / "checkpoints.sqlite"
    _write_checkpoint_threads(checkpoint_db, ["task-a"])
    missing_knowledge = prune_agent_checkpoints(checkpoint_db, tmp_path / "absent.sqlite3")
    assert missing_knowledge.skipped_reason == "knowledge database does not exist"
    assert _checkpoint_thread_ids(checkpoint_db) == {"task-a"}


def test_prune_does_not_vacuum_below_the_free_space_threshold(tmp_path: Path) -> None:
    knowledge_db = tmp_path / "knowledge.sqlite3"
    with closing(sqlite3.connect(str(knowledge_db))) as conn:
        conn.execute("CREATE TABLE agent_tasks (id TEXT PRIMARY KEY, status TEXT, updated_at TEXT)")
        conn.commit()
    checkpoint_db = tmp_path / "checkpoints.sqlite"
    _write_checkpoint_threads(checkpoint_db, ["orphan-a"])

    result = prune_agent_checkpoints(checkpoint_db, knowledge_db)

    assert result.deleted_orphan_threads == 1
    assert result.vacuumed is False
    assert _checkpoint_thread_ids(checkpoint_db) == set()
