import numpy as np
import pytest

from api.services.wake_word.capture_endpointing import (
    FRAME_SAMPLES,
    SAMPLE_RATE,
    CaptureEndpointTracker,
    EndpointSettings,
    EnergySpeechProbability,
)


class LoudnessProbability:
    """Treats any frame with a clear peak as speech, so tests control speech by amplitude alone."""

    def __call__(self, frame):
        return 1.0 if float(np.max(np.abs(frame))) > 0.1 else 0.0

    def reset(self):
        pass


def speech(seconds):
    return np.full(int(seconds * SAMPLE_RATE), 0.5, dtype=np.float32)


def silence(seconds):
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


def make_tracker(**settings):
    return CaptureEndpointTracker(LoudnessProbability(), EndpointSettings(**settings))


def test_trailing_silence_counts_audio_seconds_after_speech():
    tracker = make_tracker(silence_seconds=2.0)

    tracker.feed(speech(1.0))
    tracker.feed(silence(1.0))

    assert tracker.heard_speech is True
    assert tracker.trailing_silence_seconds == pytest.approx(1.0, abs=0.07)
    assert tracker.remaining_seconds == pytest.approx(1.0, abs=0.07)
    assert tracker.speech_has_ended is False


def test_speech_ends_after_the_silence_threshold_of_audio():
    tracker = make_tracker(silence_seconds=2.0)

    tracker.feed(speech(1.0))
    tracker.feed(silence(2.1))

    assert tracker.speech_has_ended is True
    assert tracker.remaining_seconds == 0.0


def test_the_result_does_not_depend_on_how_the_audio_arrives():
    whole = make_tracker()
    whole.feed(np.concatenate([speech(1.0), silence(1.5)]))

    piecemeal = make_tracker()
    audio = np.concatenate([speech(1.0), silence(1.5)])
    for start in range(0, audio.size, 97):
        piecemeal.feed(audio[start:start + 97])

    assert piecemeal.trailing_silence_seconds == pytest.approx(whole.trailing_silence_seconds, abs=FRAME_SAMPLES / SAMPLE_RATE)
    assert piecemeal.speech_has_ended == whole.speech_has_ended


def test_a_burst_of_delayed_audio_is_measured_by_its_length_not_its_arrival():
    tracker = make_tracker(silence_seconds=2.0)
    tracker.feed(speech(1.0))

    tracker.feed(silence(0.6))
    tracker.feed(speech(0.4))
    tracker.feed(silence(1.0))

    assert tracker.speech_has_ended is False
    assert tracker.trailing_silence_seconds == pytest.approx(1.0, abs=0.07)


def test_a_pause_shorter_than_the_threshold_does_not_end_and_resets_when_speech_resumes():
    tracker = make_tracker(silence_seconds=2.0)
    tracker.feed(speech(1.0))
    tracker.feed(silence(1.8))

    assert tracker.speech_has_ended is False

    tracker.feed(speech(0.5))

    assert tracker.trailing_silence_seconds == 0.0
    assert tracker.in_speech is True
    assert tracker.speech_has_ended is False


def test_a_click_shorter_than_the_minimum_speech_is_not_speech():
    tracker = make_tracker(min_speech_seconds=0.3)

    tracker.feed(speech(0.1))
    tracker.feed(silence(3.0))

    assert tracker.heard_speech is False
    assert tracker.speech_has_ended is False
    assert tracker.trailing_silence_seconds == 0.0


def test_no_speech_times_out_instead_of_waiting_for_the_two_minute_limit():
    tracker = make_tracker(no_speech_seconds=8.0)

    tracker.feed(silence(7.0))
    assert tracker.no_speech_timed_out is False

    tracker.feed(silence(1.5))
    assert tracker.no_speech_timed_out is True


def test_speech_that_was_heard_never_counts_as_no_speech():
    tracker = make_tracker(no_speech_seconds=8.0)

    tracker.feed(speech(1.0))
    tracker.feed(silence(9.0))

    assert tracker.no_speech_timed_out is False


def test_hysteresis_keeps_a_dip_inside_speech():
    class DippingProbability:
        def __init__(self):
            self.values = iter([0.9, 0.4, 0.4, 0.4, 0.9])

        def __call__(self, frame):
            return next(self.values, 0.0)

        def reset(self):
            pass

    tracker = CaptureEndpointTracker(DippingProbability(), EndpointSettings(min_speech_seconds=0.0))

    tracker.feed(np.zeros(FRAME_SAMPLES * 5, dtype=np.float32))

    assert tracker.in_speech is True
    assert tracker.trailing_silence_seconds == 0.0


class TestEnergyFallback:
    def test_steady_background_noise_is_not_speech(self):
        detector = EnergySpeechProbability()
        noise = np.random.default_rng(1).normal(0, 0.01, FRAME_SAMPLES).astype(np.float32)

        results = [detector(noise) for _ in range(50)]

        assert max(results[10:]) == 0.0

    def test_quiet_speech_over_a_quiet_room_is_speech(self):
        detector = EnergySpeechProbability()
        room = np.random.default_rng(2).normal(0, 0.002, FRAME_SAMPLES).astype(np.float32)
        voice = np.random.default_rng(3).normal(0, 0.03, FRAME_SAMPLES).astype(np.float32)
        for _ in range(30):
            detector(room)

        assert detector(voice) == 1.0

    def test_digital_silence_is_not_speech(self):
        detector = EnergySpeechProbability()

        assert detector(np.zeros(FRAME_SAMPLES, dtype=np.float32)) == 0.0


def test_the_wake_word_silence_limit_is_two_and_a_half_seconds():
    from api.services.wake_word.capture_endpointing import WAKE_WORD_SILENCE_SECONDS

    assert WAKE_WORD_SILENCE_SECONDS == 2.5
    assert EndpointSettings().silence_seconds == WAKE_WORD_SILENCE_SECONDS
