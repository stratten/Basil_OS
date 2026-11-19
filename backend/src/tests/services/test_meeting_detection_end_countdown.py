"""Tests for the meeting-detection runtime's end countdown.

When a meeting app's audio goes quiet and auto-end is on, the client is told once, at the first quiet probe, exactly when the recording will end, so it can show a countdown. If the audio returns first, the client is told the countdown is off. The end fires on the probe that completes the configured inactivity period, and the period starts counting at the probe that announced it, so the countdown is the whole period and never zero: a threshold of a single probe, or none, still leaves one probe interval of countdown.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from api.core.models.preferences import Preferences
from api.services.meeting_detection.runtime import MeetingDetectionRuntime

BUNDLE = "us.zoom.xos"
ZOOM = {"bundle_id": BUNDLE, "name": "zoom.us", "pid": 4242}


@pytest.fixture
def runtime(monkeypatch) -> MeetingDetectionRuntime:
    monkeypatch.setattr("api.services.meeting_detection.runtime.load_preferences", lambda: Preferences())
    instance = MeetingDetectionRuntime()
    instance.settings.auto_end = True
    instance.settings.poll_seconds = 5.0
    instance.settings.inactivity_timeout_minutes = 0.5
    instance._active_bundle_ids.add(BUNDLE)
    monkeypatch.setattr(instance, "_expire_stale_calendar_prompts", AsyncMock())
    monkeypatch.setattr(instance, "_probe_calendar_events", AsyncMock(return_value=[]))
    monkeypatch.setattr(instance, "_surface_joinable_calendar_events", AsyncMock())
    return instance


@pytest.fixture
def broadcast(monkeypatch) -> AsyncMock:
    mock = AsyncMock(return_value=0)
    monkeypatch.setattr("api.services.meeting_detection.runtime.broadcast_json_text", mock)
    return mock


def _probe(monkeypatch, active_apps: List[Dict[str, Any]]) -> None:
    async def fake_probe(_excluded):
        return {"success": True, "active_meeting_apps": active_apps, "current_calendar_event": None}

    monkeypatch.setattr("api.services.meeting_detection.runtime.request_swift_audio_probe", fake_probe)


def _events(broadcast: AsyncMock) -> List[str]:
    return [call.args[0]["event_type"] for call in broadcast.call_args_list]


@pytest.mark.asyncio
async def test_the_first_quiet_probe_announces_when_the_recording_will_end(runtime, broadcast, monkeypatch):
    _probe(monkeypatch, [])
    monkeypatch.setattr("api.services.meeting_detection.runtime.time.time", lambda: 1_000.0)

    await runtime.run_once()

    broadcast.assert_awaited_once()
    payload = broadcast.call_args.args[0]
    # The 30 second period starts at this first quiet probe, so the end is 30 seconds (6 probes at a 5 second poll) after it.
    assert payload == {"event_type": "meeting_ending", "bundle_id": BUNDLE, "seconds_until_end": 30.0, "ends_at": 1_030.0}


@pytest.mark.asyncio
async def test_later_quiet_probes_do_not_announce_again_and_the_last_one_ends_the_meeting(runtime, broadcast, monkeypatch):
    _probe(monkeypatch, [])

    for _ in range(7):
        await runtime.run_once()

    assert _events(broadcast) == ["meeting_ending", "meeting_ended"]
    assert BUNDLE not in runtime._active_bundle_ids
    assert BUNDLE not in runtime._announced_endings


@pytest.mark.asyncio
async def test_audio_returning_calls_the_countdown_off_once_and_the_meeting_keeps_going(runtime, broadcast, monkeypatch):
    _probe(monkeypatch, [])
    await runtime.run_once()
    await runtime.run_once()
    _probe(monkeypatch, [ZOOM])

    await runtime.run_once()
    await runtime.run_once()

    assert _events(broadcast) == ["meeting_ending", "meeting_end_canceled"]
    assert BUNDLE in runtime._active_bundle_ids
    assert runtime._missing_counts == {}


@pytest.mark.asyncio
async def test_a_second_quiet_spell_announces_a_fresh_countdown(runtime, broadcast, monkeypatch):
    _probe(monkeypatch, [])
    await runtime.run_once()
    _probe(monkeypatch, [ZOOM])
    await runtime.run_once()
    _probe(monkeypatch, [])

    await runtime.run_once()

    assert _events(broadcast) == ["meeting_ending", "meeting_end_canceled", "meeting_ending"]


@pytest.mark.asyncio
async def test_nothing_is_announced_when_auto_end_is_off(runtime, broadcast, monkeypatch):
    runtime.settings.auto_end = False
    _probe(monkeypatch, [])

    for _ in range(7):
        await runtime.run_once()

    broadcast.assert_not_awaited()
    assert BUNDLE not in runtime._active_bundle_ids


@pytest.mark.asyncio
async def test_a_threshold_shorter_than_one_probe_still_gets_one_probe_of_countdown(runtime, broadcast, monkeypatch):
    runtime.settings.inactivity_timeout_minutes = 0.0
    _probe(monkeypatch, [])
    monkeypatch.setattr("api.services.meeting_detection.runtime.time.time", lambda: 1_000.0)

    await runtime.run_once()

    assert _events(broadcast) == ["meeting_ending"]
    assert broadcast.call_args.args[0]["seconds_until_end"] == 5.0
    assert BUNDLE in runtime._active_bundle_ids

    await runtime.run_once()

    assert _events(broadcast) == ["meeting_ending", "meeting_ended"]
    assert BUNDLE not in runtime._active_bundle_ids


@pytest.mark.asyncio
async def test_a_threshold_equal_to_the_probe_interval_is_never_silent(runtime, broadcast, monkeypatch):
    # The saved settings that ended a calendar meeting with no warning: a 30 second poll and a half minute of quiet.
    runtime.settings.poll_seconds = 30.0
    runtime.settings.inactivity_timeout_minutes = 0.5
    _probe(monkeypatch, [])
    monkeypatch.setattr("api.services.meeting_detection.runtime.time.time", lambda: 1_000.0)

    await runtime.run_once()

    assert broadcast.call_args.args[0] == {"event_type": "meeting_ending", "bundle_id": BUNDLE, "seconds_until_end": 30.0, "ends_at": 1_030.0}
    await runtime.run_once()
    assert _events(broadcast) == ["meeting_ending", "meeting_ended"]


@pytest.mark.asyncio
async def test_with_auto_end_off_a_one_probe_threshold_still_forgets_the_app_at_once(runtime, broadcast, monkeypatch):
    runtime.settings.auto_end = False
    runtime.settings.inactivity_timeout_minutes = 0.0
    _probe(monkeypatch, [])

    await runtime.run_once()

    broadcast.assert_not_awaited()
    assert BUNDLE not in runtime._active_bundle_ids


@pytest.mark.asyncio
async def test_the_countdown_is_the_full_configured_period_counted_from_the_first_quiet_probe(runtime, broadcast, monkeypatch):
    runtime.settings.poll_seconds = 30.0
    runtime.settings.inactivity_timeout_minutes = 2.0
    _probe(monkeypatch, [])
    monkeypatch.setattr("api.services.meeting_detection.runtime.time.time", lambda: 1_000.0)

    await runtime.run_once()

    assert broadcast.call_args.args[0]["seconds_until_end"] == 120.0
    for _ in range(3):
        await runtime.run_once()
    assert _events(broadcast) == ["meeting_ending"]
    await runtime.run_once()
    assert _events(broadcast) == ["meeting_ending", "meeting_ended"]


@pytest.mark.asyncio
async def test_a_period_that_is_not_a_whole_number_of_probes_ends_on_the_next_probe_after_it_and_says_so(runtime, broadcast, monkeypatch):
    runtime.settings.poll_seconds = 30.0
    runtime.settings.inactivity_timeout_minutes = 0.75
    _probe(monkeypatch, [])
    monkeypatch.setattr("api.services.meeting_detection.runtime.time.time", lambda: 1_000.0)

    await runtime.run_once()

    # 45 seconds is a probe and a half, so the end falls on the second probe after the first: 60 seconds, and that is what the client is told.
    assert broadcast.call_args.args[0]["seconds_until_end"] == 60.0
    await runtime.run_once()
    assert _events(broadcast) == ["meeting_ending"]
    await runtime.run_once()
    assert _events(broadcast) == ["meeting_ending", "meeting_ended"]


@pytest.mark.asyncio
async def test_stopping_the_runtime_forgets_announced_countdowns(runtime, broadcast, monkeypatch):
    _probe(monkeypatch, [])
    await runtime.run_once()
    assert runtime._announced_endings == {BUNDLE}
    runtime.task = asyncio.create_task(asyncio.sleep(3600))

    await runtime.stop()

    assert runtime._announced_endings == set()
