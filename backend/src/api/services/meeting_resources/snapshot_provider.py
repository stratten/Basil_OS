"""Builds the resource snapshot from the live recorders, the Companion sessions and the system."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional

from api.services.meeting_companion.capacity import recorder_lag_provider
from api.services.meetings import meeting_recording_registry

from .models import ResourceSnapshot
from .rules import parse_model_size_gb
from .system_probe import SystemMetrics, read_system_metrics

SnapshotProvider = Callable[[Optional[str]], ResourceSnapshot]

_CAPACITY_RANK = {"ok": 0, "deferred": 1, "paused": 2}


def analysis_jobs_running(jobs: Dict[str, Any]) -> bool:
    """True when any tracked analysis job is processing."""
    return any(isinstance(job, dict) and job.get("status") == "processing" for job in list(jobs.values()))


def _worst_capacity(statuses: Iterable[Any]) -> tuple[Optional[str], Optional[str]]:
    worst: Optional[Any] = None
    for status in statuses:
        if not getattr(status, "live", False):
            continue
        if worst is None or _CAPACITY_RANK.get(status.capacity, 0) > _CAPACITY_RANK.get(worst.capacity, 0):
            worst = status
    if worst is None:
        return None, None
    return worst.capacity, worst.capacity_reason


def _largest_local_model_gb(statuses: Iterable[Any], model_lookup: Callable[[str], Optional[Dict[str, Any]]]) -> Optional[float]:
    largest: Optional[float] = None
    for status in statuses:
        if not getattr(status, "live", False) or not getattr(status, "enabled", False) or not status.model_id:
            continue
        config = model_lookup(status.model_id)
        if not config or config.get("location") != "local":
            continue
        size = parse_model_size_gb(config.get("size"))
        if size is not None and (largest is None or size > largest):
            largest = size
    return largest


def build_snapshot_provider(
    *,
    analysis_running: Callable[[], bool],
    companion_statuses: Callable[[], List[Any]],
    model_lookup: Callable[[str], Optional[Dict[str, Any]]],
    metrics_reader: Callable[[], SystemMetrics] = read_system_metrics,
    recorders: Callable[[], Iterable[Any]] = meeting_recording_registry.active_recorders,
) -> SnapshotProvider:
    """A provider that returns an idle snapshot, without reading the system, when nothing is recording."""
    lag_provider = recorder_lag_provider(recorders)

    def provider(thermal_state: Optional[str]) -> ResourceSnapshot:
        if not list(recorders()):
            return ResourceSnapshot()
        metrics = metrics_reader()
        statuses = companion_statuses()
        capacity, reason = _worst_capacity(statuses)
        return ResourceSnapshot(
            recording=True,
            lag_seconds=lag_provider(),
            cpu_percent=metrics.cpu_percent,
            memory_percent=metrics.memory_percent,
            total_memory_gb=metrics.total_memory_gb,
            thermal_state=thermal_state,
            analysis_running=analysis_running(),
            companion_capacity=capacity,
            companion_reason=reason,
            companion_model_size_gb=_largest_local_model_gb(statuses, model_lookup),
        )

    return provider
