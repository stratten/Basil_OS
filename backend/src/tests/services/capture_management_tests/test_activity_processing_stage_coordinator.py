"""Tests for the independent OCR and sequential analysis coordinator."""

import asyncio
from types import SimpleNamespace

import pytest

from api.services.capture.automatic.activity_processing_stage_coordinator import (
    ActivityProcessingStageCoordinator,
)


class _Queues:
    def __init__(self, pending: list[str], ready: list[str] | None = None) -> None:
        self.rows = {
            "PENDING": [SimpleNamespace(id=item) for item in pending],
            "OCR_COMPLETE": [SimpleNamespace(id=item) for item in (ready or [])],
        }
        self.searches: list[str] = []

    async def search(self, *, metadata_filters, limit):
        status = metadata_filters["processing_status"]
        self.searches.append(status)
        return list(self.rows[status][:limit])

    def move(self, activity, source: str, destination: str) -> None:
        self.rows[source] = [item for item in self.rows[source] if item.id != activity.id]
        self.rows.setdefault(destination, []).append(activity)


@pytest.mark.asyncio
async def test_ocr_and_analysis_overlap_without_parallel_analysis():
    queues = _Queues(["p1", "p2"])
    ocr_started_second = asyncio.Event()
    release_ocr = asyncio.Event()
    analysis_started = asyncio.Event()
    active_analyses = 0
    max_active_analyses = 0
    completions: list[str] = []

    async def ocr(activity):
        if activity.id == "p2":
            ocr_started_second.set()
            await release_ocr.wait()
        queues.move(activity, "PENDING", "OCR_COMPLETE")

    async def analyze(activity):
        nonlocal active_analyses, max_active_analyses
        active_analyses += 1
        max_active_analyses = max(max_active_analyses, active_analyses)
        analysis_started.set()
        await asyncio.sleep(0)
        active_analyses -= 1
        queues.move(activity, "OCR_COMPLETE", "COMPLETED")

    coordinator = ActivityProcessingStageCoordinator(
        search_activities=queues.search,
        process_pending_ocr=ocr,
        process_ocr_complete=analyze,
        publish_analysis_result=lambda activity, error: completions.append(activity.id),
        cancellation_requested=lambda: False,
        max_analysis_records=0,
    )
    task = asyncio.create_task(coordinator.run())
    await asyncio.wait_for(analysis_started.wait(), timeout=1)
    await asyncio.wait_for(ocr_started_second.wait(), timeout=1)
    release_ocr.set()
    result = await asyncio.wait_for(task, timeout=1)

    assert result.analysis_attempts == 2
    assert completions == ["p1", "p2"]
    assert max_active_analyses == 1


@pytest.mark.asyncio
async def test_analysis_receives_only_ocr_complete_records_and_reports_each_result():
    queues = _Queues(["pending"], ["ready-1", "ready-2"])
    analyzed: list[str] = []
    progress: list[tuple[str, bool]] = []

    async def ocr(activity):
        queues.move(activity, "PENDING", "OCR_COMPLETE")

    async def analyze(activity):
        assert activity.id != "pending" or activity in queues.rows["OCR_COMPLETE"]
        analyzed.append(activity.id)
        queues.move(activity, "OCR_COMPLETE", "COMPLETED")

    result = await ActivityProcessingStageCoordinator(
        search_activities=queues.search,
        process_pending_ocr=ocr,
        process_ocr_complete=analyze,
        publish_analysis_result=lambda activity, error: progress.append((activity.id, error is None)),
        cancellation_requested=lambda: False,
        max_analysis_records=0,
    ).run()

    assert analyzed == ["ready-1", "ready-2", "pending"]
    assert progress == [("ready-1", True), ("ready-2", True), ("pending", True)]
    assert result.analysis_attempts == 3
    assert result.analysis_exhausted is True


@pytest.mark.asyncio
async def test_analysis_cap_does_not_stop_ocr_drain():
    queues = _Queues(["p1", "p2", "p3"], ["ready"])
    analyzed: list[str] = []

    async def ocr(activity):
        queues.move(activity, "PENDING", "OCR_COMPLETE")

    async def analyze(activity):
        analyzed.append(activity.id)
        queues.move(activity, "OCR_COMPLETE", "COMPLETED")

    result = await ActivityProcessingStageCoordinator(
        search_activities=queues.search,
        process_pending_ocr=ocr,
        process_ocr_complete=analyze,
        publish_analysis_result=lambda _activity, _error: None,
        cancellation_requested=lambda: False,
        max_analysis_records=1,
    ).run()

    assert result.reached_analysis_cap is True
    assert analyzed == ["ready"]
    assert queues.rows["PENDING"] == []
    assert {item.id for item in queues.rows["OCR_COMPLETE"]} == {"p1", "p2", "p3"}


@pytest.mark.asyncio
async def test_deterministic_ocr_failure_is_not_reselected():
    queues = _Queues(["broken"])
    attempts: list[str] = []

    async def ocr(activity):
        attempts.append(activity.id)
        raise RuntimeError("ocr failed")

    result = await ActivityProcessingStageCoordinator(
        search_activities=queues.search,
        process_pending_ocr=ocr,
        process_ocr_complete=lambda _activity: asyncio.sleep(0),
        publish_analysis_result=lambda _activity, _error: None,
        cancellation_requested=lambda: False,
        max_analysis_records=0,
    ).run()

    assert attempts == ["broken"]
    assert result.analysis_attempts == 0
    assert result.analysis_exhausted is True


@pytest.mark.asyncio
async def test_ocr_completion_wakes_idle_analysis_and_forces_durable_requery():
    queues = _Queues(["pending"])
    analysis_searches_before_completion = 0
    analyzed: list[str] = []

    async def search(*, metadata_filters, limit):
        nonlocal analysis_searches_before_completion
        status = metadata_filters["processing_status"]
        if status == "OCR_COMPLETE" and not queues.rows["OCR_COMPLETE"]:
            analysis_searches_before_completion += 1
        return await queues.search(metadata_filters=metadata_filters, limit=limit)

    async def ocr(activity):
        await asyncio.sleep(0)
        queues.move(activity, "PENDING", "OCR_COMPLETE")

    async def analyze(activity):
        analyzed.append(activity.id)
        queues.move(activity, "OCR_COMPLETE", "COMPLETED")

    result = await asyncio.wait_for(
        ActivityProcessingStageCoordinator(
            search_activities=search,
            process_pending_ocr=ocr,
            process_ocr_complete=analyze,
            publish_analysis_result=lambda _activity, _error: None,
            cancellation_requested=lambda: False,
            max_analysis_records=0,
        ).run(),
        timeout=1,
    )

    assert analysis_searches_before_completion >= 2
    assert queues.searches.count("OCR_COMPLETE") >= 4
    assert analyzed == ["pending"]
    assert result.analysis_exhausted is True


@pytest.mark.asyncio
async def test_progress_callbacks_publish_one_then_two():
    queues = _Queues([], ["ready-1", "ready-2"])
    visible_counts: list[int] = []

    async def analyze(activity):
        queues.move(activity, "OCR_COMPLETE", "COMPLETED")

    await ActivityProcessingStageCoordinator(
        search_activities=queues.search,
        process_pending_ocr=lambda _activity: asyncio.sleep(0),
        process_ocr_complete=analyze,
        publish_analysis_result=lambda _activity, _error: visible_counts.append(
            len(visible_counts) + 1
        ),
        cancellation_requested=lambda: False,
        max_analysis_records=0,
    ).run()

    assert visible_counts == [1, 2]


@pytest.mark.asyncio
async def test_cancellation_finishes_current_stage_items_and_selects_no_more():
    queues = _Queues(["pending-1", "pending-2"], ["ready-1", "ready-2"])
    ocr_started = asyncio.Event()
    analysis_started = asyncio.Event()
    release = asyncio.Event()
    cancelled = False
    ocr_attempts: list[str] = []
    analysis_attempts: list[str] = []

    async def ocr(activity):
        ocr_attempts.append(activity.id)
        ocr_started.set()
        await release.wait()
        queues.move(activity, "PENDING", "OCR_COMPLETE")

    async def analyze(activity):
        analysis_attempts.append(activity.id)
        analysis_started.set()
        await release.wait()
        queues.move(activity, "OCR_COMPLETE", "COMPLETED")

    coordinator = ActivityProcessingStageCoordinator(
        search_activities=queues.search,
        process_pending_ocr=ocr,
        process_ocr_complete=analyze,
        publish_analysis_result=lambda _activity, _error: None,
        cancellation_requested=lambda: cancelled,
        max_analysis_records=0,
    )
    task = asyncio.create_task(coordinator.run())
    await asyncio.wait_for(
        asyncio.gather(ocr_started.wait(), analysis_started.wait()),
        timeout=1,
    )
    cancelled = True
    release.set()
    result = await asyncio.wait_for(task, timeout=1)

    assert ocr_attempts == ["pending-1"]
    assert analysis_attempts == ["ready-1"]
    assert result.analysis_attempts == 1
    assert result.cancelled is True


@pytest.mark.asyncio
async def test_empty_queues_terminate_without_attempts():
    queues = _Queues([])

    result = await asyncio.wait_for(
        ActivityProcessingStageCoordinator(
            search_activities=queues.search,
            process_pending_ocr=lambda _activity: asyncio.sleep(0),
            process_ocr_complete=lambda _activity: asyncio.sleep(0),
            publish_analysis_result=lambda _activity, _error: None,
            cancellation_requested=lambda: False,
            max_analysis_records=0,
        ).run(),
        timeout=1,
    )

    assert result.analysis_attempts == 0
    assert result.analysis_exhausted is True


@pytest.mark.asyncio
async def test_ocr_completion_between_event_clear_and_wait_is_not_lost():
    queues = _Queues(["pending-1", "pending-2"])
    allow_first_ocr = asyncio.Event()
    first_row_moved = asyncio.Event()
    release_first_ocr = asyncio.Event()
    release_second_ocr = asyncio.Event()
    ready_search_count = 0
    analyzed: list[str] = []

    async def search(*, metadata_filters, limit):
        nonlocal ready_search_count
        status = metadata_filters["processing_status"]
        if status == "OCR_COMPLETE":
            ready_search_count += 1
            if ready_search_count == 3:
                empty_result = list(queues.rows["OCR_COMPLETE"])
                allow_first_ocr.set()
                await first_row_moved.wait()
                release_first_ocr.set()
                await asyncio.sleep(0)
                return empty_result
        return await queues.search(metadata_filters=metadata_filters, limit=limit)

    async def ocr(activity):
        if activity.id == "pending-1":
            await allow_first_ocr.wait()
            queues.move(activity, "PENDING", "OCR_COMPLETE")
            first_row_moved.set()
            await release_first_ocr.wait()
        else:
            await release_second_ocr.wait()
            queues.move(activity, "PENDING", "OCR_COMPLETE")

    async def analyze(activity):
        analyzed.append(activity.id)
        queues.move(activity, "OCR_COMPLETE", "COMPLETED")
        release_second_ocr.set()

    await asyncio.wait_for(
        ActivityProcessingStageCoordinator(
            search_activities=search,
            process_pending_ocr=ocr,
            process_ocr_complete=analyze,
            publish_analysis_result=lambda _activity, _error: None,
            cancellation_requested=lambda: False,
            max_analysis_records=0,
        ).run(),
        timeout=1,
    )

    assert analyzed == ["pending-1", "pending-2"]


@pytest.mark.asyncio
async def test_new_records_are_deferred_to_the_next_run():
    queues = _Queues(["admitted-pending"], ["admitted-ready"])
    analyzed: list[str] = []

    async def ocr(activity):
        queues.move(activity, "PENDING", "OCR_COMPLETE")
        queues.rows["PENDING"].append(SimpleNamespace(id="new-pending"))
        queues.rows["OCR_COMPLETE"].append(SimpleNamespace(id="new-ready"))

    async def analyze(activity):
        analyzed.append(activity.id)
        queues.move(activity, "OCR_COMPLETE", "COMPLETED")

    await ActivityProcessingStageCoordinator(
        search_activities=queues.search,
        process_pending_ocr=ocr,
        process_ocr_complete=analyze,
        publish_analysis_result=lambda _activity, _error: None,
        cancellation_requested=lambda: False,
        max_analysis_records=0,
    ).run()

    assert analyzed == ["admitted-ready", "admitted-pending"]
    assert [item.id for item in queues.rows["PENDING"]] == ["new-pending"]
    assert [item.id for item in queues.rows["OCR_COMPLETE"]] == ["new-ready"]


@pytest.mark.asyncio
async def test_analysis_exception_is_reported_once_and_next_item_runs():
    queues = _Queues([], ["broken", "healthy"])
    results: list[tuple[str, str | None]] = []

    async def analyze(activity):
        queues.move(activity, "OCR_COMPLETE", "COMPLETED")
        if activity.id == "broken":
            raise RuntimeError("deterministic analysis failure")

    result = await ActivityProcessingStageCoordinator(
        search_activities=queues.search,
        process_pending_ocr=lambda _activity: asyncio.sleep(0),
        process_ocr_complete=analyze,
        publish_analysis_result=lambda activity, error: results.append(
            (activity.id, str(error) if error else None)
        ),
        cancellation_requested=lambda: False,
        max_analysis_records=0,
    ).run()

    assert results == [
        ("broken", "deterministic analysis failure"),
        ("healthy", None),
    ]
    assert result.analysis_attempts == 2


@pytest.mark.asyncio
async def test_parallel_analysis_admits_eight_cloud_backlog_items():
    queues = _Queues([], [f"ready-{index}" for index in range(8)])
    all_started = asyncio.Event()
    release = asyncio.Event()
    active_analyses = 0
    max_active_analyses = 0
    completed: list[str] = []

    async def analyze(activity):
        nonlocal active_analyses, max_active_analyses
        active_analyses += 1
        max_active_analyses = max(max_active_analyses, active_analyses)
        if active_analyses == 8:
            all_started.set()
        await release.wait()
        active_analyses -= 1
        queues.move(activity, "OCR_COMPLETE", "COMPLETED")

    coordinator = ActivityProcessingStageCoordinator(
        search_activities=queues.search,
        process_pending_ocr=lambda _activity: asyncio.sleep(0),
        process_ocr_complete=analyze,
        publish_analysis_result=lambda activity, _error: completed.append(activity.id),
        cancellation_requested=lambda: False,
        max_analysis_records=0,
        analysis_concurrency=8,
    )
    task = asyncio.create_task(coordinator.run())

    await asyncio.wait_for(all_started.wait(), timeout=1)
    release.set()
    result = await asyncio.wait_for(task, timeout=1)

    assert max_active_analyses == 8
    assert sorted(completed) == [f"ready-{index}" for index in range(8)]
    assert result.analysis_attempts == 8


@pytest.mark.asyncio
async def test_parallel_analysis_never_admits_more_than_its_record_cap():
    queues = _Queues([], [f"ready-{index}" for index in range(8)])
    analyzed: list[str] = []

    async def analyze(activity):
        analyzed.append(activity.id)
        queues.move(activity, "OCR_COMPLETE", "COMPLETED")

    result = await ActivityProcessingStageCoordinator(
        search_activities=queues.search,
        process_pending_ocr=lambda _activity: asyncio.sleep(0),
        process_ocr_complete=analyze,
        publish_analysis_result=lambda _activity, _error: None,
        cancellation_requested=lambda: False,
        max_analysis_records=3,
        analysis_concurrency=8,
    ).run()

    assert result.reached_analysis_cap is True
    assert sorted(analyzed) == ["ready-0", "ready-1", "ready-2"]
    assert sorted(activity.id for activity in queues.rows["OCR_COMPLETE"]) == [
        "ready-3",
        "ready-4",
        "ready-5",
        "ready-6",
        "ready-7",
    ]


@pytest.mark.asyncio
async def test_parallel_cancellation_finishes_admitted_items_without_starting_more():
    queues = _Queues([], [f"ready-{index}" for index in range(9)])
    all_started = asyncio.Event()
    release = asyncio.Event()
    cancelled = False
    started: list[str] = []

    async def analyze(activity):
        started.append(activity.id)
        if len(started) == 8:
            all_started.set()
        await release.wait()
        queues.move(activity, "OCR_COMPLETE", "COMPLETED")

    coordinator = ActivityProcessingStageCoordinator(
        search_activities=queues.search,
        process_pending_ocr=lambda _activity: asyncio.sleep(0),
        process_ocr_complete=analyze,
        publish_analysis_result=lambda _activity, _error: None,
        cancellation_requested=lambda: cancelled,
        max_analysis_records=0,
        analysis_concurrency=8,
    )
    task = asyncio.create_task(coordinator.run())

    await asyncio.wait_for(all_started.wait(), timeout=1)
    cancelled = True
    release.set()
    result = await asyncio.wait_for(task, timeout=1)

    assert sorted(started) == [f"ready-{index}" for index in range(8)]
    assert result.analysis_attempts == 8
    assert result.cancelled is True
    assert [activity.id for activity in queues.rows["OCR_COMPLETE"]] == ["ready-8"]
