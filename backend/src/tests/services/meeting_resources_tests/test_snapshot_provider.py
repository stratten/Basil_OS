from types import SimpleNamespace

from api.services.meeting_resources.models import ResourceSnapshot
from api.services.meeting_resources.snapshot_provider import analysis_jobs_running, build_snapshot_provider
from api.services.meeting_resources.system_probe import SystemMetrics


def status(capacity="ok", reason=None, model_id=None, live=True, enabled=True):
    return SimpleNamespace(live=live, enabled=enabled, capacity=capacity, capacity_reason=reason, model_id=model_id)


def provider_for(recorders, statuses=(), registry=None, running=False):
    return build_snapshot_provider(
        analysis_running=lambda: running,
        companion_statuses=lambda: list(statuses),
        model_lookup=lambda model_id: (registry or {}).get(model_id),
        metrics_reader=lambda: SystemMetrics(cpu_percent=55.0, memory_percent=70.0, total_memory_gb=32.0),
        recorders=lambda: list(recorders),
    )


def test_idle_snapshot_does_not_read_the_system():
    def explode():
        raise AssertionError("must not read the system while idle")

    provider = build_snapshot_provider(analysis_running=explode, companion_statuses=explode, model_lookup=explode, metrics_reader=explode, recorders=lambda: [])
    assert provider("serious") == ResourceSnapshot()


def test_recording_snapshot_collects_every_input():
    recorders = [SimpleNamespace(transcription_lag_seconds=3.0), SimpleNamespace(transcription_lag_seconds=21.5)]
    statuses = [status("deferred", "9s behind"), status("paused", "30s behind", model_id="big"), status("paused", "ignored", live=False)]
    registry = {"big": {"location": "local", "size": "9.5GB"}}
    snapshot = provider_for(recorders, statuses, registry, running=True)("fair")
    assert snapshot.recording is True and snapshot.lag_seconds == 21.5
    assert (snapshot.cpu_percent, snapshot.memory_percent, snapshot.total_memory_gb) == (55.0, 70.0, 32.0)
    assert snapshot.thermal_state == "fair" and snapshot.analysis_running is True
    assert (snapshot.companion_capacity, snapshot.companion_reason) == ("paused", "30s behind")
    assert snapshot.companion_model_size_gb == 9.5


def test_no_live_companion_leaves_capacity_unset():
    snapshot = provider_for([SimpleNamespace(transcription_lag_seconds=0.0)], [status(live=False)])(None)
    assert snapshot.companion_capacity is None and snapshot.companion_reason is None and snapshot.companion_model_size_gb is None


def test_model_size_ignores_cloud_unknown_disabled_and_unreadable_models():
    registry = {
        "cloud": {"location": "cloud", "size": "40GB"},
        "odd": {"location": "local", "size": "huge"},
        "small": {"location": "local", "size": "640MB"},
        "large": {"location": "local", "size": "4.3GB"},
    }
    statuses = [status(model_id="cloud"), status(model_id="odd"), status(model_id="missing"), status(model_id="large", enabled=False), status(model_id="small"), status(model_id=None)]
    snapshot = provider_for([SimpleNamespace(transcription_lag_seconds=0.0)], statuses, registry)(None)
    assert snapshot.companion_model_size_gb == 0.625


def test_analysis_jobs_running_reads_processing_status_only():
    assert analysis_jobs_running({}) is False
    assert analysis_jobs_running({"m1": {"status": "pending"}, "m2": "odd", "m3": None}) is False
    assert analysis_jobs_running({"m1": {"status": "pending"}, "m2": {"status": "processing"}}) is True
