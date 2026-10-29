import asyncio
import time
from types import MethodType
from typing import List

import numpy as np
import pytest

from api.routes.websocket_routes import agent_task_streaming
from api.routes.websocket_routes.agent_task_streaming import AgentTaskStreamProcessor
from api.services.wake_word.capture_endpointing import WAKE_WORD_SILENCE_SECONDS as SILENCE_LIMIT
from api.services.whisper_live_core.timed_objects import ASRToken

SAMPLE_RATE = 16000


class LoudnessProbability:
    def __call__(self, frame):
        return 1.0 if float(np.max(np.abs(frame))) > 0.1 else 0.0

    def reset(self):
        pass


class RecordingWebSocket:
    def __init__(self):
        self.messages: List[dict] = []

    async def send_json(self, message):
        self.messages.append(message)

    def events(self, event_type):
        return [message["data"] for message in self.messages if message["event_type"] == event_type]


def speech(seconds):
    return np.full(int(seconds * SAMPLE_RATE), 0.5, dtype=np.float32)


def silence(seconds):
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


def make_processor(asr_step=None):
    processor = object.__new__(AgentTaskStreamProcessor)
    websocket = RecordingWebSocket()
    processor._init_capture_state(websocket, SILENCE_LIMIT, LoudnessProbability())
    processor.broadcasts = []
    processor._asr_step = MethodType(asr_step or (lambda _self, _chunks: []), processor)
    return processor, websocket


@pytest.fixture(autouse=True)
def capture_broadcasts(monkeypatch):
    sent = []

    async def broadcast(message):
        sent.append(message)

    monkeypatch.setattr(agent_task_streaming, "_broadcast_agent_task_capture_complete", broadcast)
    return sent


async def feed(processor, audio, step_seconds=0.1):
    step = int(step_seconds * SAMPLE_RATE)
    try:
        for start in range(0, audio.size, step):
            processor.insert_audio_chunk(audio[start:start + step])
            await processor.process_iter_with_termination_detection()
            if processor.capture_completed:
                return
            await asyncio.sleep(0.005)
    finally:
        # Let a transcription step that is still running finish, so no task outlives the test.
        if processor._asr_task is not None:
            await asyncio.gather(processor._asr_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_capture_ends_two_and_a_half_seconds_after_the_person_stops_speaking(capture_broadcasts):
    processor, _ = make_processor()

    await feed(processor, np.concatenate([speech(1.5), silence(3.0)]))

    assert processor.completion_reason == "speech_end_detected"
    assert capture_broadcasts[0]["data"]["reason"] == "speech_end_detected"
    assert processor.endpoint.trailing_silence_seconds == pytest.approx(SILENCE_LIMIT, abs=0.12)


@pytest.mark.asyncio
async def test_a_slow_transcriber_does_not_change_when_the_capture_ends():
    def slow_asr_step(_self, _chunks):
        time.sleep(0.4)
        return []

    processor, _ = make_processor(slow_asr_step)

    await feed(processor, np.concatenate([speech(1.0), silence(3.0)]))

    assert processor.completion_reason == "speech_end_detected"
    assert processor.endpoint.trailing_silence_seconds == pytest.approx(SILENCE_LIMIT, abs=0.12)


@pytest.mark.asyncio
async def test_the_event_loop_keeps_running_while_the_transcriber_works():
    def slow_asr_step(_self, _chunks):
        time.sleep(0.6)
        return []

    processor, _ = make_processor(slow_asr_step)
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    processor.insert_audio_chunk(speech(0.5))
    await processor.process_iter_with_termination_detection()
    await asyncio.sleep(0.5)
    beat.cancel()
    await processor._asr_task
    processor.shutdown()

    assert ticks >= 15


@pytest.mark.asyncio
async def test_a_pause_inside_a_request_does_not_end_the_capture():
    processor, _ = make_processor()

    await feed(processor, np.concatenate([speech(1.0), silence(2.2), speech(1.0), silence(1.0)]))

    assert processor.capture_completed is False


@pytest.mark.asyncio
async def test_the_countdown_appears_after_a_short_grace_and_counts_down_in_audio_time():
    processor, websocket = make_processor()

    await feed(processor, np.concatenate([speech(1.0), silence(1.9)]))

    progress = websocket.events("agent_task_silence_progress")
    assert progress, "the countdown should be reported"
    assert all(event["counting"] is True for event in progress)
    assert min(event["silence_duration"] for event in progress) >= 0.5
    remaining = [event["remaining_time"] for event in progress]
    assert remaining == sorted(remaining, reverse=True)
    assert remaining[0] <= SILENCE_LIMIT - 0.5 + 0.05


@pytest.mark.asyncio
async def test_the_countdown_is_reported_often_enough_to_animate():
    processor, websocket = make_processor()

    await feed(processor, np.concatenate([speech(1.0), silence(1.9)]))

    progress = websocket.events("agent_task_silence_progress")
    assert len(progress) >= 10


@pytest.mark.asyncio
async def test_resumed_speech_cancels_the_countdown_immediately():
    processor, websocket = make_processor()

    await feed(processor, np.concatenate([speech(1.0), silence(1.2), speech(0.3)]))

    progress = websocket.events("agent_task_silence_progress")
    assert progress[-1]["counting"] is False
    assert all(event["counting"] is True for event in progress[:-1])


@pytest.mark.asyncio
async def test_a_pause_shorter_than_the_grace_shows_no_countdown():
    processor, websocket = make_processor()

    await feed(processor, np.concatenate([speech(1.0), silence(0.3), speech(1.0)]))

    assert websocket.events("agent_task_silence_progress") == []


@pytest.mark.asyncio
async def test_a_capture_with_no_speech_ends_instead_of_running_to_the_limit():
    processor, _ = make_processor()

    await feed(processor, silence(10.0))

    assert processor.completion_reason == "no_speech_detected"
    assert processor.speech_detected is False


@pytest.mark.asyncio
async def test_committed_words_are_forwarded_for_display_without_affecting_the_end():
    def asr_step(_self, _chunks):
        return [ASRToken(start=0.0, end=0.4, text="hello")]

    processor, websocket = make_processor(asr_step)

    await feed(processor, np.concatenate([speech(1.0), silence(3.0)]))
    await asyncio.sleep(0.05)

    assert any(event["words"] == ["hello"] for event in websocket.events("agent_task_word_detected"))
    assert processor.completion_reason == "speech_end_detected"


@pytest.mark.asyncio
async def test_the_complete_audio_is_kept_for_the_final_transcription():
    processor, _ = make_processor()
    audio = np.concatenate([speech(1.0), silence(3.0)])

    await feed(processor, audio)

    kept = processor.get_complete_audio()
    assert kept is not None
    assert kept.size >= int(2.9 * SAMPLE_RATE)
    assert kept[0] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_nothing_runs_after_the_capture_has_ended():
    processor, websocket = make_processor()
    await feed(processor, np.concatenate([speech(1.0), silence(3.0)]))
    sent_before = len(websocket.messages)

    await processor.process_iter_with_termination_detection()

    assert len(websocket.messages) == sent_before
    assert processor.completion_reason == "speech_end_detected"
