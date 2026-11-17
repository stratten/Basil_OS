"""A stopped and restarted voice listener must not carry audio, or the wake word model's memory of audio, across the gap."""

from typing import Any, List
from unittest.mock import MagicMock

import numpy as np
import pytest

from api.services.wake_word.wake_word_detector import WakeWordDetector
from api.services.wake_word.wake_word_service import WakeWordService


class FakeModel:
    def __init__(self, events: List[Any]):
        self.events = events

    def reset(self):
        self.events.append("model_reset")

    def predict(self, frame):
        self.events.append(("model_predict", int(np.count_nonzero(frame))))
        return {"hey_basil": 0.0}


class FakeCapturer:
    def __init__(self, events: List[Any], capturing: bool = True):
        self.events = events
        self._is_capturing = capturing

    def start(self):
        self._is_capturing = True
        self.events.append("capturer_start")

    def stop(self):
        self._is_capturing = False
        self.events.append("capturer_stop")

    def clear_all_buffers(self):
        self.events.append(("clear_buffers", self._is_capturing))


class FakeDetector:
    def __init__(self, events: List[Any]):
        self.events = events
        self.oww_model = object()

    def reset_detection_state(self):
        self.events.append("detector_reset")


def make_detector(events: List[Any], paused: bool = False) -> WakeWordDetector:
    detector = object.__new__(WakeWordDetector)
    detector.oww_model = FakeModel(events)
    detector.active_models = {"hey_basil": 0.9, "other": 0.4}
    detector.on_wake_word_detected_callback = MagicMock()
    detector._is_paused = paused
    return detector


def make_service(events: List[Any], capturing: bool = False) -> WakeWordService:
    service = object.__new__(WakeWordService)
    service.audio_capturer = FakeCapturer(events, capturing=capturing)
    service.wake_word_detector = FakeDetector(events)
    service._is_globally_enabled_by_user = True
    service._is_actively_listening = False
    service._is_capturing_agent_task = False
    service._health_monitor_task = None
    service.agent_task_orchestration_service = None
    service.wake_word_manager = None
    service.transcription_service = None
    return service


class ImmediateThread:
    """Runs the thread target when started, so the background cleanup finishes before the test continues."""

    def __init__(self, target=None, **_kwargs):
        self.target = target

    def start(self):
        self.target()


class TestDetectorReset:
    def test_resets_the_model_clears_scores_and_flushes_with_silence(self):
        events: List[Any] = []
        detector = make_detector(events)

        detector.reset_detection_state()

        assert events[0] == "model_reset"
        assert events[1:] == [("model_predict", 0)] * 3
        assert detector.active_models == {"hey_basil": 0.0, "other": 0.0}

    def test_never_fires_the_wake_word_callback(self):
        detector = make_detector([])

        detector.reset_detection_state()

        detector.on_wake_word_detected_callback.assert_not_called()

    @pytest.mark.parametrize("paused", [True, False])
    def test_leaves_the_paused_state_alone(self, paused):
        detector = make_detector([], paused=paused)

        detector.reset_detection_state()

        assert detector._is_paused is paused

    def test_does_nothing_without_a_loaded_model(self):
        detector = make_detector([])
        detector.oww_model = None

        detector.reset_detection_state()

        assert detector.active_models == {"hey_basil": 0.9, "other": 0.4}

    def test_a_failing_model_reset_is_contained(self):
        detector = make_detector([])
        detector.oww_model = MagicMock()
        detector.oww_model.reset.side_effect = RuntimeError("model gone")

        detector.reset_detection_state()


class TestDiscardStaleListeningState:
    def test_clears_buffers_and_resets_the_detector_when_the_capturer_is_idle(self):
        events: List[Any] = []
        service = make_service(events, capturing=False)

        service._discard_stale_listening_state()

        assert events == [("clear_buffers", False), "detector_reset"]

    def test_does_nothing_while_the_capturer_is_running(self):
        events: List[Any] = []
        service = make_service(events, capturing=True)

        service._discard_stale_listening_state()

        assert events == []

    def test_a_failing_clear_does_not_raise(self):
        events: List[Any] = []
        service = make_service(events, capturing=False)
        service.audio_capturer.clear_all_buffers = MagicMock(side_effect=RuntimeError("busy"))

        service._discard_stale_listening_state()

        assert events == []


class TestStopListening:
    def test_clears_after_the_capturer_has_stopped_and_not_before(self, monkeypatch):
        events: List[Any] = []
        service = make_service(events, capturing=True)
        service._is_actively_listening = True
        monkeypatch.setattr("threading.Thread", ImmediateThread)

        service.stop_listening()

        assert events == ["capturer_stop", ("clear_buffers", False), "detector_reset"]
        assert service._is_actively_listening is False

    def test_does_not_reset_a_session_that_was_started_again_during_cleanup(self, monkeypatch):
        events: List[Any] = []
        service = make_service(events, capturing=True)
        service._is_actively_listening = True
        original_stop = service.audio_capturer.stop

        def stop_then_restart():
            original_stop()
            service._is_actively_listening = True

        service.audio_capturer.stop = stop_then_restart
        monkeypatch.setattr("threading.Thread", ImmediateThread)

        service.stop_listening()

        assert events == ["capturer_stop"]


class TestStartListening:
    def test_discards_stale_state_before_the_capturer_starts(self, monkeypatch):
        events: List[Any] = []
        service = make_service(events, capturing=False)
        monkeypatch.setattr(
            WakeWordService,
            "_is_api_transcription_selected",
            staticmethod(lambda: True),
        )

        service.start_listening()

        assert events[:3] == [("clear_buffers", False), "detector_reset", "capturer_start"]
        assert service._is_actively_listening is True
