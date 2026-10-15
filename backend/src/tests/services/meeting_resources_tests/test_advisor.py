import pytest

from api.services.meeting_resources.advisor import ResourceAdvisor
from api.services.meeting_resources.models import THERMAL_REPORT_TTL_SECONDS, ResourceSnapshot


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Source:
    def __init__(self):
        self.snapshot = ResourceSnapshot(recording=True)
        self.thermal_seen = []

    def __call__(self, thermal_state):
        self.thermal_seen.append(thermal_state)
        return ResourceSnapshot(**{**self.snapshot.__dict__, "thermal_state": thermal_state or self.snapshot.thermal_state})


def build(**kwargs):
    clock = Clock()
    source = Source()
    sent = []

    async def broadcaster(message):
        sent.append(message)

    advisor = ResourceAdvisor(source, broadcaster=broadcaster, clock=clock, wall_clock=lambda: 5000.0 + clock.now, sustain_seconds=20, clear_seconds=20, **kwargs)
    return advisor, source, clock, sent


def lagging(source, lag=30.0):
    source.snapshot = ResourceSnapshot(recording=True, lag_seconds=lag)


def test_advice_is_raised_only_after_the_sustain_window():
    advisor, source, clock, _ = build()
    lagging(source)
    assert advisor.sample() is False and advisor.state().advice == []
    clock.advance(19)
    assert advisor.sample() is False
    clock.advance(1)
    assert advisor.sample() is True
    state = advisor.state()
    assert [advice.id for advice in state.advice] == ["transcription_lag"] and state.revision == 1
    assert state.advice[0].raised_at == pytest.approx(5000.0 + clock.now)


def test_a_spike_shorter_than_the_sustain_window_never_raises():
    advisor, source, clock, _ = build()
    lagging(source)
    advisor.sample()
    clock.advance(15)
    source.snapshot = ResourceSnapshot(recording=True, lag_seconds=1.0)
    advisor.sample()
    clock.advance(10)
    lagging(source)
    advisor.sample()
    clock.advance(15)
    assert advisor.sample() is False and advisor.state().advice == []


def test_advice_clears_only_after_the_clear_window_and_flicker_does_not_clear_it():
    advisor, source, clock, _ = build()
    lagging(source)
    advisor.sample()
    clock.advance(20)
    advisor.sample()
    source.snapshot = ResourceSnapshot(recording=True, lag_seconds=1.0)
    clock.advance(5)
    assert advisor.sample() is False and len(advisor.state().advice) == 1
    lagging(source)
    clock.advance(5)
    advisor.sample()
    source.snapshot = ResourceSnapshot(recording=True, lag_seconds=1.0)
    clock.advance(19)
    advisor.sample()
    clock.advance(1)
    assert advisor.sample() is False
    assert advisor.state().advice != []
    clock.advance(20)
    assert advisor.sample() is True
    assert advisor.state().advice == []


def test_stopping_the_recording_clears_everything_at_once_and_forgets_dismissals():
    advisor, source, clock, _ = build()
    lagging(source)
    advisor.sample()
    clock.advance(20)
    advisor.sample()
    assert advisor.dismiss("transcription_lag") is True
    source.snapshot = ResourceSnapshot(recording=False)
    advisor.sample()
    assert advisor.state().advice == []
    lagging(source)
    advisor.sample()
    clock.advance(20)
    advisor.sample()
    assert [advice.id for advice in advisor.state().advice] == ["transcription_lag"]


def test_dismissed_advice_stays_hidden_until_the_rule_clears():
    advisor, source, clock, _ = build()
    lagging(source)
    advisor.sample()
    clock.advance(20)
    advisor.sample()
    revision = advisor.state().revision
    assert advisor.dismiss("transcription_lag") is True
    assert advisor.sample() is True and advisor.state().advice == [] and advisor.state().revision == revision + 1
    clock.advance(60)
    assert advisor.sample() is False and advisor.state().advice == []
    source.snapshot = ResourceSnapshot(recording=True, lag_seconds=1.0)
    clock.advance(1)
    advisor.sample()
    clock.advance(20)
    advisor.sample()
    lagging(source)
    advisor.sample()
    clock.advance(20)
    advisor.sample()
    assert [advice.id for advice in advisor.state().advice] == ["transcription_lag"]


def test_dismissing_unknown_advice_is_rejected():
    advisor, _, _, _ = build()
    assert advisor.dismiss("transcription_lag") is False and advisor.dismiss("nope") is False


def test_at_most_three_items_are_shown_most_severe_first():
    advisor, source, clock, _ = build()
    source.snapshot = ResourceSnapshot(recording=True, lag_seconds=50, thermal_state="serious", memory_percent=95, cpu_percent=95, companion_capacity="deferred")
    advisor.sample()
    clock.advance(20)
    advisor.sample()
    assert [advice.id for advice in advisor.state().advice] == ["transcription_lag", "thermal", "memory_pressure"]


def test_text_changes_update_the_visible_advice_without_resetting_raised_at():
    advisor, source, clock, _ = build()
    lagging(source, 20.0)
    advisor.sample()
    clock.advance(20)
    advisor.sample()
    first = advisor.state().advice[0]
    clock.advance(10)
    lagging(source, 52.0)
    assert advisor.sample() is True
    updated = advisor.state().advice[0]
    assert updated.severity == "critical" and "more than 50 seconds" in updated.detail and updated.raised_at == first.raised_at


def test_thermal_reports_are_validated_and_expire():
    advisor, source, clock, _ = build()
    assert advisor.report_thermal_state("lava") is False
    assert advisor.report_thermal_state("serious") is True
    advisor.sample()
    assert source.thermal_seen[-1] == "serious"
    clock.advance(THERMAL_REPORT_TTL_SECONDS)
    advisor.sample()
    assert source.thermal_seen[-1] == "serious"
    clock.advance(1)
    advisor.sample()
    assert source.thermal_seen[-1] is None


@pytest.mark.asyncio
async def test_publish_if_changed_sends_one_frame_per_change():
    advisor, source, clock, sent = build()
    lagging(source)
    assert await advisor.publish_if_changed() is False and sent == []
    clock.advance(20)
    assert await advisor.publish_if_changed() is True
    assert await advisor.publish_if_changed() is False
    assert len(sent) == 1
    frame = sent[0]
    assert frame["event_type"] == "resource_advice" and frame["revision"] == 1
    assert frame["advice"][0]["id"] == "transcription_lag" and frame["advice"][0]["action"] == "open_settings"


@pytest.mark.asyncio
async def test_the_loop_survives_a_failing_sample_and_stops_cleanly():
    calls = {"count": 0}

    def provider(thermal_state):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("probe failed")
        return ResourceSnapshot()

    advisor = ResourceAdvisor(provider, sample_interval_seconds=0.01)
    advisor.start()
    advisor.start()
    for _ in range(100):
        if calls["count"] >= 3:
            break
        await __import__("asyncio").sleep(0.01)
    await advisor.stop()
    assert calls["count"] >= 3
    await advisor.stop()
