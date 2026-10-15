import pytest

from api.services.meeting_resources.models import ResourceSnapshot
from api.services.meeting_resources.rules import evaluate_rules, parse_model_size_gb


def snap(**overrides):
    base = dict(recording=True)
    base.update(overrides)
    return ResourceSnapshot(**base)


def ids(snapshot):
    return [advice.id for advice in evaluate_rules(snapshot)]


def test_nothing_applies_unless_a_recording_is_live():
    assert evaluate_rules(snap(recording=False, lag_seconds=99, cpu_percent=99, memory_percent=99, thermal_state="critical")) == []


def test_a_healthy_recording_has_no_advice():
    assert ids(snap(lag_seconds=2, cpu_percent=40, memory_percent=60, thermal_state="nominal", companion_capacity="ok")) == []


@pytest.mark.parametrize(("lag", "expected"), [(14.9, []), (15.0, ["transcription_lag"]), (60.0, ["transcription_lag"])])
def test_lag_rule_starts_at_the_threshold(lag, expected):
    assert ids(snap(lag_seconds=lag)) == expected


def test_lag_severity_and_text_are_stable_inside_a_ten_second_bucket():
    warning = evaluate_rules(snap(lag_seconds=17.0))[0]
    same_bucket = evaluate_rules(snap(lag_seconds=19.9))[0]
    critical = evaluate_rules(snap(lag_seconds=45.0))[0]
    assert warning.severity == "warning" and warning.action == "open_settings"
    assert warning.detail == same_bucket.detail and "more than 10 seconds" in warning.detail
    assert critical.severity == "critical" and "more than 40 seconds" in critical.detail


@pytest.mark.parametrize(("state", "severity"), [("nominal", None), ("fair", None), (None, None), ("serious", "warning"), ("critical", "critical")])
def test_thermal_rule(state, severity):
    found = evaluate_rules(snap(thermal_state=state))
    assert [advice.severity for advice in found] == ([severity] if severity else [])


def test_memory_and_cpu_rules_use_the_ninety_percent_threshold():
    assert ids(snap(memory_percent=89.9, cpu_percent=89.9)) == []
    assert ids(snap(memory_percent=90.0)) == ["memory_pressure"]
    cpu = evaluate_rules(snap(cpu_percent=95.0))[0]
    assert cpu.id == "cpu_saturated" and cpu.action == "open_settings"


def test_companion_capacity_rule_explains_deferred_and_paused():
    deferred = evaluate_rules(snap(companion_capacity="deferred"))[0]
    paused = evaluate_rules(snap(companion_capacity="paused", companion_reason="30s behind"))[0]
    bare = evaluate_rules(snap(companion_capacity="paused"))[0]
    assert deferred.severity == "info" and "optional work" in deferred.detail
    assert paused.severity == "warning" and "(30s behind)" in paused.detail
    assert "(" not in bare.detail
    assert evaluate_rules(snap(companion_capacity="ok")) == []


def test_analysis_rule_needs_both_a_running_analysis_and_some_lag():
    assert ids(snap(analysis_running=True, lag_seconds=7.9)) == []
    assert ids(snap(analysis_running=False, lag_seconds=10)) == []
    assert ids(snap(analysis_running=True, lag_seconds=8.0)) == ["analysis_running"]


def test_large_model_rule_compares_against_total_memory():
    assert ids(snap(companion_model_size_gb=7.9, total_memory_gb=16)) == []
    assert ids(snap(companion_model_size_gb=8.0, total_memory_gb=16)) == ["companion_model_large"]
    assert ids(snap(companion_model_size_gb=8.0, total_memory_gb=0)) == []
    assert ids(snap(companion_model_size_gb=None, total_memory_gb=16)) == []
    detail = evaluate_rules(snap(companion_model_size_gb=9.5, total_memory_gb=16))[0].detail
    assert "9.5 GB of 16 GB" in detail


def test_advice_is_ordered_by_severity_then_rule_order():
    found = evaluate_rules(snap(lag_seconds=50, thermal_state="serious", memory_percent=95, companion_capacity="deferred", analysis_running=True))
    assert [advice.id for advice in found] == ["transcription_lag", "thermal", "memory_pressure", "companion_capacity", "analysis_running"]
    assert [advice.severity for advice in found] == ["critical", "warning", "warning", "info", "info"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("1.93GB", 1.93), ("640MB", 0.625), (" 2.4 gb ", 2.4), ("1TB", 1024.0), ("512KB", 512 / 1024 / 1024), ("", None), ("big", None), ("12", None), ("-3GB", None), (None, None), (4, None)],
)
def test_parse_model_size_gb(text, expected):
    result = parse_model_size_gb(text)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)
