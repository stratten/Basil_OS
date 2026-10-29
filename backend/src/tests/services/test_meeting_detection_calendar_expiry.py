"""
Tests for the meeting-detection runtime's calendar-event-expiry poller.

Covers the backend-driven auto-dismiss of calendar-sourced join prompts whose
event has ended with no user action taken. This replaces a client-side Timer
approach: the poller now owns the expiry decision entirely, adding the event
to the existing ignored-set (so it can't resurface after cooldown) and
broadcasting `meeting_prompt_expired` so any open client panel hides itself.

Audio-sourced prompts are explicitly out of scope for this mechanism (they
have no stable server-side identifier and already have a better-suited
end-of-life signal in the existing auto_end/_surface_ended falling-edge path)
and are not exercised here.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest

from api.core.models.preferences import Preferences
from api.services.meeting_detection.runtime import MeetingDetectionRuntime


@pytest.fixture
def runtime(monkeypatch) -> MeetingDetectionRuntime:
    """A fresh runtime backed by default preferences, isolated from disk."""
    monkeypatch.setattr(
        "api.services.meeting_detection.runtime.load_preferences",
        lambda: Preferences(),
    )
    return MeetingDetectionRuntime()


def _patch_broadcast(monkeypatch) -> AsyncMock:
    mock = AsyncMock(return_value=0)
    monkeypatch.setattr("api.services.meeting_detection.runtime.broadcast_json_text", mock)
    return mock


@pytest.mark.asyncio
async def test_expire_stale_calendar_prompts_broadcasts_and_ignores(runtime, monkeypatch):
    """An event whose end time has passed is ignored and broadcast exactly once."""
    broadcast = _patch_broadcast(monkeypatch)
    past_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()
    runtime._surfaced_calendar_event_end_times["evt-past"] = past_ts

    await runtime._expire_stale_calendar_prompts()

    assert "evt-past" in runtime._ignored_calendar_event_ids
    assert "evt-past" not in runtime._surfaced_calendar_event_end_times
    broadcast.assert_awaited_once()
    (payload,), _ = broadcast.call_args
    assert payload == {"event_type": "meeting_prompt_expired", "calendar_event_id": "evt-past"}


@pytest.mark.asyncio
async def test_expire_stale_calendar_prompts_is_idempotent(runtime, monkeypatch):
    """Re-running after an event already expired must not re-broadcast."""
    broadcast = _patch_broadcast(monkeypatch)
    past_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()
    runtime._surfaced_calendar_event_end_times["evt-past"] = past_ts

    await runtime._expire_stale_calendar_prompts()
    broadcast.reset_mock()
    await runtime._expire_stale_calendar_prompts()

    broadcast.assert_not_awaited()


@pytest.mark.asyncio
async def test_expire_stale_calendar_prompts_leaves_future_event_untouched(runtime, monkeypatch):
    """An event whose end time has not yet passed must not be touched (negative case)."""
    broadcast = _patch_broadcast(monkeypatch)
    future_ts = (datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()
    runtime._surfaced_calendar_event_end_times["evt-future"] = future_ts

    await runtime._expire_stale_calendar_prompts()

    assert "evt-future" not in runtime._ignored_calendar_event_ids
    assert runtime._surfaced_calendar_event_end_times["evt-future"] == future_ts
    broadcast.assert_not_awaited()


@pytest.mark.asyncio
async def test_expire_stale_calendar_prompts_skips_already_ignored_event(runtime, monkeypatch):
    """An event dismissed manually before its natural expiry must not re-broadcast."""
    broadcast = _patch_broadcast(monkeypatch)
    past_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()
    runtime._surfaced_calendar_event_end_times["evt-dismissed"] = past_ts
    runtime.ignore_calendar_event("evt-dismissed")

    await runtime._expire_stale_calendar_prompts()

    assert "evt-dismissed" not in runtime._surfaced_calendar_event_end_times
    broadcast.assert_not_awaited()


@pytest.mark.asyncio
async def test_surface_joinable_calendar_events_records_end_time(runtime, monkeypatch):
    """Surfacing a joinable calendar event must capture its end_timestamp for
    later expiry tracking."""
    broadcast = _patch_broadcast(monkeypatch)
    end_ts = (datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp()
    event: Dict[str, Any] = {
        "event_identifier": "evt-1",
        "title": "Weekly Sync",
        "calendar_name": "Work",
        "has_call_info": True,
        "join_url": "https://example.com/join",
        "end_timestamp": end_ts,
    }

    await runtime._surface_joinable_calendar_events([event])

    assert runtime._surfaced_calendar_event_end_times["evt-1"] == end_ts
    assert broadcast.await_args.args[0]["meeting"]["calendar_name"] == "Work"


@pytest.mark.asyncio
async def test_surface_joinable_calendar_events_handles_missing_end_timestamp(runtime, monkeypatch):
    """No end_timestamp on the event must not raise or record a stale entry."""
    _patch_broadcast(monkeypatch)
    event: Dict[str, Any] = {
        "event_identifier": "evt-no-end",
        "title": "No End Time",
        "has_call_info": True,
        "join_url": "https://example.com/join",
    }

    await runtime._surface_joinable_calendar_events([event])

    assert "evt-no-end" not in runtime._surfaced_calendar_event_end_times


@pytest.mark.asyncio
async def test_stop_clears_end_time_tracking(runtime):
    """stop() resets end-time tracking alongside the other edge-detection state
    so a restart re-tracks a still-relevant event cleanly."""
    runtime._surfaced_calendar_event_end_times["evt-1"] = 123.0
    runtime.task = asyncio.create_task(asyncio.sleep(3600))

    await runtime.stop()

    assert runtime._surfaced_calendar_event_end_times == {}
