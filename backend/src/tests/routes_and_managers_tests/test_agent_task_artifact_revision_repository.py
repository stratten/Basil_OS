"""Transaction, quota, and cascade-delete coverage for artifact revisions."""

import sqlite3
import uuid

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.agent_tasks.mutations import (
    revision_repository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
    run_write_transaction,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.agent_tasks.migrations import (
    migrate_agent_task_artifact_revisions,
    migrate_agent_tasks_table,
)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "revisions.sqlite3")
    conn = get_sync_connection(path)
    try:
        migrate_agent_tasks_table(conn)
        migrate_agent_task_artifact_revisions(conn)
        conn.execute(
            "INSERT INTO agent_tasks (id, timestamp, original_prompt, transcribed_prompt, status) "
            "VALUES (?, CURRENT_TIMESTAMP, 'prompt', 'prompt', 'processing')",
            (str(uuid.uuid4()),),
        )
        conn.commit()
    finally:
        conn.close()
    return path


def _task_id(db_path: str) -> str:
    conn = get_sync_connection(db_path)
    try:
        row = conn.execute("SELECT id FROM agent_tasks LIMIT 1").fetchone()
        return row["id"]
    finally:
        conn.close()


def test_migration_creates_table_and_index_idempotently(db_path):
    conn = get_sync_connection(db_path)
    try:
        migrate_agent_task_artifact_revisions(conn)  # second call must be a no-op
        table_row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent_task_artifact_revisions'"
        ).fetchone()
        index_row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_agent_task_artifact_revisions_lookup'"
        ).fetchone()
        assert table_row is not None
        assert index_row is not None
    finally:
        conn.close()


def test_insert_assigns_monotonic_revisions(db_path):
    task_id = _task_id(db_path)

    def _insert_first(conn: sqlite3.Connection) -> int:
        return revision_repository.insert_artifact_revision(
            conn,
            agent_task_id=task_id,
            artifact_id="artifact-1",
            local_path="/tmp/report.md",
            display_name="report.md",
            content_kind="markdown",
            content_sha256="a" * 64,
            content="# v1",
            byte_count=4,
        )

    def _insert_second(conn: sqlite3.Connection) -> int:
        return revision_repository.insert_artifact_revision(
            conn,
            agent_task_id=task_id,
            artifact_id="artifact-1",
            local_path="/tmp/report.md",
            display_name="report.md",
            content_kind="markdown",
            content_sha256="b" * 64,
            content="# v2",
            byte_count=4,
        )

    first_revision = run_write_transaction(db_path, "test_insert_first", _insert_first)
    second_revision = run_write_transaction(db_path, "test_insert_second", _insert_second)

    assert first_revision == 1
    assert second_revision == 2


def test_reverting_to_a_prior_digest_creates_a_new_revision(db_path):
    task_id = _task_id(db_path)

    def _insert(content_sha256: str, content: str) -> int:
        def _body(conn: sqlite3.Connection) -> int:
            return revision_repository.insert_artifact_revision(
                conn,
                agent_task_id=task_id,
                artifact_id="artifact-1",
                local_path="/tmp/report.md",
                display_name="report.md",
                content_kind="markdown",
                content_sha256=content_sha256,
                content=content,
                byte_count=len(content),
            )

        return run_write_transaction(db_path, "test_insert_revision", _body)

    assert _insert("c" * 64, "# v1") == 1
    assert _insert("d" * 64, "# v2") == 2
    assert _insert("c" * 64, "# v1") == 3


def test_migration_removes_legacy_digest_unique_constraint(db_path):
    task_id = _task_id(db_path)
    conn = get_sync_connection(db_path)
    try:
        conn.execute("DROP TABLE agent_task_artifact_revisions")
        conn.execute(
            """
            CREATE TABLE agent_task_artifact_revisions (
                id TEXT PRIMARY KEY,
                agent_task_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                local_path TEXT NOT NULL,
                display_name TEXT NOT NULL,
                content_kind TEXT NOT NULL,
                revision INTEGER NOT NULL,
                content_sha256 TEXT NOT NULL,
                content TEXT NOT NULL,
                byte_count INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (agent_task_id) REFERENCES agent_tasks(id) ON DELETE CASCADE,
                UNIQUE(agent_task_id, artifact_id, content_sha256),
                UNIQUE(agent_task_id, artifact_id, revision)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO agent_task_artifact_revisions (
                id, agent_task_id, artifact_id, local_path, display_name, content_kind,
                revision, content_sha256, content, byte_count
            ) VALUES (?, ?, 'artifact-1', '/tmp/report.md', 'report.md', 'markdown', 1, ?, '# v1', 4)
            """,
            (str(uuid.uuid4()), task_id, "c" * 64),
        )
        migrate_agent_task_artifact_revisions(conn)
        conn.commit()
        rows = conn.execute(
            """
            SELECT content_sha256, content, revision
            FROM agent_task_artifact_revisions
            WHERE agent_task_id = ? AND artifact_id = 'artifact-1'
            """,
            (task_id,),
        ).fetchall()
        assert [(row["content_sha256"], row["content"], row["revision"]) for row in rows] == [
            ("c" * 64, "# v1", 1)
        ]
    finally:
        conn.close()

    def _insert(conn: sqlite3.Connection) -> int:
        return revision_repository.insert_artifact_revision(
            conn,
            agent_task_id=task_id,
            artifact_id="artifact-1",
            local_path="/tmp/report.md",
            display_name="report.md",
            content_kind="markdown",
            content_sha256="c" * 64,
            content="# v2",
            byte_count=4,
        )

    assert run_write_transaction(db_path, "test_insert_after_migration", _insert) == 2


def test_cascade_delete_removes_revisions_when_task_is_deleted(db_path):
    task_id = _task_id(db_path)

    def _insert(conn: sqlite3.Connection) -> int:
        return revision_repository.insert_artifact_revision(
            conn,
            agent_task_id=task_id,
            artifact_id="artifact-1",
            local_path="/tmp/report.md",
            display_name="report.md",
            content_kind="markdown",
            content_sha256="d" * 64,
            content="# v1",
            byte_count=4,
        )

    run_write_transaction(db_path, "test_insert_for_cascade", _insert)

    def _delete_task(conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM agent_tasks WHERE id = ?", (task_id,))

    run_write_transaction(db_path, "test_delete_task", _delete_task)

    conn = get_sync_connection(db_path)
    try:
        remaining = conn.execute(
            "SELECT COUNT(*) AS remaining_count FROM agent_task_artifact_revisions WHERE agent_task_id = ?",
            (task_id,),
        ).fetchone()["remaining_count"]
        assert remaining == 0
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_list_and_get_are_owned_by_the_requesting_task(db_path):
    task_id = _task_id(db_path)

    def _insert(conn: sqlite3.Connection) -> int:
        return revision_repository.insert_artifact_revision(
            conn,
            agent_task_id=task_id,
            artifact_id="artifact-1",
            local_path="/tmp/report.md",
            display_name="report.md",
            content_kind="markdown",
            content_sha256="e" * 64,
            content="# v1",
            byte_count=4,
        )

    run_write_transaction(db_path, "test_insert_for_list", _insert)

    revisions = await revision_repository.list_artifact_revisions(db_path, task_id, "artifact-1")
    assert len(revisions) == 1
    assert revisions[0]["revision"] == 1
    assert "content" not in revisions[0]

    snapshot = await revision_repository.get_artifact_revision(db_path, task_id, "artifact-1", 1)
    assert snapshot is not None
    assert snapshot["content"] == "# v1"
    assert snapshot["content_sha256"] == "e" * 64

    missing = await revision_repository.get_artifact_revision(db_path, "other-task", "artifact-1", 1)
    assert missing is None
