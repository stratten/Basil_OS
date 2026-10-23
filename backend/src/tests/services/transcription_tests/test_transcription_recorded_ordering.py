import sqlite3
from datetime import datetime, timedelta

import pytest

from api.core.knowledge.models import Transcription
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.schema_management.core_migrations import (
    migrate_transcriptions_table,
)
from api.core.knowledge.sqlite.transcription_repository import TranscriptionRepository
from api.services.transcription.processing.transcription_lifecycle import (
    STATUS_PENDING,
    should_persist,
)


def _transcription(
    transcription_id: str,
    timestamp: datetime,
    created_at: datetime,
) -> Transcription:
    return Transcription(
        id=transcription_id,
        timestamp=timestamp,
        transcription_text=f"text for {transcription_id}",
        model_name="test-model",
        audio_file_path=f"/tmp/{transcription_id}.wav",
        created_at=created_at,
    )


def test_normal_transcription_flow_context_remains_history_eligible():
    assert should_persist({"flowContext": "transcription"})


def test_internal_flow_contexts_remain_excluded_from_history():
    assert not should_persist({"flowContext": "basil_board_home"})
    assert not should_persist({"assistant_session": True})


@pytest.mark.asyncio
async def test_retranscription_status_update_preserves_recorded_timestamp(tmp_path):
    repo = TranscriptionRepository(tmp_path / "transcriptions.db")
    recorded_at = datetime(2026, 6, 10, 9, 30, 0)
    retranscribed_at = datetime(2026, 6, 13, 16, 5, 0)

    await repo.save_transcription(
        _transcription("old-recording", recorded_at, recorded_at)
    )

    await repo.update_status(
        "old-recording",
        STATUS_PENDING,
        transcription_text="",
        model_name="new-model",
        last_transcribed_at=retranscribed_at,
    )

    updated = await repo.get_transcription("old-recording")

    assert updated is not None
    assert updated.timestamp == recorded_at
    assert updated.last_transcribed_at == retranscribed_at


@pytest.mark.asyncio
async def test_search_transcriptions_orders_by_recorded_timestamp(tmp_path):
    repo = TranscriptionRepository(tmp_path / "transcriptions.db")
    old_recorded_at = datetime(2026, 6, 10, 9, 30, 0)
    new_recorded_at = datetime(2026, 6, 12, 9, 30, 0)
    retranscribed_at = datetime(2026, 6, 13, 16, 5, 0)

    await repo.save_transcription(
        _transcription("old-recording", old_recorded_at, old_recorded_at)
    )
    await repo.save_transcription(
        _transcription("new-recording", new_recorded_at, new_recorded_at)
    )
    await repo.update_status(
        "old-recording",
        STATUS_PENDING,
        last_transcribed_at=retranscribed_at,
    )

    results = await repo.search_transcriptions(
        start_date=old_recorded_at - timedelta(days=1),
        limit=10,
    )

    assert [row.id for row in results] == ["new-recording", "old-recording"]


def test_transcription_migration_restores_recorded_timestamp(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE transcriptions (
                id TEXT PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL,
                transcription_text TEXT NOT NULL,
                model_name TEXT NOT NULL,
                audio_file_path TEXT NOT NULL,
                created_at TIMESTAMP
            )
            """
        )
        original_recorded_at = "2026-06-10T09:30:00"
        overwritten_transcribed_at = "2026-06-13T16:05:00"
        conn.execute(
            """
            INSERT INTO transcriptions (
                id, timestamp, transcription_text, model_name, audio_file_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-retranscribed-row",
                overwritten_transcribed_at,
                "text",
                "model",
                "/tmp/audio.wav",
                original_recorded_at,
            ),
        )
        conn.commit()

        migrate_transcriptions_table(conn)
        conn.commit()

        row = conn.execute(
            "SELECT timestamp, last_transcribed_at FROM transcriptions WHERE id = ?",
            ("legacy-retranscribed-row",),
        ).fetchone()
    finally:
        conn.close()

    assert row["timestamp"] == original_recorded_at
    assert row["last_transcribed_at"] == overwritten_transcribed_at
