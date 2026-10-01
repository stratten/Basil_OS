"""Coordinate independent OCR preparation and sequential activity analysis."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, List, Optional


@dataclass(frozen=True)
class ActivityProcessingStageRunResult:
    """Outcome of one coordinated OCR and analysis run."""

    analysis_attempts: int
    reached_analysis_cap: bool
    canceled: bool
    analysis_exhausted: bool


class ActivityProcessingStageCoordinator:
    """Run one PENDING OCR worker and a bounded OCR_COMPLETE analysis pool."""

    def __init__(
        self,
        *,
        search_activities: Callable[..., Awaitable[List[Any]]],
        process_pending_ocr: Callable[[Any], Awaitable[None]],
        process_ocr_complete: Callable[[Any], Awaitable[None]],
        publish_analysis_result: Callable[[Any, Optional[BaseException]], None],
        cancellation_requested: Callable[[], bool],
        max_analysis_records: int,
        analysis_concurrency: int = 1,
        candidate_window: int = 1000,
    ) -> None:
        if analysis_concurrency < 1:
            raise ValueError("analysis_concurrency must be at least 1")
        self._search_activities = search_activities
        self._process_pending_ocr = process_pending_ocr
        self._process_ocr_complete = process_ocr_complete
        self._publish_analysis_result = publish_analysis_result
        self._cancellation_requested = cancellation_requested
        self._max_analysis_records = max_analysis_records
        self._analysis_concurrency = analysis_concurrency
        self._candidate_window = candidate_window
        self._ocr_ready = asyncio.Event()
        self._ocr_finished = asyncio.Event()
        self._attempted_ocr_ids: set[str] = set()
        self._attempted_analysis_ids: set[str] = set()
        self._admitted_ocr_ids: set[str] = set()
        self._admitted_analysis_ids: set[str] = set()
        self._analysis_admissions = 0
        self._analysis_attempts = 0
        self._reached_analysis_cap = False
        self._analysis_exhausted = False

    async def run(self) -> ActivityProcessingStageRunResult:
        """Run both stage workers until exhausted, capped, or canceled."""
        pending, ocr_complete = await asyncio.gather(
            self._search_activities(
                metadata_filters={"processing_status": "PENDING"},
                limit=self._candidate_window,
            ),
            self._search_activities(
                metadata_filters={"processing_status": "OCR_COMPLETE"},
                limit=self._candidate_window,
            ),
        )
        self._admitted_ocr_ids = {activity.id for activity in pending}
        self._admitted_analysis_ids = {activity.id for activity in ocr_complete}
        ocr_task = asyncio.create_task(self._run_ocr_worker())
        analysis_task = asyncio.create_task(self._run_analysis_workers())
        try:
            await asyncio.gather(ocr_task, analysis_task)
        finally:
            for task in (ocr_task, analysis_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(ocr_task, analysis_task, return_exceptions=True)
        return ActivityProcessingStageRunResult(
            analysis_attempts=self._analysis_attempts,
            reached_analysis_cap=self._reached_analysis_cap,
            canceled=self._cancellation_requested(),
            analysis_exhausted=self._analysis_exhausted,
        )

    async def _run_ocr_worker(self) -> None:
        try:
            while not self._cancellation_requested():
                activity = await self._select_unattempted(
                    "PENDING",
                    self._attempted_ocr_ids,
                    self._admitted_ocr_ids,
                )
                if activity is None:
                    return
                self._attempted_ocr_ids.add(activity.id)
                try:
                    await self._process_pending_ocr(activity)
                    self._admitted_analysis_ids.add(activity.id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
                finally:
                    self._ocr_ready.set()
        finally:
            self._ocr_finished.set()
            self._ocr_ready.set()

    async def _run_analysis_workers(self) -> None:
        in_flight: set[asyncio.Task[None]] = set()
        while True:
            while (
                not self._cancellation_requested()
                and len(in_flight) < self._analysis_concurrency
            ):
                if (
                    self._max_analysis_records > 0
                    and self._analysis_admissions >= self._max_analysis_records
                ):
                    self._reached_analysis_cap = True
                    break

                activity = await self._select_unattempted(
                    "OCR_COMPLETE",
                    self._attempted_analysis_ids,
                    self._admitted_analysis_ids,
                )
                if activity is None:
                    break
                if self._cancellation_requested():
                    break

                self._attempted_analysis_ids.add(activity.id)
                self._analysis_admissions += 1
                in_flight.add(
                    asyncio.create_task(self._process_analysis_activity(activity))
                )

            if in_flight:
                completed, in_flight = await asyncio.wait(
                    in_flight,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                await asyncio.gather(*completed)
                continue

            if self._cancellation_requested():
                return

            if (
                self._max_analysis_records > 0
                and self._analysis_admissions >= self._max_analysis_records
            ):
                self._reached_analysis_cap = True
                return

            if self._ocr_finished.is_set():
                activity = await self._select_unattempted(
                    "OCR_COMPLETE",
                    self._attempted_analysis_ids,
                    self._admitted_analysis_ids,
                )
                if activity is None:
                    self._analysis_exhausted = True
                    return
                continue

            self._ocr_ready.clear()
            activity = await self._select_unattempted(
                "OCR_COMPLETE",
                self._attempted_analysis_ids,
                self._admitted_analysis_ids,
            )
            if activity is not None:
                continue

            if self._ocr_finished.is_set():
                continue
            await self._ocr_ready.wait()

    async def _select_unattempted(
        self,
        status: str,
        attempted_ids: set[str],
        admitted_ids: set[str],
    ) -> Any | None:
        candidates = await self._search_activities(
            metadata_filters={"processing_status": status},
            limit=self._candidate_window,
        )
        return next(
            (
                activity
                for activity in candidates
                if activity.id in admitted_ids and activity.id not in attempted_ids
            ),
            None,
        )

    async def _process_analysis_activity(self, activity: Any) -> None:
        error: Optional[BaseException] = None
        try:
            await self._process_ocr_complete(activity)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = exc
        self._analysis_attempts += 1
        self._publish_analysis_result(activity, error)
