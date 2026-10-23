from types import SimpleNamespace

from api.services.meeting_companion.capacity import LagCapacityGuard, allowed_triggers, prefetch_allowed, recorder_lag_provider
from api.services.meeting_companion.gate import ALL_TRIGGERS, DEFERRED_TRIGGERS


def test_guard_escalates_only_after_sustain_and_recovers_with_hysteresis():
    lag = {"value": 2.0}
    guard = LagCapacityGuard(lambda: lag["value"])
    assert guard.assess(0).state == "ok"
    lag["value"] = 10.0
    assert guard.assess(1).state == "ok"
    assert guard.assess(5).state == "deferred"
    lag["value"] = 30.0
    assert guard.assess(6).state == "deferred"
    paused = guard.assess(10)
    assert paused.state == "paused" and "30s behind" in paused.reason
    lag["value"] = 14.0
    assert guard.assess(11).state == "deferred"
    lag["value"] = 6.0
    assert guard.assess(12).state == "deferred"
    lag["value"] = 3.0
    assert guard.assess(13).state == "ok"
    assert guard.assess(13).reason is None


def test_spike_shorter_than_sustain_does_not_escalate():
    lag = {"value": 12.0}
    guard = LagCapacityGuard(lambda: lag["value"])
    assert guard.assess(0).state == "ok"
    lag["value"] = 1.0
    assert guard.assess(2).state == "ok"
    lag["value"] = 12.0
    assert guard.assess(3).state == "ok"
    assert guard.assess(6).state == "ok"
    assert guard.assess(7.5).state == "deferred"


def test_failing_provider_reads_as_zero_lag():
    def broken():
        raise RuntimeError("boom")

    assert LagCapacityGuard(broken).assess(0).state == "ok"


def test_allowed_triggers_and_prefetch_policy():
    assert allowed_triggers("ok") == ALL_TRIGGERS
    assert allowed_triggers("deferred") == DEFERRED_TRIGGERS
    assert allowed_triggers("paused") == frozenset()
    assert prefetch_allowed("ok") and not prefetch_allowed("deferred") and not prefetch_allowed("paused")


def test_recorder_lag_provider_takes_the_maximum_and_ignores_bad_values():
    recorders = [
        SimpleNamespace(transcription_lag_seconds=3.5),
        SimpleNamespace(transcription_lag_seconds="oops"),
        SimpleNamespace(),
        SimpleNamespace(transcription_lag_seconds=None),
        SimpleNamespace(transcription_lag_seconds=9.25),
    ]
    assert recorder_lag_provider(lambda: recorders)() == 9.25
    assert recorder_lag_provider(lambda: [])() == 0.0
