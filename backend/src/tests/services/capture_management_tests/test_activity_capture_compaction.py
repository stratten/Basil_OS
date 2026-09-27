"""Regression coverage for ingestion-time automatic capture compaction."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.capture.automatic.automatic_activity_capture_service import (
    ActivityCaptureRecord,
    AutomaticActivityCaptureService,
)
from api.services.capture.shared.activity_capture_status import ActivityCaptureStatus
from api.services.capture.shared.perceptual_similarity import (
    SIMILARITY_HAMMING_THRESHOLD,
    hamming_distance,
    is_functionally_unchanged,
)


@pytest.fixture
def compaction_service(tmp_path: Path) -> tuple[Path, SQLiteKnowledgeService, AutomaticActivityCaptureService]:
    db_path = tmp_path / "knowledge_base.db"
    knowledge_service = SQLiteKnowledgeService(str(db_path))
    service = AutomaticActivityCaptureService.__new__(AutomaticActivityCaptureService)
    service.knowledge_service = knowledge_service
    service.activity_capture_frequency_minutes = 0.5
    service.compacted_capture_count = 0
    service.last_policy_decision = None
    service.last_policy_decision_time = None
    return db_path, knowledge_service, service


def _seed_open_sequence(
    db_path: Path,
    *,
    timestamp: datetime,
    fingerprint: str = "0000000000000000",
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO activities (
            id, timestamp, app_name, window_title, duration, observation_count,
            last_observed_at, content_fingerprint
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "open-sequence",
            timestamp.isoformat(),
            "TestApp",
            "Study notes",
            30,
            1,
            timestamp.isoformat(),
            fingerprint,
        ),
    )
    conn.execute(
        """
        INSERT INTO activity_metadata (activity_id, key, value)
        VALUES (?, 'work_context_key', ?)
        """,
        ("open-sequence", "document:study-notes"),
    )
    conn.commit()
    conn.close()


def _record(timestamp: datetime, screenshot_path: str | None = None, fingerprint: str = "0000000000000000") -> ActivityCaptureRecord:
    return ActivityCaptureRecord(
        capture_id="new-capture",
        timestamp=timestamp,
        app_name="TestApp",
        window_title="Study notes",
        screenshot_path=screenshot_path,
        extracted_text=None,
        processing_status=ActivityCaptureStatus.PENDING,
        automatic_capture=True,
        perceptual_hash=fingerprint,
        work_context_key="document:study-notes",
    )


@pytest.mark.asyncio
async def test_matching_capture_extends_existing_activity_and_removes_temp_file(
    compaction_service,
    tmp_path: Path,
) -> None:
    db_path, _knowledge_service, service = compaction_service
    previous_timestamp = datetime.now() - timedelta(seconds=30)
    _seed_open_sequence(db_path, timestamp=previous_timestamp)
    screenshot = tmp_path / "redundant.png"
    screenshot.write_bytes(b"capture")

    compacted = await service._try_compact_into_open_sequence(
        _record(datetime.now(), str(screenshot)),
        "document:study-notes",
    )

    assert compacted is True
    assert not screenshot.exists()
    assert service.compacted_capture_count == 1
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT observation_count, duration, last_observed_at FROM activities WHERE id = 'open-sequence'"
    ).fetchone()
    count = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    conn.close()
    assert row is not None
    assert row[0] == 2
    assert row[1] >= 60
    assert datetime.fromisoformat(row[2]) > previous_timestamp
    assert count == 1


@pytest.mark.asyncio
async def test_different_or_stale_capture_does_not_compact(compaction_service) -> None:
    db_path, _knowledge_service, service = compaction_service
    _seed_open_sequence(
        db_path,
        timestamp=datetime.now() - timedelta(minutes=10),
        fingerprint="0000000000000000",
    )

    assert await service._try_compact_into_open_sequence(
        _record(datetime.now(), fingerprint="ffffffffffffffff"),
        "document:study-notes",
    ) is False

    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE activities SET last_observed_at = ? WHERE id = 'open-sequence'",
        ((datetime.now() - timedelta(minutes=10)).isoformat(),),
    )
    conn.commit()
    conn.close()
    assert await service._try_compact_into_open_sequence(
        _record(datetime.now()),
        "document:study-notes",
    ) is False


def test_hamming_similarity_handles_identical_different_and_malformed_hashes() -> None:
    assert hamming_distance("0000000000000000", "0000000000000000") == 0
    assert hamming_distance("0000000000000000", "0000000000000001") == 1
    assert is_functionally_unchanged("0000000000000000", "0000000000000001")
    assert hamming_distance("0000000000000000", "ffffffffffffffff") == 64
    assert not is_functionally_unchanged("0000000000000000", "ffffffffffffffff")
    assert hamming_distance("malformed", "0000000000000000") > SIMILARITY_HAMMING_THRESHOLD
