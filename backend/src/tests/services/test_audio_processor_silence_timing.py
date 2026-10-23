"""Tests for AudioProcessor's native capture-offset origin setter."""

from types import SimpleNamespace

import pytest

from api.services.whisper_live_core.audio_processor import AudioProcessor


def test_native_stream_offset_updates_emitted_timeline_origin() -> None:
    origins: list[float] = []
    fake = SimpleNamespace(
        native_stream_offset_seconds=0.0,
        meeting_recorder=SimpleNamespace(
            timeline_offset_seconds=120.0,
            set_stream_timeline_origin_seconds=origins.append,
        ),
    )

    AudioProcessor.set_native_stream_offset_seconds(fake, 600.0)

    assert fake.native_stream_offset_seconds == 600.0
    assert origins == [720.0]
    with pytest.raises(ValueError):
        AudioProcessor.set_native_stream_offset_seconds(fake, float("nan"))
