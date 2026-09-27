"""Focused tests for native live-stream timing control parsing."""

import pytest

from api.services.live_transcription.whisper_live_service import (
    apply_native_stream_timing_control,
    is_legacy_termination_control,
)


class FakeAudioProcessor:
    def __init__(self) -> None:
        self.offsets: list[float] = []

    def set_native_stream_offset_seconds(self, offset_seconds: float) -> None:
        self.offsets.append(offset_seconds)


def test_valid_native_stream_timing_control_updates_processor_once() -> None:
    processor = FakeAudioProcessor()

    handled = apply_native_stream_timing_control(
        '{"type":"native_stream_timing","stream_offset_seconds":600.25}',
        processor,
    )

    assert handled is True
    assert processor.offsets == [600.25]


@pytest.mark.parametrize(
    "control_message",
    [
        "{",
        '{"type":"native_stream_timing","stream_offset_seconds":-0.1}',
        '{"type":"native_stream_timing","stream_offset_seconds":NaN}',
        '{"type":"native_stream_timing","stream_offset_seconds":86400.1}',
        '{"type":"native_stream_timing","stream_offset_seconds":true}',
        '{"type":"other","stream_offset_seconds":5}',
        '{"action":"close"}',
        '{"action":"terminate"}',
        '{"action":"kill_process"}',
        '{"action":"force_terminate"}',
    ],
)
def test_invalid_or_legacy_control_does_not_update_stream_offset(
    control_message: str,
) -> None:
    processor = FakeAudioProcessor()

    handled = apply_native_stream_timing_control(control_message, processor)

    assert handled is False
    assert processor.offsets == []


@pytest.mark.parametrize(
    "control_message",
    [
        '{"action":"close"}',
        '{"action":"terminate"}',
        '{"action":"kill_process"}',
        '{"action":"force_terminate"}',
    ],
)
def test_legacy_termination_controls_remain_distinct_from_timing_controls(
    control_message: str,
) -> None:
    assert is_legacy_termination_control(control_message) is True
    assert is_legacy_termination_control(
        '{"type":"native_stream_timing","stream_offset_seconds":5}'
    ) is False
