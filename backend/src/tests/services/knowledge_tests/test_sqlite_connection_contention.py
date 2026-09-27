"""SQLite writer-gate and contention regression tests."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from api.core.knowledge.sqlite.conversation_repository import ConversationRepository
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.mutations.service import (
    AgentTaskMutations,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_async_connection,
    get_sync_connection,
    initialize_sqlite_database_mode,
    reset_sqlite_connection_state_for_tests,
    run_write_transaction,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure import (
    connection as db_connection,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.schema_manager import (
    SchemaManager,
)
from api.services.todos.repository import TodoRepository


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    reset_sqlite_connection_state_for_tests()
    db_path = str(tmp_path / "contention.db")
    initialize_sqlite_database_mode(db_path)
    SchemaManager(db_path).initialize_db()
    return db_path


@pytest.fixture
def conversation_repository(temp_db_path: str) -> ConversationRepository:
    return ConversationRepository(temp_db_path)


def _ensure_conversation(repo: ConversationRepository, conversation_id: str) -> None:
    conn = get_sync_connection(repo.db_path)
    try:
        conn.execute(
            "INSERT INTO conversations (id, title, message_count, is_active, created_at, updated_at) "
            "VALUES (?, 'test', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (conversation_id,),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_concurrent_message_pair_and_metadata_writes_do_not_lock(
    conversation_repository: ConversationRepository,
) -> None:
    conversation_id = "conv-contention-1"
    _ensure_conversation(conversation_repository, conversation_id)

    pair = await conversation_repository.create_message_pair(
        conversation_id=conversation_id,
        user_content="hello",
        user_metadata={"source": "test"},
        assistant_metadata={"conversation_turn": {"route": "direct", "lifecycle": "pending"}},
    )

    def _write_metadata() -> None:
        asyncio.run(
            conversation_repository.merge_message_metadata(
                pair.assistant_message_id,
                {"conversation_turn": {"lifecycle": "running"}},
            )
        )

    def _write_pair() -> None:
        asyncio.run(
            conversation_repository.create_message_pair(
                conversation_id=conversation_id,
                user_content="follow-up",
                user_metadata=None,
                assistant_metadata={"conversation_turn": {"route": "direct", "lifecycle": "pending"}},
            )
        )

    def _read_messages() -> int:
        conn = get_sync_connection(conversation_repository.db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM conversation_messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            return int(row["count"])
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [
            pool.submit(_write_metadata),
            pool.submit(_write_pair),
            pool.submit(_read_messages),
            pool.submit(_read_messages),
            pool.submit(_write_metadata),
            pool.submit(_read_messages),
        ]
        for future in as_completed(futures):
            future.result()


@pytest.mark.asyncio
async def test_agent_task_status_write_uses_writer_gate(temp_db_path: str) -> None:
    mutations = AgentTaskMutations(temp_db_path)
    task_id = "task-contention-1"
    await mutations.store_agent_task(
        agent_task_id=task_id,
        original_prompt="prompt",
        transcribed_prompt="prompt",
    )

    def _update_status(status: str) -> None:
        asyncio.run(mutations.update_agent_task_status(task_id, status))

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_update_status, "processing") for _ in range(4)]
        for future in as_completed(futures):
            future.result()


def test_wal_initialization_is_idempotent(temp_db_path: str) -> None:
    initialize_sqlite_database_mode(temp_db_path)
    initialize_sqlite_database_mode(temp_db_path)
    conn = get_sync_connection(temp_db_path, ensure_schema=False)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"
    finally:
        conn.close()


def test_write_transaction_rolls_back_on_failure(temp_db_path: str) -> None:
    conn = get_sync_connection(temp_db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS contention_probe (
                id INTEGER PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    def _failing_body(conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO contention_probe (value) VALUES (?)", ("before",))
        raise RuntimeError("forced failure")

    with pytest.raises(RuntimeError):
        run_write_transaction(temp_db_path, "contention_probe_failure", _failing_body)

    conn = get_sync_connection(temp_db_path, ensure_schema=False)
    try:
        count = conn.execute("SELECT COUNT(*) FROM contention_probe").fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_write_transaction_retries_a_transient_lock_without_releasing_the_gate_twice(
    temp_db_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_get_connection = db_connection.get_sync_connection
    attempts = 0

    def _transiently_locked_connection(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("database is locked")
        return original_get_connection(*args, **kwargs)

    monkeypatch.setattr(db_connection, "get_sync_connection", _transiently_locked_connection)

    assert run_write_transaction(
        temp_db_path,
        "transient_lock_retry",
        lambda conn: conn.execute("SELECT 1").fetchone()[0],
    ) == 1
    assert attempts == 2


def test_direct_todo_and_activity_writes_share_the_writer_coordinator(temp_db_path: str) -> None:
    """Regression test for the reported "database is locked" defect: a
    direct-connection activity write and a `TodoRepository` write (which
    issues its own `BEGIN IMMEDIATE` independently of `run_write_transaction`)
    must both succeed when run concurrently from separate threads."""
    todo_repo = TodoRepository(temp_db_path)

    def _write_activity() -> None:
        conn = get_sync_connection(temp_db_path, ensure_schema=False, operation_name="activity_write")
        try:
            conn.execute(
                "INSERT INTO activities (id, timestamp, app_name) VALUES (?, ?, ?)",
                ("activity-contention-1", "2026-08-14T00:00:00", "TestApp"),
            )
            conn.commit()
        finally:
            conn.close()

    def _write_todo() -> None:
        asyncio.run(
            todo_repo.create_todo_item_with_source(
                title="Contention To-Do",
                description="",
                notes="",
                responsibility="user",
                priority="normal",
                due_at=None,
                status="open",
                created_by_kind="user",
                created_by_id=None,
                idempotency_key="contention-todo-1",
                idempotency_payload_hash="hash-1",
                source_kind=None,
                source_id=None,
                source_locator=None,
                source_excerpt="",
            )
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_write_activity), pool.submit(_write_todo)]
        for future in as_completed(futures):
            future.result()

    conn = get_sync_connection(temp_db_path, ensure_schema=False)
    try:
        activity_count = conn.execute(
            "SELECT COUNT(*) FROM activities WHERE id = ?", ("activity-contention-1",)
        ).fetchone()[0]
        todo_count = conn.execute(
            "SELECT COUNT(*) FROM todo_items WHERE idempotency_key = ?", ("contention-todo-1",)
        ).fetchone()[0]
    finally:
        conn.close()
    assert activity_count == 1
    assert todo_count == 1


def test_write_coordinator_admits_waiters_in_strict_fifo_order() -> None:
    """Unit-level proof that `_WriteCoordinator` admits queued writers in the
    order they enqueued, independent of SQLite statement timing. The two
    short `time.sleep` calls only sequence when each test thread's `acquire`
    call enqueues relative to the others; there is no production state signal
    for "has enqueued yet" to wait on instead, and adding one purely for this
    test would be test-only production instrumentation."""
    coordinator = db_connection._WriteCoordinator("fifo-order-probe")
    first_token = object()
    coordinator.acquire(first_token, time.monotonic() + 5.0)

    admission_order: list[str] = []

    def _wait_for(name: str, token: object) -> None:
        coordinator.acquire(token, time.monotonic() + 5.0)
        admission_order.append(name)
        coordinator.release(token)

    second_token, third_token = object(), object()
    second_thread = threading.Thread(target=_wait_for, args=("second", second_token))
    second_thread.start()
    time.sleep(0.05)
    third_thread = threading.Thread(target=_wait_for, args=("third", third_token))
    third_thread.start()
    time.sleep(0.05)

    coordinator.release(first_token)
    second_thread.join(timeout=5.0)
    third_thread.join(timeout=5.0)

    assert admission_order == ["second", "third"]


def test_write_budget_times_out_without_poisoning_later_writes(
    temp_db_path: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(db_connection, "WRITE_OPERATION_CEILING_SECONDS", 0.2)

    holder_conn = get_sync_connection(temp_db_path, ensure_schema=False, operation_name="holder")
    holder_conn.execute(
        "CREATE TABLE IF NOT EXISTS contention_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
    )
    holder_conn.commit()
    holder_conn.execute("BEGIN IMMEDIATE")
    holder_conn.execute("INSERT INTO contention_probe (value) VALUES (?)", ("holder",))

    timed_out = threading.Event()

    def _second_writer() -> None:
        conn = get_sync_connection(temp_db_path, ensure_schema=False, operation_name="second_writer")
        try:
            with pytest.raises(db_connection.SQLiteWriteTimeoutError):
                conn.execute("INSERT INTO contention_probe (value) VALUES (?)", ("second",))
        finally:
            timed_out.set()
            conn.close()

    second_thread = threading.Thread(target=_second_writer)
    second_thread.start()
    second_thread.join(timeout=5.0)
    assert timed_out.is_set()

    timeout_messages = [
        record.getMessage()
        for record in caplog.records
        if "SQLite write coordinator timeout" in record.getMessage()
    ]
    assert len(timeout_messages) == 1
    timeout_message = timeout_messages[0]
    assert "holder_operation=holder" in timeout_message
    assert "holder_statement=BEGIN IMMEDIATE" in timeout_message
    assert "holder_age_seconds=" in timeout_message
    assert "holder_thread=MainThread:" in timeout_message
    assert "queued_writers=0" in timeout_message

    holder_conn.commit()
    holder_conn.close()

    third_conn = get_sync_connection(temp_db_path, ensure_schema=False, operation_name="third_writer")
    try:
        third_conn.execute("INSERT INTO contention_probe (value) VALUES (?)", ("third",))
        third_conn.commit()
    finally:
        third_conn.close()

    verify_conn = get_sync_connection(temp_db_path, ensure_schema=False)
    try:
        values = [
            row["value"]
            for row in verify_conn.execute("SELECT value FROM contention_probe ORDER BY id").fetchall()
        ]
    finally:
        verify_conn.close()
    assert values == ["holder", "third"]


def test_factory_gate_does_not_block_reads_or_other_database_files(
    temp_db_path: str, tmp_path: Path
) -> None:
    seed_conn = get_sync_connection(temp_db_path, ensure_schema=False)
    seed_conn.execute(
        "CREATE TABLE IF NOT EXISTS contention_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
    )
    seed_conn.execute("INSERT INTO contention_probe (value) VALUES (?)", ("seeded",))
    seed_conn.commit()
    seed_conn.close()

    holder_conn = get_sync_connection(temp_db_path, ensure_schema=False, operation_name="holder")
    holder_conn.execute("BEGIN IMMEDIATE")
    holder_conn.execute("INSERT INTO contention_probe (value) VALUES (?)", ("held",))

    reader_conn = get_sync_connection(temp_db_path, ensure_schema=False)
    try:
        seeded_row = reader_conn.execute(
            "SELECT value FROM contention_probe WHERE value = 'seeded'"
        ).fetchone()
    finally:
        reader_conn.close()
    assert seeded_row["value"] == "seeded"

    other_db_path = str(tmp_path / "unrelated.db")
    other_conn = get_sync_connection(other_db_path, ensure_schema=False)
    try:
        other_conn.execute(
            "CREATE TABLE IF NOT EXISTS other_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        other_conn.execute("INSERT INTO other_probe (value) VALUES (?)", ("independent",))
        other_conn.commit()
    finally:
        other_conn.close()

    holder_conn.commit()
    holder_conn.close()


def test_run_write_transaction_propagates_coordinator_timeout_without_retrying(
    temp_db_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(db_connection, "WRITE_OPERATION_CEILING_SECONDS", 0.2)

    holder_conn = get_sync_connection(temp_db_path, ensure_schema=False, operation_name="holder")
    holder_conn.execute("BEGIN IMMEDIATE")
    holder_conn.execute(
        "CREATE TABLE IF NOT EXISTS contention_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
    )

    def _insert_body(conn: sqlite3.Connection) -> None:
        conn.execute("INSERT INTO contention_probe (value) VALUES (?)", ("blocked",))

    with pytest.raises(db_connection.SQLiteWriteTimeoutError):
        run_write_transaction(temp_db_path, "blocked_write", _insert_body, ensure_schema=False)

    holder_conn.commit()
    holder_conn.close()


@pytest.mark.parametrize(
    "write_statement",
    [
        "INSERT INTO contention_probe (value) VALUES ('x')",
        "UPDATE contention_probe SET value = 'y' WHERE value = 'x'",
        "DELETE FROM contention_probe WHERE value = 'y'",
        "CREATE TABLE IF NOT EXISTS extra_probe (id INTEGER PRIMARY KEY)",
        "ALTER TABLE contention_probe ADD COLUMN extra TEXT",
        "REINDEX idx_contention_probe_value",
        "ANALYZE contention_probe",
        "BEGIN IMMEDIATE",
    ],
)
def test_authorizer_classifies_every_write_category_as_coordinated(
    temp_db_path: str, monkeypatch: pytest.MonkeyPatch, write_statement: str
) -> None:
    """Smoke test for the locally declared SQLite authorizer action-code
    constants (Python's `sqlite3` module does not expose them). If any
    constant is wrong for a given statement category, that category is
    authorized immediately instead of queuing behind `holder_conn`, and this
    test fails loudly instead of the coordinator silently no-op'ing for that
    category in production."""
    monkeypatch.setattr(db_connection, "WRITE_OPERATION_CEILING_SECONDS", 0.2)

    setup_conn = get_sync_connection(temp_db_path, ensure_schema=False)
    setup_conn.execute(
        "CREATE TABLE IF NOT EXISTS contention_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
    )
    setup_conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_contention_probe_value ON contention_probe(value)"
    )
    setup_conn.commit()
    setup_conn.close()

    holder_conn = get_sync_connection(temp_db_path, ensure_schema=False, operation_name="holder")
    holder_conn.execute("BEGIN IMMEDIATE")
    holder_conn.execute("INSERT INTO contention_probe (value) VALUES ('holder')")

    blocked_conn = get_sync_connection(temp_db_path, ensure_schema=False, operation_name="blocked")
    try:
        with pytest.raises(db_connection.SQLiteWriteTimeoutError):
            blocked_conn.execute(write_statement)
    finally:
        blocked_conn.close()
        holder_conn.commit()
        holder_conn.close()


def test_context_manager_exit_releases_the_write_coordinator(temp_db_path: str) -> None:
    """`with connection` must release the FIFO token even when the caller
    never invokes Python `commit()`. sqlite3's C-level `__exit__` would
    otherwise leak the holder and deadlock the next writer."""
    with get_sync_connection(temp_db_path, ensure_schema=False) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS contention_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO contention_probe (value) VALUES (?)", ("first",))

    coordinator = db_connection._coordinator_for(temp_db_path)
    assert coordinator._holder is None
    assert list(coordinator._queue) == []

    with get_sync_connection(temp_db_path, ensure_schema=False) as connection:
        connection.execute("INSERT INTO contention_probe (value) VALUES (?)", ("second",))

    assert coordinator._holder is None
    with get_sync_connection(temp_db_path, ensure_schema=False) as connection:
        rows = connection.execute(
            "SELECT value FROM contention_probe ORDER BY id"
        ).fetchall()
    assert [row["value"] for row in rows] == ["first", "second"]


@pytest.mark.parametrize(
    "write",
    [
        lambda connection: connection.executemany(
            "INSERT INTO contention_probe (value) VALUES (?)", [("bulk",)]
        ),
        lambda connection: connection.executescript(
            "INSERT INTO contention_probe (value) VALUES ('script');"
        ),
    ],
    ids=["executemany", "executescript"],
)
def test_bulk_write_apis_propagate_coordinator_timeout(
    temp_db_path: str, monkeypatch: pytest.MonkeyPatch, write
) -> None:
    monkeypatch.setattr(db_connection, "WRITE_OPERATION_CEILING_SECONDS", 0.2)
    setup_conn = get_sync_connection(temp_db_path, ensure_schema=False)
    setup_conn.execute(
        "CREATE TABLE IF NOT EXISTS contention_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
    )
    setup_conn.commit()
    setup_conn.close()

    holder_conn = get_sync_connection(temp_db_path, ensure_schema=False, operation_name="holder")
    holder_conn.execute("BEGIN IMMEDIATE")
    holder_conn.execute("INSERT INTO contention_probe (value) VALUES (?)", ("holder",))

    blocked_conn = get_sync_connection(temp_db_path, ensure_schema=False, operation_name="blocked")
    try:
        with pytest.raises(db_connection.SQLiteWriteTimeoutError):
            write(blocked_conn)
    finally:
        blocked_conn.close()
        holder_conn.commit()
        holder_conn.close()


@pytest.mark.asyncio
async def test_async_factory_propagates_coordinator_timeout(
    temp_db_path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(db_connection, "WRITE_OPERATION_CEILING_SECONDS", 0.2)
    setup_conn = get_sync_connection(temp_db_path, ensure_schema=False)
    setup_conn.execute(
        "CREATE TABLE IF NOT EXISTS contention_probe (id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
    )
    setup_conn.commit()
    setup_conn.close()

    holder_conn = get_sync_connection(temp_db_path, ensure_schema=False, operation_name="holder")
    holder_conn.execute("BEGIN IMMEDIATE")
    holder_conn.execute("INSERT INTO contention_probe (value) VALUES (?)", ("holder",))

    blocked_conn = await get_async_connection(temp_db_path, ensure_schema=False)
    try:
        with pytest.raises(db_connection.SQLiteWriteTimeoutError) as error:
            await blocked_conn.execute("INSERT INTO contention_probe (value) VALUES (?)", ("blocked",))
        assert error.value.operation_name == "async_write"
    finally:
        await blocked_conn.close()
        holder_conn.commit()
        holder_conn.close()
