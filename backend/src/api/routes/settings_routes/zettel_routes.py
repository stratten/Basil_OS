"""Unified event stream (zettel) settings routes."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException

from api.core.logging.api_logger import api_logger
from api.core.models.preferences import ZettelSettings
from api.core.models.responses import SettingsResponse, UpdateResponse
from api.core.preferences.preferences_io import load_preferences, save_preferences
from api.routes.settings_routes.models import (
    NarrativeProgressResponse,
    ZettelSettingsUpdate,
    ZettelStatsResponse,
)


router = APIRouter(prefix="/zettel", tags=["zettel"])


@router.get("", response_model=SettingsResponse[ZettelSettings])
async def get_zettel_settings() -> SettingsResponse[ZettelSettings]:
    """Get current unified event stream settings."""
    try:
        preferences = load_preferences()
        return SettingsResponse(settings=preferences.zettel)
    except Exception as exc:
        api_logger.error(f"Error getting zettel settings: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("", response_model=UpdateResponse[ZettelSettings])
async def update_zettel_settings(
    settings: ZettelSettingsUpdate,
) -> UpdateResponse[ZettelSettings]:
    """Update unified event stream settings.

    Bounds mirror the Field constraints on ZettelSettings so an out-of-range
    value is rejected as a 400 here rather than raising during load.
    """
    try:
        preferences = load_preferences()
        updates = settings.model_dump(exclude_unset=True)

        _INT_BOUNDS = {
            "history_days": (0, 3650, "History window (days)"),
            "carding_interval_minutes": (1, 1440, "Carding interval (minutes)"),
            "limit_per_source_per_pass": (50, 5000, "Limit per source per pass"),
            "narrative_interval_minutes": (1, 1440, "Narrative interval (minutes)"),
            "narrative_batch_size": (1, 1000, "Narrative batch size"),
            "narrative_max_attempts": (1, 10, "Narrative max attempts"),
            "narrative_max_records": (0, 100000, "Narrative max records"),
        }
        for field_name, value in updates.items():
            if field_name in _INT_BOUNDS and value is not None:
                low, high, label = _INT_BOUNDS[field_name]
                _validate_range(value, low, high, label)
            if field_name == "narrative_mode" and value not in (None, "scheduled", "continuous"):
                raise ValueError("Narrative mode must be 'scheduled' or 'continuous'.")
            if field_name == "narrative_scheduled_time" and value is not None:
                _validate_hhmm(value)
            if field_name == "enabled_sources" and value is not None:
                _validate_sources(value)
            setattr(preferences.zettel, field_name, value)

        save_preferences(preferences)
        await _apply_to_running_schedulers(preferences.zettel)
        return UpdateResponse(
            updated_settings=preferences.zettel,
            message="Unified event stream settings updated successfully",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        api_logger.error(f"Error updating zettel settings: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/stats", response_model=ZettelStatsResponse)
async def get_zettel_stats() -> ZettelStatsResponse:
    """Read-only progress counters for the settings UI.

    Scoped to the same window (history_days) and source set (enabled_sources)
    as the carding pass so "collected" and "waiting to be collected" reconcile.
    The counts run off the event loop because they scan source tables.
    """
    try:
        from api.services.zettel.materializer import (
            get_zettel_materializer,
            since_iso_for_days,
        )

        zettel = load_preferences().zettel
        since_iso = since_iso_for_days(int(getattr(zettel, "history_days", 30) or 0))
        enabled = getattr(zettel, "enabled_sources", None)
        enabled_kinds = set(enabled) if enabled else None
        data = await asyncio.to_thread(
            get_zettel_materializer().stats,
            since_iso=since_iso,
            enabled_kinds=enabled_kinds,
            narrative_max_attempts=int(
                getattr(zettel, "narrative_max_attempts", 3) or 3
            ),
        )
        return ZettelStatsResponse(**data)
    except Exception as exc:
        api_logger.error(f"Error getting zettel stats: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/carding/run-now", response_model=UpdateResponse[ZettelSettings])
async def run_carding_now() -> UpdateResponse[ZettelSettings]:
    """Trigger one carding pass immediately (cheap, model-free collection)."""
    try:
        from api.services.zettel.scheduler import get_zettel_scheduler

        error = await get_zettel_scheduler().run_now()
        preferences = load_preferences()
        return UpdateResponse(
            updated_settings=preferences.zettel,
            message=error or "Collection pass completed.",
        )
    except Exception as exc:
        api_logger.error(f"Error running carding pass: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/narrative/run-now", response_model=UpdateResponse[ZettelSettings])
async def run_narrative_now() -> UpdateResponse[ZettelSettings]:
    """Kick one narrative finalizing pass in the background and return at once.

    The pass drains the whole backlog and can run long, so it must not hold the
    request open. Poll GET /zettel/narrative/progress for live status.
    """
    try:
        from api.services.zettel.narrative_scheduler import get_zettel_narrative_scheduler

        get_zettel_narrative_scheduler().run_now_background()
        preferences = load_preferences()
        return UpdateResponse(
            updated_settings=preferences.zettel,
            message="Summaries started.",
        )
    except Exception as exc:
        api_logger.error(f"Error running narrative pass: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/narrative/retry-failed", response_model=UpdateResponse[ZettelSettings])
async def retry_failed_narratives() -> UpdateResponse[ZettelSettings]:
    """Reset unfinished narrative entries without starting a summarize pass."""
    try:
        from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.infrastructure.connection import (
            get_sync_connection,
        )
        from api.dependencies import get_sqlite_knowledge_service
        from api.services.zettel import store

        def _requeue() -> int:
            with get_sync_connection(get_sqlite_knowledge_service().db_path) as conn:
                count = store.requeue_failed(conn)
                conn.commit()
                return count

        requeued = await asyncio.to_thread(_requeue)
        preferences = load_preferences()
        return UpdateResponse(
            updated_settings=preferences.zettel,
            message=f"{requeued} unfinished entries reset. Start summarization when ready.",
        )
    except Exception as exc:
        api_logger.error(f"Error retrying failed narratives: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/narrative/cancel", response_model=UpdateResponse[ZettelSettings])
async def cancel_narrative_pass() -> UpdateResponse[ZettelSettings]:
    """Ask an in-flight summarize pass to stop after admitted entries finish.

    Cooperative rather than a task cancellation, so entries already being generated finish and are recorded normally instead of being abandoned mid-call. Entries not yet admitted stay 'pending' and are picked up by a later pass.
    """
    try:
        from api.services.zettel.narrative.enricher import get_zettel_enricher

        canceled = get_zettel_enricher().request_cancel()
        preferences = load_preferences()
        return UpdateResponse(
            updated_settings=preferences.zettel,
            message=(
                "Stopping summaries after items in progress."
                if canceled
                else "No summarize pass is running."
            ),
        )
    except Exception as exc:
        api_logger.error(f"Error canceling narrative pass: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/narrative/progress", response_model=NarrativeProgressResponse)
async def get_narrative_progress() -> NarrativeProgressResponse:
    """Live progress of the current (or most recent) summarize run."""
    try:
        from api.services.zettel.narrative_scheduler import get_zettel_narrative_scheduler

        progress = get_zettel_narrative_scheduler().get_progress()
        remaining = max(progress.total - progress.processed, 0)
        eta_seconds = None
        if progress.processed > 0 and remaining > 0 and progress.started_at:
            elapsed = _elapsed_seconds(progress.started_at)
            if elapsed is not None and elapsed > 0:
                eta_seconds = elapsed / progress.processed * remaining
        return NarrativeProgressResponse(
            active=progress.active,
            total=progress.total,
            processed=progress.processed,
            finalized=progress.finalized,
            still_open=progress.still_open,
            failed=progress.failed,
            remaining=remaining,
            eta_seconds=eta_seconds,
            last_error=progress.last_error,
            canceling=progress.cancel_requested,
            analysis_concurrency=progress.analysis_concurrency,
            processing_strategy=progress.processing_strategy,
        )
    except Exception as exc:
        api_logger.error(f"Error getting narrative progress: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _elapsed_seconds(started_at: str) -> Optional[float]:
    from datetime import datetime, timezone

    try:
        start = datetime.fromisoformat(started_at)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - start).total_seconds()
    except (ValueError, TypeError):
        return None


def _validate_range(value: int, low: int, high: int, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer.")
    if not (low <= value <= high):
        raise ValueError(f"{label} must be between {low} and {high}.")


def _validate_hhmm(value: str) -> None:
    parts = str(value).split(":")
    if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
        raise ValueError("Scheduled time must be in HH:MM format.")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Scheduled time must be a valid 24-hour HH:MM.")


def _validate_sources(value: object) -> None:
    from api.core.models.preference_models.execution_and_connections import ZETTEL_SOURCE_KINDS

    if not isinstance(value, list) or any(item not in ZETTEL_SOURCE_KINDS for item in value):
        raise ValueError(
            f"enabled_sources must be a subset of {ZETTEL_SOURCE_KINDS}."
        )


async def _apply_to_running_schedulers(zettel) -> None:
    """Make enable toggles take effect now instead of at the next restart.

    Every start/stop is idempotent, so re-saving unchanged settings is a no-op;
    changed intervals and times are picked up when each loop schedules its next
    run.
    """
    try:
        from api.services.zettel.scheduler import get_zettel_scheduler

        carding = get_zettel_scheduler()
        if bool(getattr(zettel, "carding_enabled", True)):
            await carding.start()
        else:
            await carding.stop()
    except Exception:
        api_logger.warning("Could not apply zettel carding settings to the scheduler", exc_info=True)

    try:
        from api.services.zettel.narrative_scheduler import get_zettel_narrative_scheduler

        narrative = get_zettel_narrative_scheduler()
        if bool(getattr(zettel, "narrative_enabled", True)):
            await narrative.start()
        else:
            await narrative.stop()
    except Exception:
        api_logger.warning("Could not apply zettel narrative settings to the scheduler", exc_info=True)
