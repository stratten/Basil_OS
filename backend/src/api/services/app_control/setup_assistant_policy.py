"""The settings the Setup Assistant may propose, kept beside the registry so there is one place that decides what is changeable and by whom.

The Setup Assistant is a different route from an agent calling `app_settings`: its proposals are shown to the user in the setup approval card with the exact values, and the user approves them there. So it may propose a few settings that the registry keeps human-only for an agent acting on its own. Every such setting is listed in SETUP_ASSISTANT_EXCEPTIONS with the reason, and a test fails if the Setup Assistant allows a setting the registry does not classify, or if an exception no longer matches.
"""

from __future__ import annotations

from typing import Dict, FrozenSet

from .entries import AVAILABLE_FONTS

SETUP_ASSISTANT_COLOR_KEYS: FrozenSet[str] = frozenset(
    f"{color}_{channel}"
    for color in ("background_color", "primary_color", "secondary_color", "text_color", "processing_color", "processing_accent_color")
    for channel in ("red", "green", "blue")
)

SETUP_ASSISTANT_ALLOWLISTS: Dict[str, FrozenSet[str]] = {
    "models": frozenset(
        {
            "reasoning_model",
            "transcription_model",
            "language_model",
            "vision_model",
            "use_api_models",
            "close_assistant_session_on_insert",
            "assistant_output_paste_mode",
            "use_region_selection",
        }
    ),
    "behavior": frozenset({"enable_monitoring_at_startup", "enable_voice_listener_at_startup"}),
    "activity_capture": frozenset({"enabled", "start_at_startup", "frequency_minutes", "processing_mode", "scheduled_processing_time"}),
    "memory_intelligence": frozenset(
        {
            "memory_after_task_enabled",
            "memory_daily_enabled",
            "memory_daily_time_local",
            "memory_processing_model",
            "skill_after_task_enabled",
            "skill_daily_enabled",
            "skill_daily_time_local",
            "skill_processing_model",
        }
    ),
    "tool_execution": frozenset({"auto_approve_read_only"}),
    "ui": SETUP_ASSISTANT_COLOR_KEYS | {"preferred_font"},
}

SETUP_ASSISTANT_FONTS: FrozenSet[str] = frozenset(AVAILABLE_FONTS)

_APPROVED_IN_SETUP = "The Setup Assistant shows the user the exact value in its own approval card. An agent using app_settings cannot change it."

SETUP_ASSISTANT_EXCEPTIONS: Dict[str, str] = {
    **{
        f"models.{name}": f"{_APPROVED_IN_SETUP} Model choices are made during first-run setup."
        for name in ("reasoning_model", "transcription_model", "language_model", "vision_model")
    },
    **{
        f"memory_intelligence.{name}": f"{_APPROVED_IN_SETUP} Model choices are made during first-run setup."
        for name in ("memory_processing_model", "skill_processing_model")
    },
    "tool_execution.auto_approve_read_only": f"{_APPROVED_IN_SETUP} This one widens what Basil does without asking, so it is the first to review if the Setup Assistant's authority is ever narrowed.",
    **{
        f"activity_capture.{name}": f"{_APPROVED_IN_SETUP} Turning capture on or off is offered during first-run setup."
        for name in ("enabled", "start_at_startup", "frequency_minutes", "processing_mode", "scheduled_processing_time")
    },
}
