"""Process-wide resource advisor lifecycle."""

from __future__ import annotations

from typing import Callable, Optional

from api.core.models.models_registry.schema import get_model
from api.services.meeting_companion.runtime import get_meeting_companion_runtime

from .advisor import ResourceAdvisor
from .snapshot_provider import build_snapshot_provider
from .system_probe import prime_system_metrics

_advisor: Optional[ResourceAdvisor] = None


def _companion_statuses():
    runtime = get_meeting_companion_runtime()
    return runtime.live_statuses() if runtime is not None else []


async def initialize_resource_advisor(*, analysis_running: Callable[[], bool]) -> ResourceAdvisor:
    global _advisor
    if _advisor is None:
        prime_system_metrics()
        provider = build_snapshot_provider(
            analysis_running=analysis_running,
            companion_statuses=_companion_statuses,
            model_lookup=get_model,
        )
        _advisor = ResourceAdvisor(provider)
        _advisor.start()
    return _advisor


async def cleanup_resource_advisor() -> None:
    global _advisor
    advisor, _advisor = _advisor, None
    if advisor is not None:
        await advisor.stop()


def get_resource_advisor() -> Optional[ResourceAdvisor]:
    return _advisor
