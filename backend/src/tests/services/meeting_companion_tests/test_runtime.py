import asyncio
import time
from types import SimpleNamespace

import pytest

from api.services.meeting_companion.models import CompanionSettings
from api.services.meeting_companion.runtime import (
    CompanionNotLive,
    cleanup_meeting_companion_runtime,
    get_meeting_companion_runtime,
    initialize_meeting_companion_runtime,
    member_start_epoch,
    role_for,
    session_key_for,
    speaker_for,
)
from api.services.meetings import meeting_recording_registry
from api.services.meeting_companion.store import CompanionDocument, CompanionStore

QUESTION = "How does the retry policy handle timeouts in billing?"
SYSTEM_START = "2026-01-01T10:00:12.000000Z"


def segment(text, start, end):
    return {"start": start, "end": end, "text": text, "speaker": "Microphone", "is_interim": False}


def test_identity_role_speaker_and_start_epoch_helpers():
    mic = SimpleNamespace(meeting_id="m1", session_id="s1", audio_source="Microphone", metadata=SimpleNamespace(start_time="2026-01-01T10:00:00.000000Z"))
    system = SimpleNamespace(meeting_id="m2", session_id="s1", audio_source="Zoom", metadata=SimpleNamespace(start_time="2026-01-01T10:00:12.500000Z"))
    standalone = SimpleNamespace(meeting_id="m3", session_id=None, audio_source=None, metadata=None)
    assert session_key_for("m1", mic) == session_key_for("m2", system) == "s1"
    assert session_key_for("m3", standalone) == "m3"
    assert role_for(mic) == "self" and role_for(system) == "other" and role_for(standalone) == "self"
    assert speaker_for(system) == "Zoom" and speaker_for(standalone) == "Speaker 1"
    assert member_start_epoch(system) - member_start_epoch(mic) == pytest.approx(12.5)
    assert abs(member_start_epoch(standalone) - time.time()) < 5
    broken = SimpleNamespace(metadata=SimpleNamespace(start_time="not a date"))
    assert abs(member_start_epoch(broken) - time.time()) < 5


@pytest.mark.asyncio
async def test_enable_requires_a_live_recorder(runtime_factory):
    env = runtime_factory()
    with pytest.raises(CompanionNotLive):
        await env.runtime.enable("ghost")
    assert env.runtime.session_for("ghost") is None and env.runtime.snapshot("ghost") is None
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_enable_attaches_both_siblings_and_uses_the_global_default_mode(runtime_factory, recorder_factory):
    env = runtime_factory(default_mode="passive")
    env.recorders.extend([recorder_factory("mic1", session_id="s1"), recorder_factory("sys1", session_id="s1", audio_source="Zoom", start_time=SYSTEM_START)])
    session = await env.runtime.enable("mic1")
    assert session.settings.enabled is True and session.settings.mode == "passive" and session.settings.model_id is None
    assert env.runtime.session_for("sys1") is session and session.meeting_ids() == ["mic1", "sys1"]
    assert env.runtime.snapshot("sys1").status.live is True
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_enable_twice_returns_the_same_session_and_applies_overrides(runtime_factory, recorder_factory):
    env = runtime_factory()
    env.recorders.append(recorder_factory("mic1"))
    first = await env.runtime.enable("mic1")
    second = await env.runtime.enable("mic1", mode="passive", model_id="model-x")
    assert first is second and second.settings.mode == "passive" and second.settings.model_id == "model-x"
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_existing_final_segments_seed_history_and_do_not_trigger(runtime_factory, recorder_factory):
    env = runtime_factory()
    env.recorders.append(recorder_factory("mic1", existing=[segment(QUESTION, 1.0, 4.0)]))
    session = await env.runtime.enable("mic1")
    assert session.pending_line_count() == 0
    await session.tick()
    await session.wait_idle()
    assert env.evaluator.requests == []
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_segments_from_the_audio_thread_reach_the_session(runtime_factory, recorder_factory):
    env = runtime_factory()
    mic = recorder_factory("mic1")
    env.recorders.append(mic)
    session = await env.runtime.enable("mic1")
    await asyncio.to_thread(env.runtime._on_registry_event, "segment", "mic1", mic, {"segment": segment(QUESTION, 1.0, 4.0)})
    await env.runtime.wait_idle()
    assert session.pending_line_count() == 1
    await session.tick()
    await session.wait_idle()
    assert [request.trigger for request in env.evaluator.requests] == ["question"]
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_segments_for_unknown_sessions_or_without_payload_are_ignored(runtime_factory, recorder_factory):
    env = runtime_factory()
    mic = recorder_factory("mic1")
    ghost = recorder_factory("ghost")
    env.recorders.append(mic)
    session = await env.runtime.enable("mic1")
    env.runtime._on_registry_event("segment", "ghost", ghost, {"segment": segment(QUESTION, 1.0, 4.0)})
    env.runtime._on_registry_event("segment", "mic1", mic, None)
    env.runtime._on_registry_event("segment", "mic1", mic, {})
    await env.runtime.wait_idle()
    assert session.pending_line_count() == 0
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_auto_enable_creates_a_session_on_start_and_a_late_sibling_joins_it(runtime_factory, recorder_factory):
    env = runtime_factory(auto_enable=True, default_mode="passive")
    mic = recorder_factory("mic1", session_id="s1")
    env.recorders.append(mic)
    env.runtime._on_registry_event("started", "mic1", mic, None)
    await env.runtime.wait_idle()
    session = env.runtime.session_for("mic1")
    assert session is not None and session.settings.mode == "passive"
    system = recorder_factory("sys1", session_id="s1", audio_source="Zoom", start_time=SYSTEM_START)
    env.recorders.append(system)
    env.runtime._on_registry_event("started", "sys1", system, None)
    await env.runtime.wait_idle()
    assert session.has_member("sys1") and env.runtime.session_for("sys1") is session
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_auto_enable_off_and_stale_recorders_are_ignored_and_toggling_applies_next_start(runtime_factory, recorder_factory):
    env = runtime_factory(auto_enable=False)
    mic = recorder_factory("mic1")
    env.recorders.append(mic)
    env.runtime._on_registry_event("started", "mic1", mic, None)
    await env.runtime.wait_idle()
    assert env.runtime.session_for("mic1") is None
    updated = env.runtime.update_global_settings(auto_enable=True)
    assert updated.auto_enable is True and env.runtime.get_global_settings().auto_enable is True
    stale = recorder_factory("stale1")
    env.runtime._on_registry_event("started", "stale1", stale, None)
    await env.runtime.wait_idle()
    assert env.runtime.session_for("stale1") is None
    live = recorder_factory("mic2")
    env.recorders.append(live)
    env.runtime._on_registry_event("started", "mic2", live, None)
    await env.runtime.wait_idle()
    assert env.runtime.session_for("mic2") is not None
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_stopping_the_last_member_closes_and_persists(runtime_factory, recorder_factory, tmp_path):
    env = runtime_factory()
    mic = recorder_factory("mic1")
    env.recorders.append(mic)
    session = await env.runtime.enable("mic1")
    env.runtime._on_registry_event("segment", "mic1", mic, {"segment": segment(QUESTION, 1.0, 4.0)})
    await env.runtime.wait_idle()
    await session.tick()
    await session.wait_idle()
    env.runtime._on_registry_event("stopped", "mic1", mic, None)
    await env.runtime.wait_idle()
    assert env.runtime.session_for("mic1") is None and session.status().live is False
    stored = CompanionStore(tmp_path / "mic1").load()
    assert stored is not None and any(event.kind == "item" for event in stored.events) and stored.events[-1].kind == "status"
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_session_with_two_members_closes_only_after_the_last_one_stops(runtime_factory, recorder_factory):
    env = runtime_factory()
    mic = recorder_factory("mic1", session_id="s1")
    system = recorder_factory("sys1", session_id="s1", audio_source="Zoom", start_time=SYSTEM_START)
    env.recorders.extend([mic, system])
    session = await env.runtime.enable("mic1")
    env.runtime._on_registry_event("stopped", "sys1", system, None)
    await env.runtime.wait_idle()
    assert env.runtime.session_for("mic1") is session and session.has_member("sys1") is False and session.status().live is True
    env.runtime._on_registry_event("stopped", "mic1", mic, None)
    await env.runtime.wait_idle()
    assert env.runtime.session_for("mic1") is None and session.status().live is False
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_discarding_the_last_member_writes_nothing(runtime_factory, recorder_factory, tmp_path):
    env = runtime_factory()
    mic = recorder_factory("mic1")
    env.recorders.append(mic)
    session = await env.runtime.enable("mic1")
    env.runtime._on_registry_event("discarded", "mic1", mic, None)
    await env.runtime.wait_idle()
    assert session.status().live is False and env.runtime.session_for("mic1") is None
    assert not (tmp_path / "mic1" / "companion.json").exists()
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_disable_closes_with_enabled_false_and_enable_can_start_again(runtime_factory, recorder_factory, tmp_path):
    env = runtime_factory()
    mic = recorder_factory("mic1")
    env.recorders.append(mic)
    session = await env.runtime.enable("mic1")
    assert await env.runtime.disable("mic1") is True
    assert await env.runtime.disable("mic1") is False
    stored = CompanionStore(tmp_path / "mic1").load()
    assert stored.settings.enabled is False and session.status().live is False
    again = await env.runtime.enable("mic1")
    assert again is not session and again.status().enabled is True and again.status().live is True
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_resumed_meeting_adopts_stored_settings_unless_the_request_is_explicit(runtime_factory, recorder_factory, tmp_path):
    directory = tmp_path / "mic1"
    directory.mkdir()
    stored = CompanionSettings(enabled=True, mode="passive", model_id="stored-model")
    CompanionStore(directory).save(CompanionDocument(session_key="mic1", settings=stored, events=[], saved_at="w"))
    env = runtime_factory(default_mode="active")
    env.recorders.append(recorder_factory("mic1"))
    inherited = await env.runtime.enable("mic1")
    assert inherited.settings.mode == "passive" and inherited.settings.model_id == "stored-model"
    await env.runtime.shutdown()
    env_explicit = runtime_factory(default_mode="active")
    env_explicit.recorders.append(recorder_factory("mic1"))
    explicit = await env_explicit.runtime.enable("mic1", mode="active")
    assert explicit.settings.mode == "active" and explicit.settings.model_id == "stored-model"
    await env_explicit.runtime.shutdown()


@pytest.mark.asyncio
async def test_capacity_guard_reads_the_recorder_lag(runtime_factory, recorder_factory):
    env = runtime_factory()
    mic = recorder_factory("mic1")
    mic.transcription_lag_seconds = 30.0
    env.recorders.append(mic)
    session = await env.runtime.enable("mic1")
    await session.tick()
    env.clock.advance(5.0)
    await session.tick()
    assert session.status().capacity == "paused" and session.status().transcription_lag_seconds == 30.0
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_shutdown_closes_every_session_and_late_events_are_harmless(runtime_factory, recorder_factory):
    env = runtime_factory()
    mic = recorder_factory("mic1")
    env.recorders.append(mic)
    session = await env.runtime.enable("mic1")
    await env.runtime.shutdown()
    assert session.status().live is False and env.runtime.session_for("mic1") is None
    env.runtime._on_registry_event("started", "mic1", mic, None)
    env.runtime._on_registry_event("segment", "mic1", mic, {"segment": segment(QUESTION, 1.0, 4.0)})
    await env.runtime.wait_idle()


@pytest.mark.asyncio
async def test_singleton_registers_and_removes_the_registry_listener():
    runtime = await initialize_meeting_companion_runtime()
    try:
        assert get_meeting_companion_runtime() is runtime
        assert runtime._on_registry_event in meeting_recording_registry._listeners
        assert await initialize_meeting_companion_runtime() is runtime
    finally:
        await cleanup_meeting_companion_runtime()
    assert get_meeting_companion_runtime() is None
    assert runtime._on_registry_event not in meeting_recording_registry._listeners
    await cleanup_meeting_companion_runtime()


@pytest.mark.asyncio
async def test_focus_typed_before_recording_applies_to_that_meeting_once_and_is_consumed(runtime_factory, recorder_factory):
    env = runtime_factory(auto_enable=True)
    env.runtime.update_global_settings(next_focus="  Watch the budget numbers ")
    mic = recorder_factory("mic1")
    env.recorders.append(mic)
    env.runtime._on_registry_event("started", "mic1", mic, None)
    await env.runtime.wait_idle()
    session = env.runtime.session_for("mic1")
    assert session is not None and session.settings.focus == "Watch the budget numbers"
    assert session.status().focus == "Watch the budget numbers"
    assert env.runtime.get_global_settings().next_focus == ""
    later = recorder_factory("mic2", session_id="other")
    env.recorders.append(later)
    env.runtime._on_registry_event("started", "mic2", later, None)
    await env.runtime.wait_idle()
    follow_up = env.runtime.session_for("mic2")
    assert follow_up is not None and follow_up.settings.focus == ""
    await env.runtime.shutdown()


@pytest.mark.asyncio
async def test_focus_can_be_set_on_enable_and_changed_mid_meeting_and_reaches_the_evaluator(runtime_factory, recorder_factory):
    env = runtime_factory()
    mic = recorder_factory("mic1")
    env.recorders.append(mic)
    session = await env.runtime.enable("mic1", focus="Pricing")
    assert session.settings.focus == "Pricing"
    again = await env.runtime.enable("mic1")
    assert again.settings.focus == "Pricing"
    session.update_settings(focus="  Hiring plan ")
    assert session.status().focus == "Hiring plan"
    session.update_settings(focus="")
    assert session.status().focus == ""
    session.update_settings(focus="Roadmap")
    await asyncio.to_thread(env.runtime._on_registry_event, "segment", "mic1", mic, {"segment": segment(QUESTION, 1.0, 4.0)})
    await env.runtime.wait_idle()
    await session.tick()
    await session.wait_idle()
    assert env.evaluator.requests and env.evaluator.requests[-1].focus == "Roadmap"
    await env.runtime.shutdown()
