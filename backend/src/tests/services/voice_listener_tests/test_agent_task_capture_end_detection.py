import time
from types import MethodType

import pytest

from api.routes.websocket_routes.agent_task_streaming import AgentTaskStreamProcessor


def make_processor(
    *,
    speech_detected: bool,
    seconds_since_last_word: float = 0.0,
    audio_silence_duration: float = 0.0,
    latest_average_rms: float = 0.0,
):
    processor = object.__new__(AgentTaskStreamProcessor)
    now = time.time()
    processor.websocket = None
    processor.silence_threshold = 2.0
    processor.minimum_speech_duration = 0.5
    processor.last_word_time = now - seconds_since_last_word if speech_detected else None
    processor.speech_detected = speech_detected
    processor.silence_start_time = None
    processor.capture_start_time = now - 10.0
    processor.capture_timeout = 120.0
    processor.audio_silence_threshold = 0.02
    processor.audio_silence_duration = audio_silence_duration
    processor.last_audio_time = now - 0.1
    processor.audio_silence_start_time = None
    processor.recent_audio_levels = [latest_average_rms]
    processor.latest_average_rms = latest_average_rms
    processor.active_audio_grace_after_word_silence = 5.0
    processor.recent_committed_words = []
    processor.complete_audio_buffer = []
    processor.capture_completed = False
    processor.completion_reason = None
    processor.progress_events = []

    def process_streaming_iteration(_self):
        return [], 0.0

    async def emit_silence_progress_event(_self, silence_duration):
        _self.progress_events.append(silence_duration)

    async def end_capture(_self, reason):
        _self.capture_completed = True
        _self.completion_reason = reason

    processor._process_streaming_iteration = MethodType(process_streaming_iteration, processor)
    processor._emit_silence_progress_event = MethodType(emit_silence_progress_event, processor)
    processor._end_capture = MethodType(end_capture, processor)
    return processor


@pytest.mark.asyncio
async def test_word_silence_does_not_end_while_audio_is_active():
    processor = make_processor(
        speech_detected=True,
        seconds_since_last_word=3.0,
        audio_silence_duration=0.0,
        latest_average_rms=0.10,
    )

    await processor.process_iter_with_termination_detection()

    assert processor.capture_completed is False
    assert processor.completion_reason is None
    assert processor.progress_events


@pytest.mark.asyncio
async def test_word_silence_ends_when_audio_is_also_silent():
    processor = make_processor(
        speech_detected=True,
        seconds_since_last_word=3.0,
        audio_silence_duration=2.2,
        latest_average_rms=0.01,
    )

    await processor.process_iter_with_termination_detection()

    assert processor.capture_completed is True
    assert processor.completion_reason == "word_silence_detected"


@pytest.mark.asyncio
async def test_active_audio_grace_eventually_ends_capture():
    processor = make_processor(
        speech_detected=True,
        seconds_since_last_word=8.0,
        audio_silence_duration=0.0,
        latest_average_rms=0.10,
    )

    await processor.process_iter_with_termination_detection()

    assert processor.capture_completed is True
    assert processor.completion_reason == "word_silence_with_active_audio_grace_elapsed"


@pytest.mark.asyncio
async def test_audio_fallback_before_speech_still_works():
    processor = make_processor(
        speech_detected=False,
        audio_silence_duration=2.2,
        latest_average_rms=0.01,
    )

    await processor.process_iter_with_termination_detection()

    assert processor.capture_completed is True
    assert processor.completion_reason == "audio_silence_detected"
