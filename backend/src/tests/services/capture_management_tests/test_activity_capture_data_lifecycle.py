"""Tests for ActivityCaptureDataLifecycleService cascade deletion."""

from __future__ import annotations

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.services.capture_management_service import CaptureManagementService
from api.services.capture.automatic.activity_capture_data_lifecycle_service import (
    ActivityCaptureDataLifecycleService,
)


def _insert_capture_activity(
    conn: sqlite3.Connection,
    *,
    activity_id: str,
    timestamp: str,
    automatic: str,
    screenshot_path: str | None = None,
    zettel_id: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO activities (id, timestamp, app_name, window_title) VALUES (?, ?, ?, ?)",
        (activity_id, timestamp, "TestApp", "Window"),
    )
    conn.execute(
        "INSERT INTO activity_metadata (activity_id, key, value) VALUES (?, 'automatic_capture', ?)",
        (activity_id, automatic),
    )
    if screenshot_path is not None:
        conn.execute(
            "INSERT INTO activity_metadata (activity_id, key, value) VALUES (?, 'screenshot_path', ?)",
            (activity_id, screenshot_path),
        )
    if zettel_id is not None:
        conn.execute("UPDATE activities SET zettel_id = ? WHERE id = ?", (zettel_id, activity_id))


@pytest.fixture
def lifecycle_env(tmp_path: Path):
    db_path = tmp_path / "knowledge_base.db"
    SQLiteKnowledgeService(db_path)
    retrieval_runtime = MagicMock()
    materializer = MagicMock()
    materializer.run_pass.return_value = MagicMock(carded=0, existing=0, stamped=0, errors=[])
    service = ActivityCaptureDataLifecycleService(str(db_path), retrieval_runtime, materializer)
    return db_path, service, retrieval_runtime, materializer


@pytest.mark.asyncio
async def test_delete_all_removes_capture_rows_files_fts_and_retrieval_metadata(lifecycle_env, tmp_path: Path) -> None:
    db_path, service, retrieval_runtime, _materializer = lifecycle_env
    screenshot = tmp_path / "capture_a.png"
    screenshot.write_bytes(b"x" * 128)
    other_screenshot = tmp_path / "orphan.png"
    other_screenshot.write_bytes(b"y" * 64)

    conn = sqlite3.connect(db_path)
    _insert_capture_activity(
        conn,
        activity_id="auto-1",
        timestamp=datetime.now().isoformat(),
        automatic="True",
        screenshot_path=str(screenshot),
        zettel_id="screen_block:auto-1",
    )
    _insert_capture_activity(
        conn,
        activity_id="manual-1",
        timestamp=datetime.now().isoformat(),
        automatic="False",
    )
    conn.execute(
        "INSERT INTO activities (id, timestamp, app_name, window_title) VALUES ('plain-1', ?, 'Notes', 'No marker')",
        (datetime.now().isoformat(),),
    )
    conn.execute(
        """
        INSERT INTO zettel_entries (
            id, source_kind, source_id, event_type, occurred_at, title, payload_json, materialized_at
        ) VALUES ('screen_block:auto-1', 'screen_block', 'auto-1', 'screen_block', ?, 'Block', '{}', ?)
        """,
        (datetime.now().isoformat(), datetime.now().isoformat()),
    )
    conn.execute(
        "INSERT INTO zettel_search_fts (entry_id, source_kind, occurred_at, content) VALUES ('screen_block:auto-1', 'screen_block', ?, 'secret')",
        (datetime.now().isoformat(),),
    )
    conn.execute(
        """
        INSERT INTO retrieval_documents (
            document_id, source_kind, source_id, content_digest, occurred_at, updated_at,
            embedding_model, embedding_dimension, vector_id, generation_id, indexed_at, is_active
        ) VALUES ('screen_block:auto-1', 'screen_block', 'auto-1', 'd', ?, ?, 'm', 1, 1, 'g', ?, 1)
        """,
        (datetime.now().isoformat(), datetime.now().isoformat(), datetime.now().isoformat()),
    )
    conn.execute(
        """
        INSERT INTO zettel_entries (
            id, source_kind, source_id, event_type, occurred_at, title, payload_json, materialized_at
        ) VALUES ('conversation:keep', 'conversation', 'keep', 'conversation', ?, 'Keep', '{}', ?)
        """,
        (datetime.now().isoformat(), datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()

    result = await service.delete_all()

    assert result.activity_rows_deleted == 2
    assert result.zettel_rows_deleted == 1
    assert result.files_deleted == 1
    assert not screenshot.exists()
    assert other_screenshot.exists()

    conn = sqlite3.connect(db_path)
    remaining = {row[0] for row in conn.execute("SELECT id FROM activities").fetchall()}
    retained_zettels = {
        row[0] for row in conn.execute("SELECT id FROM zettel_entries").fetchall()
    }
    conn.close()
    assert remaining == {"plain-1"}
    assert retained_zettels == {"conversation:keep"}
    retrieval_runtime.request_reconciliation.assert_called_once_with("activity_capture_deletion")


@pytest.mark.asyncio
async def test_delete_older_than_uses_strict_cutoff(lifecycle_env) -> None:
    db_path, service, _, _ = lifecycle_env
    old_ts = (datetime.now() - timedelta(days=10)).isoformat()
    cutoff_ts = (datetime.now() - timedelta(days=5)).isoformat()
    new_ts = datetime.now().isoformat()

    conn = sqlite3.connect(db_path)
    _insert_capture_activity(conn, activity_id="old", timestamp=old_ts, automatic="True")
    _insert_capture_activity(conn, activity_id="at-cutoff", timestamp=cutoff_ts, automatic="True")
    _insert_capture_activity(conn, activity_id="new", timestamp=new_ts, automatic="True")
    conn.commit()
    conn.close()

    result = await service.delete_older_than(datetime.fromisoformat(cutoff_ts))

    conn = sqlite3.connect(db_path)
    remaining = {row[0] for row in conn.execute("SELECT id FROM activities").fetchall()}
    conn.close()
    assert result.activity_rows_deleted == 1
    assert remaining == {"at-cutoff", "new"}


@pytest.mark.asyncio
async def test_repeated_deletion_is_idempotent(lifecycle_env) -> None:
    _db_path, service, _, _ = lifecycle_env
    first = await service.delete_all()
    second = await service.delete_all()
    assert first.activity_rows_deleted >= 0
    assert second.activity_rows_deleted == 0
    assert not second.file_errors
    assert not second.post_commit_errors


@pytest.mark.asyncio
async def test_delete_subset_invalidates_shared_block_and_recards_retained_members(
    lifecycle_env,
) -> None:
    db_path, service, _, materializer = lifecycle_env
    cutoff = datetime.now() - timedelta(days=5)
    stale_zettel_id = "screen_block:old"

    conn = sqlite3.connect(db_path)
    _insert_capture_activity(
        conn,
        activity_id="old",
        timestamp=(cutoff - timedelta(days=1)).isoformat(),
        automatic="True",
        zettel_id=stale_zettel_id,
    )
    _insert_capture_activity(
        conn,
        activity_id="retained",
        timestamp=(cutoff + timedelta(days=1)).isoformat(),
        automatic="True",
        zettel_id=stale_zettel_id,
    )
    conn.execute("UPDATE activities SET extracted_text = 'deleted secret' WHERE id = 'old'")
    conn.execute("UPDATE activities SET extracted_text = 'retained text' WHERE id = 'retained'")
    conn.execute(
        """
        INSERT INTO zettel_entries (
            id, source_kind, source_id, event_type, occurred_at, title, payload_json, materialized_at
        ) VALUES (?, 'screen_block', 'old', 'screen_block', ?, 'Stale block', ?, ?)
        """,
        (
            stale_zettel_id,
            datetime.now().isoformat(),
            json.dumps({"captures": ["deleted secret", "retained text"]}),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()

    def _recard(*, enabled_kinds):
        assert enabled_kinds == {"screen_block"}
        recard_conn = sqlite3.connect(db_path)
        row = recard_conn.execute(
            "SELECT id, extracted_text FROM activities WHERE zettel_id IS NULL"
        ).fetchone()
        assert row is not None
        new_zettel_id = f"screen_block:{row[0]}"
        recard_conn.execute(
            """
            INSERT INTO zettel_entries (
                id, source_kind, source_id, event_type, occurred_at, title,
                payload_json, materialized_at
            ) VALUES (?, 'screen_block', ?, 'screen_block', ?, 'Recarded', ?, ?)
            """,
            (
                new_zettel_id,
                row[0],
                datetime.now().isoformat(),
                json.dumps({"text": row[1]}),
                datetime.now().isoformat(),
            ),
        )
        recard_conn.execute(
            "UPDATE activities SET zettel_id = ? WHERE id = ?",
            (new_zettel_id, row[0]),
        )
        recard_conn.commit()
        recard_conn.close()

    materializer.run_pass.side_effect = _recard

    result = await service.delete_older_than(cutoff)

    assert result.activity_rows_deleted == 1
    conn = sqlite3.connect(db_path)
    retained = conn.execute(
        "SELECT zettel_id FROM activities WHERE id = 'retained'"
    ).fetchone()
    assert retained == ("screen_block:retained",)
    payload = conn.execute(
        "SELECT payload_json FROM zettel_entries WHERE id = ?",
        (retained[0],),
    ).fetchone()[0]
    assert "retained text" in payload
    assert "deleted secret" not in payload
    assert conn.execute(
        "SELECT 1 FROM zettel_entries WHERE id = ?", (stale_zettel_id,)
    ).fetchone() is None
    conn.close()


@pytest.mark.asyncio
async def test_storage_trim_deletes_oldest_managed_paths_only(
    lifecycle_env,
    tmp_path: Path,
) -> None:
    db_path, service, _, _ = lifecycle_env
    base = datetime.now() - timedelta(days=3)
    conn = sqlite3.connect(db_path)
    paths: list[Path] = []
    for index in range(3):
        path = tmp_path / f"capture-{index}.png"
        path.write_bytes(b"x" * 700_000)
        paths.append(path)
        _insert_capture_activity(
            conn,
            activity_id=f"capture-{index}",
            timestamp=(base + timedelta(days=index)).isoformat(),
            automatic="True",
            screenshot_path=str(path),
        )
    conn.commit()
    conn.close()
    orphan = tmp_path / "orphan.png"
    orphan.write_bytes(b"o" * 1_500_000)

    result = await service.trim_to_storage_limit(1)

    assert result.activity_rows_deleted == 2
    assert not paths[0].exists()
    assert not paths[1].exists()
    assert paths[2].exists()
    assert orphan.exists()
    conn = sqlite3.connect(db_path)
    remaining = {
        row[0] for row in conn.execute("SELECT id FROM activities").fetchall()
    }
    conn.close()
    assert remaining == {"capture-2"}


@pytest.mark.asyncio
async def test_database_failure_does_not_unlink_files(
    lifecycle_env,
    tmp_path: Path,
) -> None:
    db_path, service, _, _ = lifecycle_env
    screenshot = tmp_path / "capture.png"
    screenshot.write_bytes(b"x" * 128)
    conn = sqlite3.connect(db_path)
    _insert_capture_activity(
        conn,
        activity_id="capture",
        timestamp=datetime.now().isoformat(),
        automatic="True",
        screenshot_path=str(screenshot),
    )
    conn.execute(
        """
        CREATE TRIGGER fail_capture_delete
        BEFORE DELETE ON activities
        BEGIN
            SELECT RAISE(ABORT, 'injected delete failure');
        END
        """
    )
    conn.commit()
    conn.close()

    with pytest.raises(sqlite3.IntegrityError, match="injected delete failure"):
        await service.delete_all()

    assert screenshot.exists()
    conn = sqlite3.connect(db_path)
    assert conn.execute(
        "SELECT 1 FROM activities WHERE id = 'capture'"
    ).fetchone() is not None
    assert conn.execute(
        "SELECT 1 FROM activity_metadata WHERE activity_id = 'capture'"
    ).fetchone() is not None
    conn.close()


@pytest.mark.asyncio
async def test_unlink_failure_returns_partial_and_database_stays_deleted(
    lifecycle_env,
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path, service, _, _ = lifecycle_env
    screenshot = tmp_path / "capture.png"
    screenshot.write_bytes(b"x" * 128)
    conn = sqlite3.connect(db_path)
    _insert_capture_activity(
        conn,
        activity_id="capture",
        timestamp=datetime.now().isoformat(),
        automatic="True",
        screenshot_path=str(screenshot),
    )
    conn.commit()
    conn.close()

    original_unlink = Path.unlink

    def _fail_unlink(path: Path, *args, **kwargs):
        if path == screenshot:
            raise PermissionError("injected unlink failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _fail_unlink)

    result = await service.delete_all()

    assert result.is_partial
    assert len(result.file_errors) == 1
    assert "injected unlink failure" in result.file_errors[0]
    assert len(result.file_errors[0]) <= 500
    assert screenshot.exists()
    conn = sqlite3.connect(db_path)
    assert conn.execute(
        "SELECT 1 FROM activities WHERE id = 'capture'"
    ).fetchone() is None
    conn.close()


@pytest.mark.asyncio
async def test_assistant_output_survives_with_capture_links_cleared(
    lifecycle_env,
    tmp_path: Path,
) -> None:
    db_path, service, _, _ = lifecycle_env
    screenshot = tmp_path / "capture.png"
    screenshot.write_bytes(b"x" * 128)
    conn = sqlite3.connect(db_path)
    _insert_capture_activity(
        conn,
        activity_id="capture",
        timestamp=datetime.now().isoformat(),
        automatic="True",
        screenshot_path=str(screenshot),
    )
    conn.execute(
        """
        INSERT INTO assistant_outputs (activity_id, output_text, screen_capture_path)
        VALUES ('capture', 'keep this output', ?)
        """,
        (str(screenshot),),
    )
    conn.commit()
    conn.close()

    await service.delete_all()

    conn = sqlite3.connect(db_path)
    output = conn.execute(
        "SELECT activity_id, output_text, screen_capture_path FROM assistant_outputs"
    ).fetchone()
    conn.close()
    assert output == (None, "keep this output", None)


@pytest.mark.asyncio
async def test_retrieval_is_ineligible_before_async_rebuild_finishes(
    lifecycle_env,
) -> None:
    db_path, service, retrieval_runtime, _ = lifecycle_env
    zettel_id = "screen_block:capture"
    conn = sqlite3.connect(db_path)
    _insert_capture_activity(
        conn,
        activity_id="capture",
        timestamp=datetime.now().isoformat(),
        automatic="True",
        zettel_id=zettel_id,
    )
    conn.execute(
        """
        INSERT INTO zettel_entries (
            id, source_kind, source_id, event_type, occurred_at, title,
            payload_json, materialized_at
        ) VALUES (?, 'screen_block', 'capture', 'screen_block', ?, 'Block', '{}', ?)
        """,
        (zettel_id, datetime.now().isoformat(), datetime.now().isoformat()),
    )
    conn.execute(
        """
        INSERT INTO retrieval_documents (
            document_id, source_kind, source_id, content_digest, occurred_at,
            updated_at, embedding_model, embedding_dimension, vector_id,
            generation_id, indexed_at, is_active
        ) VALUES (?, 'screen_block', 'capture', 'digest', ?, ?, 'model', 1, 1, 'g', ?, 1)
        """,
        (
            zettel_id,
            datetime.now().isoformat(),
            datetime.now().isoformat(),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()

    await service.delete_all()

    conn = sqlite3.connect(db_path)
    assert conn.execute(
        "SELECT 1 FROM retrieval_documents WHERE document_id = ?", (zettel_id,)
    ).fetchone() is None
    conn.close()
    retrieval_runtime.request_reconciliation.assert_called_once_with(
        "activity_capture_deletion"
    )


@pytest.mark.asyncio
async def test_lifecycle_dependency_failure_does_not_start_filesystem_cleanup(
    monkeypatch,
) -> None:
    service = CaptureManagementService.__new__(CaptureManagementService)
    service.storage_service = MagicMock()
    service.storage_service.get_db_path.return_value = Path("/tmp/not-used.db")
    service._clear_legacy_capture_files_only = AsyncMock()

    def _fail_runtime():
        raise RuntimeError("retrieval runtime unavailable")

    monkeypatch.setattr(
        "api.services.retrieval.index_runtime.get_retrieval_index_runtime",
        _fail_runtime,
    )

    with pytest.raises(RuntimeError, match="retrieval runtime unavailable"):
        await service.clear_all_captures()

    service._clear_legacy_capture_files_only.assert_not_awaited()
