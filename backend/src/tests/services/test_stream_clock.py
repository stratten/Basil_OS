"""Tests for the native stream clock that maps samples onto meeting-elapsed time."""

import pytest

from api.services.live_transcription.stream_clock import StreamClock


def test_no_anchor_returns_none() -> None:
    clock = StreamClock()
    assert clock.has_anchors is False
    assert clock.timeline_seconds_for_sample(16000) is None


def test_samples_follow_the_nearest_preceding_anchor() -> None:
    clock = StreamClock()
    assert clock.add_anchor(0, 0.0) is True
    assert clock.add_anchor(32000, 2.5) is True
    assert clock.timeline_seconds_for_sample(16000) == pytest.approx(1.0)
    assert clock.timeline_seconds_for_sample(40000) == pytest.approx(3.0)


def test_drift_does_not_accumulate_past_an_anchor() -> None:
    clock = StreamClock()
    clock.add_anchor(0, 0.0)
    # One hour of wall clock, but the capture delivered 90 minutes of samples.
    clock.add_anchor(16000 * 5400, 3600.0)
    assert clock.timeline_seconds_for_sample(16000 * 5400 + 16000) == pytest.approx(3601.0)


def test_samples_before_the_first_anchor_extrapolate_and_clamp_at_zero() -> None:
    clock = StreamClock()
    clock.add_anchor(16000, 3.0)
    assert clock.timeline_seconds_for_sample(0) == pytest.approx(2.0)
    late = StreamClock()
    late.add_anchor(16000, 0.5)
    assert late.timeline_seconds_for_sample(0) == 0.0


def test_equal_index_replaces_the_last_anchor() -> None:
    clock = StreamClock()
    clock.add_anchor(100, 1.0)
    assert clock.add_anchor(100, 1.5) is True
    assert clock.timeline_seconds_for_sample(100) == pytest.approx(1.5)


@pytest.mark.parametrize(
    ("sample_index", "elapsed_seconds"),
    [(-1, 0.0), (True, 0.0), (1.5, 0.0), (0, float("nan")), (0, float("inf")), (0, -0.1), (0, True)],
)
def test_invalid_anchor_is_rejected(sample_index, elapsed_seconds) -> None:
    clock = StreamClock()
    assert clock.add_anchor(sample_index, elapsed_seconds) is False
    assert clock.has_anchors is False


def test_out_of_order_anchor_is_rejected() -> None:
    clock = StreamClock()
    clock.add_anchor(100, 1.0)
    assert clock.add_anchor(50, 2.0) is False
    assert clock.timeline_seconds_for_sample(100) == pytest.approx(1.0)


def test_non_positive_sample_rate_is_rejected() -> None:
    with pytest.raises(ValueError):
        StreamClock(sample_rate=0)
