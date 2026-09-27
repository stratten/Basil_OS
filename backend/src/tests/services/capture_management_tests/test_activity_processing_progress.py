"""Regression tests for activity-capture processing progress and run control."""

import asyncio
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.image_processing.image_models import ActivityAnalysis
from api.routes.capture.activity_routes import (
    cancel_activity_processing,
    clear_backlog,
    get_activity_processing_progress,
)
from api.services.capture.automatic.automatic_activity_processing_service import (
    FAILED_RETRY_WINDOW,
    INTERRUPTED_PROCESSING_ERROR,
    ActivityProcessingProgress,
    AutomaticActivityProcessingService,
    _nearest_rank_percentile,
)
from api.services.capture.automatic.activity_processing_run_policy import (
    ActivityProcessingRunPolicy,
)
from api.services.capture.shared.activity_capture_status import ActivityCaptureStatus


class _Activity:
    def __init__(self, activity_id: str, status: str = "PENDING") -> None:
        self.id = activity_id
        self.app_name = "TestApp"
        self.metadata = {"processing_status": status}
        self.extracted_text = "screen text"


class _StubKnowledge:
    def __init__(self, queues: dict[str, list[_Activity]]) -> None:
        self.db_path = "/tmp/basil_progress_test.db"
        self._queues = {key: list(items) for key, items in queues.items()}
        self.status_updates: list[tuple[str, str]] = []

    async def search_activities(self, metadata_filters=None, limit=None):
        status = (metadata_filters or {}).get("processing_status")
        items = list(self._queues.get(status, []))
        if limit is not None:
            items = items[:limit]
        return items

    async def count_activities_by_metadata(self, key: str, value: str):
        assert key == "processing_status"
        return len(self._queues.get(value, []))

    async def update_activity_metadata(self, activity_id: str, metadata: dict):
        self.status_updates.append((activity_id, metadata["processing_status"]))
        new_status = metadata["processing_status"]
        for status, queue in self._queues.items():
            for index, activity in enumerate(queue):
                if activity.id == activity_id:
                    activity.metadata["processing_status"] = new_status
                    if "error_message" in metadata:
                        activity.metadata["error_message"] = metadata["error_message"]
                    if status != new_status:
                        queue.pop(index)
                        self._queues.setdefault(new_status, []).append(activity)
                    return

    async def update_activity(self, activity_id: str, updates: dict):
        return True


class _Preferences:
    processing_max_records = 0
    processing_model = "test-local-model"


class _PreferenceContainer:
    activity_capture = _Preferences()


def _service(knowledge: _StubKnowledge) -> AutomaticActivityProcessingService:
    return AutomaticActivityProcessingService(
        knowledge, model_service=SimpleNamespace(model_manager=None), image_processor=None
    )


@pytest.mark.asyncio
async def test_clear_backlog_deletes_failed_activity_with_metadata(tmp_path, monkeypatch):
    knowledge = SQLiteKnowledgeService(tmp_path / "clear_backlog.db")
    activity_id = "failed-capture"
    conn = sqlite3.connect(knowledge.db_path)
    conn.execute(
        "INSERT INTO activities (id, timestamp, app_name, window_title) VALUES (?, ?, ?, ?)",
        (activity_id, datetime.now().isoformat(), "TestApp", "No Window"),
    )
    conn.executemany(
        "INSERT INTO activity_metadata (activity_id, key, value) VALUES (?, ?, ?)",
        [
            (activity_id, "automatic_capture", "True"),
            (activity_id, "processing_status", "FAILED"),
            (activity_id, "error_message", "OCR returned no text"),
        ],
    )
    conn.commit()
    conn.close()

    retrieval_runtime = SimpleNamespace(request_reconciliation=MagicMock())
    materializer = SimpleNamespace(run_pass=MagicMock())
    monkeypatch.setattr(
        "api.services.retrieval.index_runtime.get_retrieval_index_runtime",
        lambda: retrieval_runtime,
    )
    monkeypatch.setattr(
        "api.services.zettel.materializer.get_zettel_materializer",
        lambda: materializer,
    )

    response = await clear_backlog(knowledge)

    assert response.success is True
    assert response.data["deleted_count"] == 1
    assert response.data["failed_deleted"] == 1
    conn = sqlite3.connect(knowledge.db_path)
    assert conn.execute(
        "SELECT COUNT(*) FROM activities WHERE id = ?",
        (activity_id,),
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM activity_metadata WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()[0] == 0
    conn.close()


@pytest.mark.asyncio
async def test_cap_of_two_processes_first_two_candidates_only():
    knowledge = _StubKnowledge(
        {
            "PENDING": [_Activity("p1"), _Activity("p2"), _Activity("p3")],
            "OCR_COMPLETE": [],
            "FAILED": [],
        }
    )
    service = _service(knowledge)
    service._Preferences = _PreferenceContainer  # unused guard

    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=_PreferenceContainer(),
    ):
        _PreferenceContainer.activity_capture.processing_max_records = 2

        async def _consume(activity):
            _dequeue_activity(knowledge, activity.id)

        service._process_ocr_complete_activity = AsyncMock(side_effect=_consume)

        await service._start_processing_run()
        await asyncio.wait_for(service._current_processing_task, timeout=5)

    progress = service.get_processing_progress()
    assert progress.processed == 2
    assert progress.succeeded == 2
    assert progress.total == 2
    assert service._process_ocr_complete_activity.await_count == 2


def _dequeue_activity(knowledge: _StubKnowledge, activity_id: str) -> None:
    for status, queue in list(knowledge._queues.items()):
        knowledge._queues[status] = [item for item in queue if item.id != activity_id]


@pytest.mark.asyncio
async def test_zero_cap_processes_all_eligible_records():
    failed = [_Activity(f"f{i}", "FAILED") for i in range(5)]
    knowledge = _StubKnowledge(
        {
            "PENDING": [_Activity("p1")],
            "OCR_COMPLETE": [_Activity("o1", "OCR_COMPLETE")],
            "FAILED": failed,
        }
    )
    service = _service(knowledge)

    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=_PreferenceContainer(),
    ):
        _PreferenceContainer.activity_capture.processing_max_records = 0

        async def _consume(activity):
            _dequeue_activity(knowledge, activity.id)

        service._process_ocr_complete_activity = AsyncMock(side_effect=_consume)

        await service._start_processing_run()
        await asyncio.wait_for(service._current_processing_task, timeout=5)

    progress = service.get_processing_progress()
    expected_total = 1 + 1 + 5
    assert progress.total == expected_total
    assert progress.processed == expected_total
    assert service._process_ocr_complete_activity.await_count == expected_total


@pytest.mark.asyncio
async def test_eligible_count_uses_indexed_metadata_counts_without_hydration():
    knowledge = _StubKnowledge(
        {
            "PENDING": [_Activity("p1")],
            "OCR_COMPLETE": [_Activity("o1", "OCR_COMPLETE")],
            "FAILED": [_Activity("f1", "FAILED")],
        }
    )
    service = _service(knowledge)

    assert await service._calculate_eligible_count() == 3


@pytest.mark.asyncio
async def test_cancellation_finishes_current_item_and_stops_next_selection():
    knowledge = _StubKnowledge(
        {
            "PENDING": [_Activity("p1"), _Activity("p2"), _Activity("p3")],
            "OCR_COMPLETE": [],
            "FAILED": [],
        }
    )
    service = _service(knowledge)

    async def _slow_process(activity):
        if activity.id == "p1":
            service.request_processing_cancellation()
        _dequeue_activity(knowledge, activity.id)
        await asyncio.sleep(0)

    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=_PreferenceContainer(),
    ):
        _PreferenceContainer.activity_capture.processing_max_records = 0
        service._process_ocr_complete_activity = _slow_process

        await service._start_processing_run()
        await asyncio.wait_for(service._current_processing_task, timeout=5)

    progress = service.get_processing_progress()
    assert progress.processed == 1
    assert progress.active is False
    assert progress.cancel_requested is True
    assert knowledge._queues["PENDING"] == []


@pytest.mark.asyncio
async def test_progress_snapshot_updates_on_success_and_failure():
    knowledge = _StubKnowledge(
        {
            "PENDING": [_Activity("ok"), _Activity("bad")],
            "OCR_COMPLETE": [],
            "FAILED": [],
        }
    )
    service = _service(knowledge)

    async def _mixed(activity):
        _dequeue_activity(knowledge, activity.id)
        if activity.id == "bad":
            raise RuntimeError("boom")

    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=_PreferenceContainer(),
    ):
        _PreferenceContainer.activity_capture.processing_max_records = 0
        service._process_ocr_complete_activity = _mixed

        await service._start_processing_run()
        await asyncio.wait_for(service._current_processing_task, timeout=5)

    progress = service.get_processing_progress()
    assert progress.processed == 2
    assert progress.succeeded == 1
    assert progress.failed == 1
    assert progress.last_error == "boom"
    assert progress.active is False


@pytest.mark.asyncio
async def test_staged_logs_record_ocr_reuse_and_persistence_without_text(caplog):
    knowledge = _StubKnowledge({"PENDING": [_Activity("activity-1")], "OCR_COMPLETE": [], "FAILED": []})
    service = _service(knowledge)
    service.image_processor = SimpleNamespace(
        _get_model_for_task=AsyncMock(return_value=SimpleNamespace(handler="llama_cpp")),
        analyze_text_only=AsyncMock(
            return_value={
                "analysis": ActivityAnalysis(
                    activity_type="coding",
                    context="private analysis",
                    content_summary="private analysis",
                ),
                "analysis_type": "text-only",
                "processing_time_ms": 1,
            }
        ),
    )
    service.contact_observation_processor.process = AsyncMock(return_value=0)
    activity = knowledge._queues["PENDING"][0]

    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=_PreferenceContainer(),
    ):
        _PreferenceContainer.activity_capture.processing_model = "model-test"
        caplog.set_level("INFO")
        await service._process_ocr_complete_activity(activity)

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "stage=model_acquisition" in messages
    assert "stage=analysis" in messages
    assert "activity_persistence_stage_completed" in messages
    assert "private analysis" not in messages
    assert "screen text" not in messages


@pytest.mark.asyncio
async def test_pending_ocr_persists_text_before_marking_row_ocr_complete():
    activity = _Activity("needs-ocr")
    activity.extracted_text = None
    activity.metadata["screenshot_path"] = "/tmp/capture.png"
    knowledge = _StubKnowledge({"PENDING": [activity], "OCR_COMPLETE": [], "FAILED": []})
    service = _service(knowledge)
    service.image_processor = SimpleNamespace(extract_text=lambda _path: "fresh OCR text")
    persistence_order: list[str] = []
    original_metadata_update = knowledge.update_activity_metadata

    async def update_activity(activity_id: str, updates: dict):
        assert activity_id == "needs-ocr"
        assert updates == {"extracted_text": "fresh OCR text"}
        persistence_order.append("extracted_text")

    async def update_activity_metadata(activity_id: str, metadata: dict):
        persistence_order.append(metadata["processing_status"])
        await original_metadata_update(activity_id, metadata)

    knowledge.update_activity = update_activity
    knowledge.update_activity_metadata = update_activity_metadata

    await service._process_pending_ocr_activity(activity)

    assert activity.extracted_text == "fresh OCR text"
    assert persistence_order == ["extracted_text", "OCR_COMPLETE"]
    assert knowledge.status_updates == [("needs-ocr", "OCR_COMPLETE")]


@pytest.mark.asyncio
async def test_ocr_complete_without_text_fails_before_model_acquisition():
    activity = _Activity("invalid-ready", "OCR_COMPLETE")
    activity.extracted_text = ""
    knowledge = _StubKnowledge({"PENDING": [], "OCR_COMPLETE": [activity], "FAILED": []})
    service = _service(knowledge)
    service.image_processor = SimpleNamespace(_get_model_for_task=AsyncMock())

    with pytest.raises(RuntimeError, match="OCR_COMPLETE activity has no extracted text"):
        await service._process_ocr_complete_activity(activity)

    service.image_processor._get_model_for_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_stage_workers_overlap_ocr_with_one_sequential_analysis():
    knowledge = _StubKnowledge(
        {
            "PENDING": [_Activity("p1"), _Activity("p2")],
            "OCR_COMPLETE": [],
            "FAILED": [],
        }
    )
    service = _service(knowledge)
    analysis_started = asyncio.Event()
    ocr_started_second = asyncio.Event()
    release_ocr = asyncio.Event()
    analyzed: list[str] = []

    async def _ocr(activity):
        if activity.id == "p2":
            ocr_started_second.set()
            await release_ocr.wait()
        await knowledge.update_activity_metadata(
            activity.id, {"processing_status": "OCR_COMPLETE"}
        )

    async def _analyze(activity):
        analyzed.append(activity.id)
        analysis_started.set()
        _dequeue_activity(knowledge, activity.id)

    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=_PreferenceContainer(),
    ):
        _PreferenceContainer.activity_capture.processing_max_records = 0
        service._process_pending_ocr_activity = _ocr
        service._process_ocr_complete_activity = _analyze
        await service._start_processing_run()
        await asyncio.wait_for(analysis_started.wait(), timeout=5)
        await asyncio.wait_for(ocr_started_second.wait(), timeout=5)
        release_ocr.set()
        await asyncio.wait_for(service._current_processing_task, timeout=5)

    assert analyzed == ["p1", "p2"]


@pytest.mark.asyncio
async def test_max_record_cap_spans_pending_and_failed_retry_candidates():
    knowledge = _StubKnowledge(
        {
            "PENDING": [_Activity("p1")],
            "OCR_COMPLETE": [],
            "FAILED": [_Activity("f1", "FAILED"), _Activity("f2", "FAILED")],
        }
    )
    service = _service(knowledge)
    processed_ids: list[str] = []

    async def _consume(activity):
        processed_ids.append(activity.id)
        _dequeue_activity(knowledge, activity.id)

    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=_PreferenceContainer(),
    ):
        _PreferenceContainer.activity_capture.processing_max_records = 2
        service._process_ocr_complete_activity = _consume
        await service._start_processing_run()
        await asyncio.wait_for(service._current_processing_task, timeout=5)

    assert service.get_processing_progress().processed == 2
    assert len(processed_ids) == 2
    assert {activity.id for activity in knowledge._queues["PENDING"]} == set()
    assert any(activity.id == "p1" for activity in knowledge._queues["OCR_COMPLETE"])


@pytest.mark.asyncio
async def test_concurrent_starts_return_already_in_progress():
    knowledge = _StubKnowledge({"PENDING": [_Activity("p1")], "OCR_COMPLETE": [], "FAILED": []})
    service = _service(knowledge)
    gate = asyncio.Event()

    async def _blocked(_activity):
        await gate.wait()

    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=_PreferenceContainer(),
    ):
        service._process_ocr_complete_activity = _blocked
        first = await service.process_pending_activities_now()
        second = await service.process_pending_activities_now()

    assert first["success"] is True
    assert second["success"] is False
    assert second["message"] == "Processing is already in progress"
    gate.set()
    service.request_processing_cancellation()
    await asyncio.wait_for(service._current_processing_task, timeout=5)


@pytest.mark.asyncio
async def test_manual_cloud_backlog_exposes_parallel_policy_and_clears_it_after_completion(
    monkeypatch,
):
    knowledge = _StubKnowledge(
        {"PENDING": [_Activity("p1")], "OCR_COMPLETE": [], "FAILED": []}
    )
    service = _service(knowledge)
    preferences = SimpleNamespace(
        activity_capture=SimpleNamespace(
            processing_max_records=0,
            processing_model="cloud-model",
        )
    )

    async def consume(activity):
        _dequeue_activity(knowledge, activity.id)

    monkeypatch.setattr(
        "api.services.capture.automatic.activity_processing_run_policy.get_model",
        lambda model_id: {"location": "cloud"} if model_id == "cloud-model" else None,
    )
    service._process_ocr_complete_activity = consume
    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=preferences,
    ):
        response = await service.process_pending_activities_now()
        assert response["progress"]["analysis_concurrency"] == 8
        assert response["progress"]["processing_strategy"] == "api_parallel"
        await asyncio.wait_for(service._current_processing_task, timeout=5)

    assert service.get_processing_progress().analysis_concurrency == 8
    assert service.get_processing_progress().processing_strategy == "api_parallel"
    assert service._active_run_policy is None


@pytest.mark.asyncio
async def test_scheduled_cloud_run_remains_serial(monkeypatch):
    knowledge = _StubKnowledge(
        {"PENDING": [_Activity("p1")], "OCR_COMPLETE": [], "FAILED": []}
    )
    service = _service(knowledge)
    preferences = SimpleNamespace(
        activity_capture=SimpleNamespace(
            processing_max_records=0,
            processing_model="cloud-model",
        )
    )

    async def consume(activity):
        _dequeue_activity(knowledge, activity.id)

    monkeypatch.setattr(
        "api.services.capture.automatic.activity_processing_run_policy.get_model",
        lambda model_id: {"location": "cloud"} if model_id == "cloud-model" else None,
    )
    service._process_ocr_complete_activity = consume
    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=preferences,
    ):
        await service._start_processing_run(is_manual_backlog_run=False)
        await asyncio.wait_for(service._current_processing_task, timeout=5)

    assert service.get_processing_progress().analysis_concurrency == 1
    assert service.get_processing_progress().processing_strategy == "sequential"


@pytest.mark.asyncio
async def test_manual_run_keeps_the_model_snapshot_after_preferences_change(monkeypatch):
    knowledge = _StubKnowledge(
        {"PENDING": [_Activity("p1")], "OCR_COMPLETE": [], "FAILED": []}
    )
    service = _service(knowledge)
    preferences = SimpleNamespace(
        activity_capture=SimpleNamespace(
            processing_max_records=0,
            processing_model="cloud-model",
        )
    )
    started = asyncio.Event()
    release = asyncio.Event()
    observed_model_ids: list[str] = []

    async def consume(activity):
        observed_model_ids.append(service._active_run_policy.model_id)
        started.set()
        await release.wait()
        _dequeue_activity(knowledge, activity.id)

    monkeypatch.setattr(
        "api.services.capture.automatic.activity_processing_run_policy.get_model",
        lambda model_id: (
            {"location": "cloud"}
            if model_id == "cloud-model"
            else {"location": "local"}
            if model_id == "local-model"
            else None
        ),
    )
    service._process_ocr_complete_activity = consume
    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=preferences,
    ):
        await service.process_pending_activities_now()
        await asyncio.wait_for(started.wait(), timeout=5)
        preferences.activity_capture.processing_model = "local-model"
        release.set()
        await asyncio.wait_for(service._current_processing_task, timeout=5)

    assert observed_model_ids == ["cloud-model"]


@pytest.mark.asyncio
async def test_api_analysis_invocation_uses_the_active_run_model_snapshot():
    activity = _Activity("snapshot", "OCR_COMPLETE")
    knowledge = _StubKnowledge({"PENDING": [], "OCR_COMPLETE": [activity], "FAILED": []})
    service = _service(knowledge)
    service._active_run_policy = ActivityProcessingRunPolicy(
        model_id="cloud-model",
        analysis_concurrency=8,
        processing_strategy="api_parallel",
    )
    service.image_processor = SimpleNamespace(
        _get_model_for_task=AsyncMock(return_value=SimpleNamespace(handler="openai_api")),
        analyze_text_only=AsyncMock(
            return_value={
                "analysis": ActivityAnalysis(
                    activity_type="coding",
                    context="analysis",
                    content_summary="analysis",
                ),
                "analysis_type": "text-only",
                "processing_time_ms": 1,
            }
        ),
    )
    preferences = SimpleNamespace(
        activity_capture=SimpleNamespace(processing_model="local-model")
    )

    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=preferences,
    ):
        await service._perform_ai_analysis_only(activity, activity.extracted_text)

    assert service.image_processor._get_model_for_task.await_args.kwargs["model_id"] == "cloud-model"
    assert service.image_processor.analyze_text_only.await_args.kwargs["model_id"] == "cloud-model"


@pytest.mark.asyncio
async def test_api_parallel_run_releases_model_semaphore_before_the_http_call():
    """Two concurrent api_parallel analyses must overlap their analyze_text_only calls.

    The model-acquisition semaphore must be released before the network call, or
    concurrent backlog analyses would still be serialized behind it and the whole
    parallelism feature would be a no-op.
    """
    activity_one = _Activity("overlap-1", "OCR_COMPLETE")
    activity_two = _Activity("overlap-2", "OCR_COMPLETE")
    knowledge = _StubKnowledge({"PENDING": [], "OCR_COMPLETE": [], "FAILED": []})
    service = _service(knowledge)
    service._active_run_policy = ActivityProcessingRunPolicy(
        model_id="cloud-model",
        analysis_concurrency=8,
        processing_strategy="api_parallel",
    )

    active_calls = 0
    max_concurrent_calls = 0
    both_entered = asyncio.Event()

    async def fake_analyze_text_only(*args, **kwargs):
        nonlocal active_calls, max_concurrent_calls
        active_calls += 1
        max_concurrent_calls = max(max_concurrent_calls, active_calls)
        if active_calls == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), timeout=5)
        active_calls -= 1
        return {
            "analysis": ActivityAnalysis(
                activity_type="coding", context="analysis", content_summary="analysis"
            ),
            "analysis_type": "text-only",
            "processing_time_ms": 1,
        }

    service.image_processor = SimpleNamespace(
        _get_model_for_task=AsyncMock(return_value=SimpleNamespace(handler="openai_api")),
        analyze_text_only=fake_analyze_text_only,
    )
    preferences = SimpleNamespace(
        activity_capture=SimpleNamespace(processing_model="local-model")
    )

    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=preferences,
    ):
        await asyncio.wait_for(
            asyncio.gather(
                service._perform_ai_analysis_only(activity_one, activity_one.extracted_text),
                service._perform_ai_analysis_only(activity_two, activity_two.extracted_text),
            ),
            timeout=5,
        )

    assert max_concurrent_calls == 2


@pytest.mark.asyncio
async def test_sequential_run_holds_model_semaphore_across_the_http_call():
    """A sequential (non-api_parallel) run must serialize the analysis call itself."""
    activity_one = _Activity("serial-1", "OCR_COMPLETE")
    activity_two = _Activity("serial-2", "OCR_COMPLETE")
    knowledge = _StubKnowledge({"PENDING": [], "OCR_COMPLETE": [], "FAILED": []})
    service = _service(knowledge)
    service._active_run_policy = ActivityProcessingRunPolicy(
        model_id="local-model",
        analysis_concurrency=1,
        processing_strategy="sequential",
    )

    active_calls = 0
    max_concurrent_calls = 0

    async def fake_analyze_text_only(*args, **kwargs):
        nonlocal active_calls, max_concurrent_calls
        active_calls += 1
        max_concurrent_calls = max(max_concurrent_calls, active_calls)
        await asyncio.sleep(0.01)
        active_calls -= 1
        return {
            "analysis": ActivityAnalysis(
                activity_type="coding", context="analysis", content_summary="analysis"
            ),
            "analysis_type": "text-only",
            "processing_time_ms": 1,
        }

    service.image_processor = SimpleNamespace(
        _get_model_for_task=AsyncMock(return_value=SimpleNamespace(handler="local")),
        analyze_text_only=fake_analyze_text_only,
    )
    preferences = SimpleNamespace(
        activity_capture=SimpleNamespace(processing_model="local-model")
    )

    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=preferences,
    ):
        await asyncio.wait_for(
            asyncio.gather(
                service._perform_ai_analysis_only(activity_one, activity_one.extracted_text),
                service._perform_ai_analysis_only(activity_two, activity_two.extracted_text),
            ),
            timeout=5,
        )

    assert max_concurrent_calls == 1


@pytest.mark.asyncio
async def test_recovery_marks_only_processing_rows_failed():
    knowledge = _StubKnowledge(
        {
            "PROCESSING": [_Activity("proc1", "PROCESSING"), _Activity("proc2", "PROCESSING")],
            "PENDING": [_Activity("pending1")],
            "OCR_COMPLETE": [_Activity("ocr1", "OCR_COMPLETE")],
            "FAILED": [],
            "COMPLETED": [_Activity("done1", "COMPLETED")],
        }
    )
    service = _service(knowledge)

    recovered = await service.recover_interrupted_processing_activities()

    assert recovered == 2
    assert knowledge._queues.get("PROCESSING", []) == []
    failed_items = knowledge._queues.get("FAILED", [])
    assert len(failed_items) == 2
    assert all(
        activity.metadata.get("error_message") == INTERRUPTED_PROCESSING_ERROR
        for activity in failed_items
    )
    assert knowledge._queues["PENDING"][0].metadata["processing_status"] == "PENDING"
    assert knowledge._queues["OCR_COMPLETE"][0].metadata["processing_status"] == "OCR_COMPLETE"
    assert knowledge._queues["COMPLETED"][0].metadata["processing_status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_progress_route_is_read_only():
    service = _service(_StubKnowledge({"PENDING": [], "OCR_COMPLETE": [], "FAILED": []}))
    service._processing_progress = ActivityProcessingProgress(
        active=True,
        total=3,
        processed=1,
        succeeded=1,
        failed=0,
        remaining=2,
        started_at=datetime.now() - timedelta(seconds=10),
        max_records=0,
        analysis_concurrency=8,
        processing_strategy="api_parallel",
    )

    response = await get_activity_processing_progress(processing_service=service)

    assert response.total == 3
    assert response.processed == 1
    assert response.active is True
    assert response.eta_seconds is not None
    assert response.eta_seconds > 0
    assert response.analysis_concurrency == 8
    assert response.processing_strategy == "api_parallel"


@pytest.mark.asyncio
async def test_cancel_route_is_idempotent_when_inactive():
    service = _service(_StubKnowledge({"PENDING": [], "OCR_COMPLETE": [], "FAILED": []}))

    response = await cancel_activity_processing(processing_service=service)

    assert response.success is True
    assert response.data == {"cancel_requested": False}


@pytest.mark.asyncio
async def test_cancel_route_describes_both_stage_workers_when_active():
    service = _service(_StubKnowledge({"PENDING": [], "OCR_COMPLETE": [], "FAILED": []}))
    service._processing_progress = ActivityProcessingProgress(active=True)

    response = await cancel_activity_processing(processing_service=service)

    assert response.data == {"cancel_requested": True}
    assert response.message == "Stopping after the current OCR and analysis work finish."


def _sample_generation_telemetry(
    *,
    completion_tokens: int | None = 120,
    raw_completion_tokens: int | None = 180,
    visible_completion_tokens: int | None = 90,
    finish_reason: str = "stop",
    completion_token_source: str = "usage",
) -> dict[str, object]:
    return {
        "requested_output_tokens": 4096,
        "finish_reason": finish_reason,
        "cap_hit": finish_reason == "length",
        "prompt_tokens": 500,
        "completion_tokens": completion_tokens,
        "total_tokens": (500 + completion_tokens) if completion_tokens is not None else None,
        "completion_token_source": completion_token_source,
        "raw_completion_tokens": raw_completion_tokens,
        "visible_completion_tokens": visible_completion_tokens,
        "lock_wait_ms": 3,
        "native_duration_ms": 7000,
        "completed_at_monotonic_ms": 123456,
    }


@pytest.mark.asyncio
async def test_activity_local_generation_event_includes_token_and_parse_fields():
    knowledge = _StubKnowledge({"PENDING": [_Activity("activity-1")], "OCR_COMPLETE": [], "FAILED": []})
    service = _service(knowledge)
    telemetry = _sample_generation_telemetry()

    async def _analyze_with_telemetry(*args, **kwargs):
        return {
            "analysis": ActivityAnalysis(
                activity_type="coding",
                context="analysis",
                content_summary="analysis",
            ),
            "analysis_type": "text-only",
            "processing_time_ms": 1,
            "generation_telemetry": telemetry,
            "parse_outcome": "success",
        }

    service.image_processor = SimpleNamespace(
        _get_model_for_task=AsyncMock(return_value=SimpleNamespace(handler="llama_cpp")),
        analyze_text_only=AsyncMock(side_effect=_analyze_with_telemetry),
    )
    service.contact_observation_processor.process = AsyncMock(return_value=0)

    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=_PreferenceContainer(),
    ):
        _PreferenceContainer.activity_capture.processing_model = "model-test"
        await service._process_ocr_complete_activity(knowledge._queues["PENDING"][0])

    assert service._generation_telemetry_for_run == [{**telemetry, "parse_outcome": "success"}]
    service.image_processor.analyze_text_only.assert_awaited_once()
    call_kwargs = service.image_processor.analyze_text_only.await_args.kwargs
    assert call_kwargs["activity_generation_context"]["analysis_requested_tokens"] == 4096
    assert call_kwargs["activity_generation_context"]["activity_id"] == "activity-1"
    assert "unsafe_field" not in call_kwargs["activity_generation_context"]


@pytest.mark.asyncio
async def test_generation_summary_computes_median_and_p95_from_known_values(caplog):
    knowledge = _StubKnowledge(
        {
            "PENDING": [_Activity("p1"), _Activity("p2"), _Activity("p3")],
            "OCR_COMPLETE": [],
            "FAILED": [],
        }
    )
    service = _service(knowledge)

    async def _record_telemetry(activity):
        index = {"p1": 100, "p2": 200, "p3": 300}[activity.id]
        service._record_generation_telemetry(
            {
                **_sample_generation_telemetry(
                    completion_tokens=index,
                    raw_completion_tokens=index,
                    visible_completion_tokens=index,
                ),
                "parse_outcome": "success",
            }
        )
        _dequeue_activity(knowledge, activity.id)

    with patch(
        "api.core.preferences.preferences_io.load_preferences",
        return_value=_PreferenceContainer(),
    ):
        _PreferenceContainer.activity_capture.processing_max_records = 0
        service._process_ocr_complete_activity = _record_telemetry
        caplog.set_level("INFO")
        await service._start_processing_run()
        await asyncio.wait_for(service._current_processing_task, timeout=5)

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "activity_processing_generation_summary" in messages
    assert "attempt_count=3" in messages
    assert "known_completion_count=3" in messages
    assert "completion_tokens_min=100" in messages
    assert "completion_tokens_median=200" in messages
    assert "completion_tokens_p95=300" in messages
    assert "completion_tokens_max=300" in messages


@pytest.mark.asyncio
async def test_generation_summary_remains_valid_when_usage_is_unavailable(caplog):
    service = _service(_StubKnowledge({"PENDING": [], "OCR_COMPLETE": [], "FAILED": []}))
    service._processing_run_id = "run-unavailable"
    service._record_generation_telemetry(
        {
            **_sample_generation_telemetry(
                completion_tokens=None,
                raw_completion_tokens=None,
                visible_completion_tokens=None,
                completion_token_source="unavailable",
            ),
            "parse_outcome": "error",
        }
    )

    caplog.set_level("INFO")
    service._emit_generation_summary("run-unavailable")

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "activity_processing_generation_summary" in messages
    assert "known_completion_count=0" in messages
    assert "completion_tokens_min=None" in messages
    assert "parse_error_count=1" in messages


def test_nearest_rank_percentile_uses_ceil_for_non_integral_rank():
    assert _nearest_rank_percentile(list(range(1, 12)), 95.0) == 11


@pytest.mark.asyncio
async def test_generation_summary_counts_tokenizer_fallback_raw_tokens(caplog):
    service = _service(_StubKnowledge({"PENDING": [], "OCR_COMPLETE": [], "FAILED": []}))
    service._record_generation_telemetry(
        {
            **_sample_generation_telemetry(
                completion_tokens=None,
                raw_completion_tokens=42,
                visible_completion_tokens=30,
                completion_token_source="tokenizer_fallback",
            ),
            "parse_outcome": "success",
        }
    )

    caplog.set_level("INFO")
    service._emit_generation_summary("run-fallback")

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "known_completion_count=1" in messages
    assert "completion_tokens_min=42" in messages
