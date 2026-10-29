"""Regression tests for direct SQLite activity-processing initialization.

Root cause (captured from the backend startup traceback): initializing the
automatic activity services constructed AutomaticActivityProcessingService, whose
__init__ builds ActivityContactObservationProcessor, which needs
`ContactObservationsManager(knowledge_service.db_path)`. A wrapper that did not
expose that path raised AttributeError, left the processing-service global as None, and every
`/activity-capture/status` request 500'd at the get_automatic_processing_service
dependency.

These tests prove the direct SQLite service used at runtime exposes the required
database path.
"""

import pytest

from api.routes.capture.activity_routes import get_activity_capture_status
from api.services.capture.automatic.activity_contact_observation_processor import (
    ActivityContactObservationProcessor,
)
from api.services.capture.automatic.automatic_activity_processing_service import (
    AutomaticActivityProcessingService,
)


class _StubSqlite:
    """SQLite-style service that exposes db_path directly."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path


def test_processor_still_accepts_direct_db_path_service() -> None:
    service = _StubSqlite("/tmp/basil_direct.db")

    processor = ActivityContactObservationProcessor(service, image_processor=None)

    assert processor.observations_manager.db_path == "/tmp/basil_direct.db"


def test_processing_service_constructs_with_direct_sqlite_service() -> None:
    """AC-B: startup construction requires the direct canonical SQLite service.

    Successful construction means the processing-service global is set at startup,
    so the get_automatic_processing_service dependency returns non-None and
    /activity-capture/status no longer 500s at dependency resolution.
    """
    knowledge_service = _StubSqlite("/tmp/basil_knowledge.db")

    service = AutomaticActivityProcessingService(
        knowledge_service, model_service=None, image_processor=None
    )

    assert (
        service.contact_observation_processor.observations_manager.db_path
        == "/tmp/basil_knowledge.db"
    )


@pytest.mark.asyncio
async def test_status_returns_persisted_metrics_without_runtime_services(monkeypatch) -> None:
    """A restart preserves durable counts without reporting a missing scheduler as active."""

    class _Activity:
        def __init__(self, metadata):
            self.metadata = metadata

    class _KnowledgeService:
        async def search_activities(self, metadata_filters=None, **_kwargs):
            status = (metadata_filters or {}).get("processing_status")
            if status == "PENDING":
                return [_Activity({}), _Activity({})]
            if status == "OCR_COMPLETE":
                return [_Activity({})]
            if status == "FAILED":
                return [_Activity({}), _Activity({})]
            return [_Activity({"automatic_capture": True})]

        async def count_automatic_captures_since(self, cutoff):
            return 5

    class _Preferences:
        enabled = True
        frequency_minutes = 2.0

    class _PreferenceContainer:
        activity_capture = _Preferences()

    monkeypatch.setattr(
        "api.routes.capture.activity_routes.get_automatic_capture_service_instance",
        lambda: None,
    )
    monkeypatch.setattr(
        "api.core.models.preferences.Preferences.load",
        lambda: _PreferenceContainer(),
    )

    response = await get_activity_capture_status(knowledge_service=_KnowledgeService())

    assert response.enabled is False
    assert response.frequency_minutes == 2.0
    assert response.last_capture_time is None
    assert response.next_capture_time is None
    assert response.total_captures_today == 1
    assert response.total_captures_last_7_days == 5
    assert response.total_captures_last_30_days == 5
    assert response.pending_captures_count == 3
    assert response.failed_captures_count == 2
