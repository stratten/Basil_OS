import time
from types import SimpleNamespace

import pytest

from api.routes.voice_listener_routes.wake_word_routes import trigger_wake_word_callback
from api.services.wake_word.wake_word_manager import VoiceListenerWakeWordManager


def _accepting_manager(schedule_result: bool = True) -> VoiceListenerWakeWordManager:
    manager = VoiceListenerWakeWordManager()
    manager._check_frontend_can_accept_agent_task = lambda: True
    manager._pause_wake_word_detection = lambda: None
    manager._is_api_transcription_selected = lambda: True
    manager._schedule_agent_task_processing = lambda phrase: schedule_result
    return manager


def test_accepts_when_nothing_blocks_the_wake_word():
    manager = _accepting_manager()

    assert manager._handle_wake_word_detected("hotkey_initiated") is True
    assert manager._is_capturing_agent_task is True


def test_declines_when_a_capture_is_already_in_progress():
    manager = _accepting_manager()
    manager._is_capturing_agent_task = True

    assert manager._handle_wake_word_detected("hotkey_initiated") is False


def test_declines_when_the_agent_task_was_canceled():
    manager = _accepting_manager()
    manager._agent_task_canceled = True

    assert manager._handle_wake_word_detected("hotkey_initiated") is False
    assert manager._is_capturing_agent_task is False


def test_declines_when_the_frontend_cannot_accept():
    manager = _accepting_manager()
    manager._check_frontend_can_accept_agent_task = lambda: False

    assert manager._handle_wake_word_detected("hotkey_initiated") is False
    assert manager._is_capturing_agent_task is False


def test_declines_while_a_backend_capture_lifecycle_is_busy():
    manager = _accepting_manager()
    manager.orchestration_service = SimpleNamespace(lifecycle_snapshot=lambda: {"wake_capture:abc": object()})

    assert manager._handle_wake_word_detected("hotkey_initiated") is False
    assert manager._is_capturing_agent_task is False


def test_declines_a_same_utterance_detection_inside_one_second():
    manager = _accepting_manager()
    manager._last_wake_word_time = time.time()

    assert manager._handle_wake_word_detected("hotkey_initiated") is False


def test_declines_inside_the_regular_debounce_window():
    manager = _accepting_manager()
    manager._last_wake_word_time = time.time() - 2.0

    assert manager._handle_wake_word_detected("hotkey_initiated") is False


def test_declines_and_resets_the_flag_when_scheduling_fails():
    manager = _accepting_manager(schedule_result=False)

    assert manager._handle_wake_word_detected("hotkey_initiated") is False
    assert manager._is_capturing_agent_task is False


class _FakeRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _service(handler):
    return SimpleNamespace(
        wake_word_manager=SimpleNamespace(_handle_wake_word_detected=handler),
        agent_task_orchestration_service=None,
        _is_capturing_agent_task=False,
    )


@pytest.mark.asyncio
async def test_route_reports_accepted_true_for_an_accepted_hotkey_press():
    response = await trigger_wake_word_callback(
        _FakeRequest({"wake_phrase": "hotkey_initiated", "hotkey_mode": True}),
        _service(lambda phrase: True),
    )

    assert response["success"] is True
    assert response["accepted"] is True


@pytest.mark.asyncio
async def test_route_reports_accepted_false_for_a_declined_hotkey_press():
    response = await trigger_wake_word_callback(
        _FakeRequest({"wake_phrase": "hotkey_initiated", "hotkey_mode": True}),
        _service(lambda phrase: False),
    )

    assert response["success"] is True
    assert response["accepted"] is False


@pytest.mark.asyncio
async def test_route_reports_accepted_false_outside_hotkey_mode():
    response = await trigger_wake_word_callback(
        _FakeRequest({"wake_phrase": "hey_basil"}),
        _service(lambda phrase: False),
    )

    assert response["accepted"] is False


@pytest.mark.asyncio
async def test_route_treats_a_handler_without_a_result_as_accepted():
    response = await trigger_wake_word_callback(
        _FakeRequest({"wake_phrase": "hotkey_initiated", "hotkey_mode": True}),
        _service(lambda phrase: None),
    )

    assert response["accepted"] is True
