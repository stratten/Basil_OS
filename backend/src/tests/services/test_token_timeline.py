"""Tests for token timeline assignment and silence-coverage suppression (2F)."""

import numpy as np

from api.services.whisper_live_core.token_timeline import (
    assign_token_timeline,
    assign_token_timeline_from_offset,
    suppress_hallucinated_silence_tokens,
)


class FakeToken:
    """Minimal stand-in for an ASR token exposing the attributes the timeline
    and suppression helpers use."""

    def __init__(self, text: str, start: float, end: float, silence: bool = False):
        self.text = text
        self.start = start
        self.end = end
        self._silence = silence
        self.timeline_start_seconds = None
        self.timeline_end_seconds = None

    def is_silence(self) -> bool:
        return self._silence


SAMPLE_RATE = 16000


def _silent_chunk(seconds: float = 2.0) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)


def _speech_chunk(seconds: float = 2.0, amplitude: float = 0.2) -> np.ndarray:
    t = np.linspace(0, seconds, int(SAMPLE_RATE * seconds), endpoint=False, dtype=np.float32)
    return (amplitude * np.sin(2 * np.pi * 220.0 * t)).astype(np.float32)


# ---- assign_token_timeline ----

def test_assign_token_timeline_maps_to_stream_end() -> None:
    tokens = [FakeToken("hello", 10.0, 10.5), FakeToken("world", 10.5, 11.0)]
    assign_token_timeline(tokens, stream_time_end=100.0)
    # Span is 1.0s ending at 100.0, so window is [99.0, 100.0].
    assert abs(tokens[0].timeline_start_seconds - 99.0) < 1e-6
    assert abs(tokens[-1].timeline_end_seconds - 100.0) < 1e-6
    # Monotonic, within the window.
    assert tokens[0].timeline_start_seconds <= tokens[1].timeline_start_seconds


def test_assign_token_timeline_applies_native_capture_offset_to_token_bounds() -> None:
    baseline = [FakeToken("hello", 10.0, 10.5), FakeToken("world", 10.5, 11.0)]
    shifted = [FakeToken("hello", 10.0, 10.5), FakeToken("world", 10.5, 11.0)]
    assign_token_timeline(baseline, stream_time_end=100.0)
    assign_token_timeline(shifted, stream_time_end=700.0)

    assert shifted[0].timeline_start_seconds == baseline[0].timeline_start_seconds + 600.0
    assert shifted[-1].timeline_end_seconds == baseline[-1].timeline_end_seconds + 600.0
    assert shifted[0].timeline_end_seconds - shifted[0].timeline_start_seconds == 0.5
    assert shifted[0].timeline_start_seconds <= shifted[1].timeline_start_seconds


def test_assign_token_timeline_ignores_silence_only() -> None:
    tokens = [FakeToken("", 0.0, 1.0, silence=True)]
    assign_token_timeline(tokens, stream_time_end=50.0)
    assert tokens[0].timeline_start_seconds is None


# ---- assign_token_timeline_from_offset (2G gated alternative) ----

def test_offset_anchoring_uses_absolute_token_times_plus_origin() -> None:
    tokens = [FakeToken("a", 100.0, 100.5), FakeToken("b", 100.5, 101.0)]
    assign_token_timeline_from_offset(tokens, session_origin_offset=1.5)
    # Absolute token times shifted only by the cross-track origin offset.
    assert abs(tokens[0].timeline_start_seconds - 101.5) < 1e-6
    assert abs(tokens[1].timeline_end_seconds - 102.5) < 1e-6


def test_offset_anchoring_skips_silence_and_clamps() -> None:
    silence = FakeToken("", 5.0, 6.0, silence=True)
    speech = FakeToken("x", -2.0, 0.5)  # negative absolute start clamps to >= 0
    assign_token_timeline_from_offset([silence, speech], session_origin_offset=0.0)
    assert silence.timeline_start_seconds is None
    assert speech.timeline_start_seconds == 0.0


# ---- suppress_hallucinated_silence_tokens ----

def test_suppression_drops_speech_on_silent_chunk() -> None:
    tokens = [FakeToken("Learn", 0.0, 0.5), FakeToken("English", 0.5, 1.0)]
    result = suppress_hallucinated_silence_tokens(
        _silent_chunk(), tokens, sample_rate=SAMPLE_RATE
    )
    assert result == []


def test_suppression_preserves_silence_markers_on_silent_chunk() -> None:
    silence = FakeToken("", 0.0, 1.0, silence=True)
    speech = FakeToken("engvid", 1.0, 1.5)
    result = suppress_hallucinated_silence_tokens(
        _silent_chunk(), [silence, speech], sample_rate=SAMPLE_RATE
    )
    assert result == [silence]


def test_suppression_passes_through_speech_chunk() -> None:
    tokens = [FakeToken("real", 0.0, 0.5), FakeToken("speech", 0.5, 1.0)]
    result = suppress_hallucinated_silence_tokens(
        _speech_chunk(), tokens, sample_rate=SAMPLE_RATE
    )
    assert result == tokens


def test_suppression_retains_low_but_real_speech() -> None:
    # Adversarial: quiet but real tone (near threshold) still produces active
    # windows, so tokens must be retained.
    tokens = [FakeToken("quiet", 0.0, 0.5)]
    quiet = _speech_chunk(amplitude=0.02)
    result = suppress_hallucinated_silence_tokens(
        quiet, tokens, sample_rate=SAMPLE_RATE
    )
    assert result == tokens


def test_suppression_noops_on_empty_tokens() -> None:
    assert suppress_hallucinated_silence_tokens(_silent_chunk(), [], sample_rate=SAMPLE_RATE) == []


def test_suppression_noops_on_empty_audio() -> None:
    tokens = [FakeToken("x", 0.0, 0.5)]
    result = suppress_hallucinated_silence_tokens(
        np.zeros(0, dtype=np.float32), tokens, sample_rate=SAMPLE_RATE
    )
    assert result == tokens
