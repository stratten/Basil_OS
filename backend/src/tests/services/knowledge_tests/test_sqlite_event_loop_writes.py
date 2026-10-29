"""A write issued on the event loop thread must never be able to freeze the loop for a held write token.

An aiosqlite writer takes the write coordinator at its first mutating statement and releases it at commit, which it can only reach by resuming on the event loop. A synchronous write that waits for the coordinator on the loop thread therefore deadlocks against it until the wait budget expires. In production this froze the whole backend for 30 seconds at a time, once per captured tool result.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure import (
    connection as db_connection,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    SQLiteWriteTimeoutError,
    get_async_connection,
    initialize_sqlite_database_mode,
    reset_sqlite_connection_state_for_tests,
    run_write_transaction,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    reset_sqlite_connection_state_for_tests()
    db_path = str(tmp_path / "loop-writes.db")
    initialize_sqlite_database_mode(db_path)
    SchemaManager(db_path).initialize_db()
    return db_path


async def _hold_write_token(db_path: str):
    """Open an async writer that has taken the write coordinator but not committed yet."""
    holder = await get_async_connection(db_path)
    await holder.execute(
        "INSERT INTO conversations (id, title, message_count, is_active, created_at, updated_at) "
        "VALUES ('holder-conversation', 'held', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
    )
    return holder


@pytest.mark.asyncio
async def test_loop_thread_write_fails_fast_while_an_async_writer_holds_the_token(
    temp_db_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(db_connection, "LOOP_THREAD_WRITE_BUDGET_SECONDS", 0.3)
    monkeypatch.setattr(db_connection, "_loop_thread_write_warned", set())
    holder = await _hold_write_token(temp_db_path)
    try:
        started = time.monotonic()
        with pytest.raises(SQLiteWriteTimeoutError) as raised:
            run_write_transaction(
                temp_db_path,
                "loop_thread_write",
                lambda conn: conn.execute(
                    "INSERT INTO conversations (id, title, message_count, is_active, created_at, updated_at) "
                    "VALUES ('loop-conversation', 'loop', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
            )
        elapsed = time.monotonic() - started

        assert raised.value.budget_seconds == pytest.approx(0.3)
        assert elapsed < 2.0
        assert "loop_thread_write" in db_connection._loop_thread_write_warned
    finally:
        await holder.commit()
        await holder.close()


@pytest.mark.asyncio
async def test_worker_thread_write_still_waits_for_the_holder_instead_of_failing(temp_db_path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_connection, "LOOP_THREAD_WRITE_BUDGET_SECONDS", 0.1)
    holder = await _hold_write_token(temp_db_path)

    def write_from_worker() -> None:
        run_write_transaction(
            temp_db_path,
            "worker_thread_write",
            lambda conn: conn.execute(
                "INSERT INTO conversations (id, title, message_count, is_active, created_at, updated_at) "
                "VALUES ('worker-conversation', 'worker', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
        )

    worker = asyncio.create_task(asyncio.to_thread(write_from_worker))
    await asyncio.sleep(0.4)
    assert not worker.done()

    await holder.commit()
    await holder.close()
    await asyncio.wait_for(worker, timeout=5)


@pytest.mark.asyncio
async def test_work_ledger_session_lookup_does_not_deadlock_with_an_uncommitted_async_writer(tmp_path: Path) -> None:
    """The original production freeze: a ledger write on the loop against an async writer waiting to commit."""
    reset_sqlite_connection_state_for_tests()
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    db_path = str(service.db_path)
    await service.store_agent_task(
        agent_task_id="root-task",
        original_prompt="Review",
        transcribed_prompt="Review",
        status="processing",
    )
    holder = await _hold_write_token(db_path)

    async def commit_after_loop_runs() -> None:
        # The holder can only commit once the loop is free to resume it, which is exactly what a blocked loop prevents.
        await asyncio.sleep(0.2)
        await holder.commit()
        await holder.close()

    committer = asyncio.create_task(commit_after_loop_runs())
    ticks = 0

    async def count_loop_ticks() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    ticker = asyncio.create_task(count_loop_ticks())
    started = time.monotonic()
    try:
        session = await asyncio.wait_for(
            service.agent_work_session_repository.get_or_create_root_session(
                agent_task_id="root-task",
                root_task_id="root-task",
                goal="Review",
                collection_type="direct_tool",
            ),
            timeout=10,
        )
        await committer
    finally:
        ticker.cancel()

    elapsed = time.monotonic() - started
    assert session["root_task_id"] == "root-task"
    assert elapsed < 5.0
    assert ticks >= 5


@pytest.mark.asyncio
async def test_existing_root_session_is_returned_without_taking_the_write_token(tmp_path: Path) -> None:
    reset_sqlite_connection_state_for_tests()
    service = SQLiteKnowledgeService(tmp_path / "knowledge.db")
    db_path = str(service.db_path)
    await service.store_agent_task(
        agent_task_id="root-task",
        original_prompt="Review",
        transcribed_prompt="Review",
        status="processing",
    )
    created = await service.agent_work_session_repository.get_or_create_root_session(
        agent_task_id="root-task",
        root_task_id="root-task",
        goal="Review",
        collection_type="direct_tool",
    )

    holder = await _hold_write_token(db_path)
    try:
        started = time.monotonic()
        again = await asyncio.wait_for(
            service.agent_work_session_repository.get_or_create_root_session(
                agent_task_id="root-task",
                root_task_id="root-task",
                goal="Review",
                collection_type="direct_tool",
            ),
            timeout=2,
        )
        assert time.monotonic() - started < 1.0
        assert again["id"] == created["id"]
    finally:
        await holder.commit()
        await holder.close()
