"""Runs the same follow-up code the Settings screens run after saving, so an agent's change takes effect now and not at the next restart."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from .classification import (
    GROUP_AMBIENT_SUGGESTIONS,
    GROUP_MEETING_DETECTION,
    GROUP_MODEL_RESIDENCY,
    GROUP_ZETTEL,
)

logger = logging.getLogger(__name__)

Hook = Callable[[Any], Awaitable[None]]


async def apply_model_residency(preferences: Any) -> None:
    """Make a changed unload delay apply to models that are already loaded."""
    from api.routes.settings_routes.router import _apply_model_residency_settings

    _apply_model_residency_settings()


async def apply_zettel(preferences: Any) -> None:
    """Start or stop the unified event stream schedulers to match the saved settings."""
    from api.routes.settings_routes.zettel_routes import _apply_to_running_schedulers

    await _apply_to_running_schedulers(preferences.zettel)


async def apply_meeting_detection(preferences: Any) -> None:
    """Push meeting detection settings to the running detector."""
    from api.services.meeting_detection.runtime import get_meeting_detection_runtime

    runtime = get_meeting_detection_runtime()
    if runtime:
        await runtime.apply_settings(preferences.meeting_detection)


async def apply_ambient_suggestions(preferences: Any) -> None:
    """Push ambient suggestion settings to the running evaluator."""
    from api.services.ambient_suggestions.runtime import get_ambient_suggestion_runtime

    runtime = get_ambient_suggestion_runtime()
    if runtime:
        await runtime.apply_settings(preferences.ambient_suggestions)


def default_apply_hooks() -> Dict[str, Hook]:
    return {
        GROUP_MODEL_RESIDENCY: apply_model_residency,
        GROUP_ZETTEL: apply_zettel,
        GROUP_MEETING_DETECTION: apply_meeting_detection,
        GROUP_AMBIENT_SUGGESTIONS: apply_ambient_suggestions,
    }
