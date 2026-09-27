"""Coverage for indexed activity status counts."""

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.activities.search_repository import (
    ActivitySearchRepository,
)
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
    get_sync_connection,
)


@pytest.mark.asyncio
async def test_count_activities_by_metadata_returns_each_status_and_zero(tmp_path):
    db_path = tmp_path / "knowledge.db"
    with get_sync_connection(
        str(db_path),
        operation_name="test_activity_metadata_counts",
    ) as connection:
        connection.executemany(
            """
            INSERT INTO activities (id, timestamp, app_name)
            VALUES (?, ?, ?)
            """,
            [
                ("p1", "2026-08-15T08:00:00", "Test"),
                ("p2", "2026-08-15T08:01:00", "Test"),
                ("o1", "2026-08-15T08:02:00", "Test"),
                ("f1", "2026-08-15T08:03:00", "Test"),
            ],
        )
        connection.executemany(
            "INSERT INTO activity_metadata (activity_id, key, value) VALUES (?, ?, ?)",
            [
                ("p1", "processing_status", "PENDING"),
                ("p2", "processing_status", "PENDING"),
                ("o1", "processing_status", "OCR_COMPLETE"),
                ("f1", "processing_status", "FAILED"),
                ("p1", "unrelated", "PENDING"),
            ],
        )

    repository = ActivitySearchRepository(str(db_path), schema={})

    assert await repository.count_activities_by_metadata("processing_status", "PENDING") == 2
    assert await repository.count_activities_by_metadata("processing_status", "OCR_COMPLETE") == 1
    assert await repository.count_activities_by_metadata("processing_status", "FAILED") == 1
    assert await repository.count_activities_by_metadata("processing_status", "COMPLETED") == 0
