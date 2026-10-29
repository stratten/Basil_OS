"""Regression tests for the overnight activity-processing spin.

Captured from a live run that logged 1,077 iterations against a single activity.
Two defects compounded:

1. ``_perform_ai_analysis_only`` returned the whole envelope from
   ``analyze_text_only`` under its own ``"analysis"`` key, so
   ``ai_analysis_result["analysis"]`` was a dict. ``_store_processing_results``
   calls ``.dict()`` on it, raising AttributeError for every activity whose OCR
   was already done - which is the common path.
2. The retry loop read one FAILED activity at a time, newest first, with no
   attempt cap. A failed retry puts the activity straight back into FAILED, so
   the loop re-selected the same row forever, and the other failures behind it
   never got a turn. Each iteration cost a full local model inference.
"""

import asyncio
import logging

import pytest

from api.services.capture.automatic.automatic_activity_processing_service import (
    AutomaticActivityProcessingService,
)
from api.services.image_processing.image_models import ActivityAnalysis
from api.services.image_processing.image_processing_service import ImageProcessor


class _Activity:
    def __init__(self, activity_id: str, app_name: str = "Cursor") -> None:
        self.id = activity_id
        self.app_name = app_name
        self.metadata = {}
        self.extracted_text = "screen text"


class _StubKnowledge:
    """Reports the same activities as FAILED on every query.

    This is what the real database does when a retry raises: the activity is
    marked FAILED again, so the next query returns it right back.
    """

    def __init__(self, failed) -> None:
        self.db_path = "/tmp/basil_retry_loop_test.db"
        self._queues = {
            "PENDING": [],
            "OCR_COMPLETE": [],
            "FAILED": list(failed),
        }

    async def search_activities(self, metadata_filters=None, limit=None):
        status = (metadata_filters or {}).get("processing_status")
        rows = list(self._queues.get(status, []))
        return rows[:limit] if limit else rows

    async def update_activity_metadata(self, activity_id, metadata):
        status = metadata["processing_status"]
        for source, rows in self._queues.items():
            for activity in rows:
                if activity.id == activity_id:
                    if source != status:
                        rows.remove(activity)
                        self._queues.setdefault(status, []).append(activity)
                    activity.metadata["processing_status"] = status
                    return


class _Qwen35ActivityModel:
    handler = "llama_cpp"
    model_name = "Qwen-qwen35-4b-q4km"


class _StubImageProcessor:
    """Stands in for ImageProcessor, returning the real envelope shape."""

    def __init__(self) -> None:
        self.db_path = "/tmp/basil_retry_loop_test.db"

    async def _get_model_for_task(self, capabilities, model_id=None):
        return _Qwen35ActivityModel()

    async def analyze_text_only(
        self, extracted_text, app_name, pre_loaded_model=None, model_id=None, activity_generation_context=None
    ):
        return {
            "analysis": ActivityAnalysis(
                context="Reviewing a pull request",
                content_summary="You worked through review comments.",
                activity_type="coding",
            ),
            "extracted_text": extracted_text,
            "analysis_type": "text-only",
            "processing_time_ms": 5,
        }


class _InstrumentedImageProcessor:
    def __init__(self) -> None:
        self.logger = logging.getLogger("test.activity_image_processing")

    def extract_text(self, _image_path: str) -> str:
        return "private OCR text"

    async def _get_model_for_task(self, capabilities, model_id=None):
        return object()

    async def analyze_text_only(
        self, extracted_text, app_name, pre_loaded_model=None, model_id=None, activity_generation_context=None
    ):
        return {
            "analysis": ActivityAnalysis(
                context="private model output",
                content_summary="private model output",
                activity_type="coding",
            ),
            "analysis_type": "text-only",
            "processing_time_ms": 5,
            "parse_outcome": "success",
            "generation_telemetry": {
                "requested_output_tokens": 4096,
                "finish_reason": "stop",
                "completion_tokens": 12,
                "raw_completion_tokens": 12,
                "visible_completion_tokens": 8,
                "completion_token_source": "usage",
                "lock_wait_ms": 1,
                "native_duration_ms": 10,
            },
        }


def _service(knowledge) -> AutomaticActivityProcessingService:
    return AutomaticActivityProcessingService(
        knowledge, model_service=None, image_processor=_StubImageProcessor()
    )


@pytest.mark.asyncio
async def test_ai_only_analysis_returns_the_analysis_not_its_envelope(caplog):
    """The stored value must be the model, since the caller calls .dict() on it."""
    service = _service(_StubKnowledge([]))
    caplog.set_level(logging.INFO)

    result = await service._perform_ai_analysis_only(
        _Activity("a"),
        "private screen text must not enter diagnostic logs",
    )

    assert isinstance(result["analysis"], ActivityAnalysis)
    # The exact call _store_processing_results makes, and the one that raised.
    assert result["analysis"].dict()["activity_type"] == "coding"
    diagnostic_messages = "\n".join(
        record.getMessage()
        for record in caplog.records
        if "activity_processing_stage" in record.getMessage()
    )
    assert "stage=model_acquisition" in diagnostic_messages
    assert "stage=analysis" in diagnostic_messages
    assert "analysis_requested_tokens=1024" in diagnostic_messages
    assert "private screen text" not in diagnostic_messages


@pytest.mark.asyncio
async def test_a_permanently_failing_activity_is_tried_once_not_forever():
    knowledge = _StubKnowledge([_Activity("stuck")])
    service = _service(knowledge)
    attempts = []

    async def _always_fails(activity):
        attempts.append(activity.id)
        raise RuntimeError("deterministic failure")

    service._process_ocr_complete_activity = _always_fails

    # The pre-fix loop never returns; fail loudly rather than hang the suite.
    result = await asyncio.wait_for(service._process_pending_activities(), timeout=10)

    assert attempts == ["stuck"]
    assert result["total_count"] == 1


@pytest.mark.asyncio
async def test_older_failures_are_not_starved_by_the_newest_one():
    """The newest-first LIMIT 1 read meant older failures were never reached."""
    knowledge = _StubKnowledge([_Activity("newest"), _Activity("middle"), _Activity("oldest")])
    service = _service(knowledge)
    attempts = []

    async def _always_fails(activity):
        attempts.append(activity.id)
        raise RuntimeError("deterministic failure")

    service._process_ocr_complete_activity = _always_fails

    await asyncio.wait_for(service._process_pending_activities(), timeout=10)

    assert attempts == ["newest", "middle", "oldest"]


@pytest.mark.asyncio
async def test_a_recovering_activity_still_gets_its_retry():
    """The cap must not stop a genuine retry from succeeding."""
    knowledge = _StubKnowledge([_Activity("recovers")])
    service = _service(knowledge)
    attempts = []

    async def _succeeds(activity):
        attempts.append(activity.id)

    service._process_ocr_complete_activity = _succeeds

    result = await asyncio.wait_for(service._process_pending_activities(), timeout=10)

    assert attempts == ["recovers"]
    assert result["processed_count"] == 1
    assert result["failed_count"] == 0


@pytest.mark.asyncio
async def test_failed_records_are_restaged_by_available_ocr_text():
    with_text = _Activity("with-text")
    without_text = _Activity("without-text")
    without_text.extracted_text = None
    knowledge = _StubKnowledge([with_text, without_text])
    service = _service(knowledge)

    await service._stage_failed_retry_candidates()

    assert [activity.id for activity in knowledge._queues["OCR_COMPLETE"]] == ["with-text"]
    assert [activity.id for activity in knowledge._queues["PENDING"]] == ["without-text"]
    assert knowledge._queues["FAILED"] == []


@pytest.mark.asyncio
async def test_ai_only_analysis_rejects_error_envelope():
    """Error-shaped analyze_text_only results must not store as COMPLETED."""
    knowledge = _StubKnowledge([])
    service = _service(knowledge)

    async def _error_envelope(*args, **kwargs):
        return {
            "analysis": ActivityAnalysis(
                context="Error during analysis",
                content_summary="Unable to complete analysis due to an error",
                activity_type="error",
            ),
            "extracted_text": "screen text",
            "analysis_type": "error",
            "error": "parse failure",
        }

    service.image_processor.analyze_text_only = _error_envelope  # type: ignore[method-assign]

    result = await service._perform_ai_analysis_only(_Activity("bad"), "screen text")

    with pytest.raises(RuntimeError, match="error during processing"):
        service._raise_if_activity_analysis_unusable(result)


@pytest.mark.asyncio
async def test_full_processing_diagnostics_exclude_capture_content_and_paths(caplog):
    processor = _InstrumentedImageProcessor()
    caplog.set_level(logging.INFO)
    diagnostic_context = {
        "run_id": "run-test",
        "activity_id": "activity-test",
        "analysis_model_id": "local-model",
        "analysis_requested_tokens": 4096,
        "unsafe_capture_content": "must not be logged",
    }

    result = await ImageProcessor.process_image(
        processor,
        "/private/captures/meeting-notes.png",
        model_id="local-model",
        model_stage_semaphore=asyncio.Semaphore(1),
        diagnostic_context=diagnostic_context,
    )

    assert result.analysis_type == "text-only"
    messages = "\n".join(
        record.getMessage()
        for record in caplog.records
        if "activity_image_processing_stage" in record.getMessage()
    )
    assert "stage=ocr" in messages
    assert "stage=model_acquisition" in messages
    assert "stage=analysis" in messages
    assert "analysis_requested_tokens=4096" in messages
    assert "private OCR text" not in messages
    assert "private model output" not in messages
    assert "/private/captures" not in messages
    assert "must not be logged" not in messages
    assert "unsafe_capture_content" not in diagnostic_context
    assert diagnostic_context["generation_telemetry"]["completion_tokens"] == 12
    assert diagnostic_context["parse_outcome"] == "success"

