"""The end-of-setup receipt: what is on right now, read from real state, with where to change each item."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .catalog import (
    CAPTURE_ACTIVITY,
    CATALOG,
    DETECT_MEETINGS,
    DOWNLOAD_THINKING,
    DOWNLOAD_VOICE_FAST,
    DOWNLOAD_VOICE_QUALITY,
    HOTKEYS,
    LEARN_MEMORY,
    LEARN_SKILLS,
    VOICE_LISTENER,
)
from .models import ReceiptItem, ReceiptState, SetupReceipt
from .planner import DownloadSpec

WHERE_TO_CHANGE: Dict[str, str] = {
    DOWNLOAD_THINKING: "Settings, Capabilities, Models",
    DOWNLOAD_VOICE_FAST: "Settings, Capabilities, Models",
    DOWNLOAD_VOICE_QUALITY: "Settings, Capabilities, Models",
    LEARN_MEMORY: "Settings, Personalization, Personal Context",
    LEARN_SKILLS: "Settings, Capabilities, Automation & Agents, Skills",
    CAPTURE_ACTIVITY: "Settings, General, Home",
    DETECT_MEETINGS: "Settings, General, Home",
    VOICE_LISTENER: "Settings, General, Home",
    HOTKEYS: "Settings, General, Hotkeys",
}


def _toggle(is_on: bool, on_detail: str, off_detail: str = "Off.") -> Tuple[ReceiptState, str]:
    return ("on", on_detail) if is_on else ("off", off_detail)


def _background(enabled: bool, at_launch: bool) -> Tuple[ReceiptState, str]:
    if enabled and at_launch:
        return "on", "Starts every time Basil launches."
    if enabled:
        return "partial", "In the Basil menu. You start it yourself."
    return "off", "Off."


def build_receipt(specs: Dict[str, DownloadSpec], preferences: Any) -> SetupReceipt:
    """Read the state of every express item. `specs` holds the starter downloads, `preferences` the saved settings."""
    items: List[ReceiptItem] = []
    for entry in CATALOG:
        if entry.group == "downloads":
            spec = specs.get(entry.id)
            if spec is None:
                continue
            name = spec.display_name or entry.title
            state, detail = _toggle(spec.installed, f"{name} is on this Mac.", "Not on this Mac yet.")
        elif entry.id == LEARN_MEMORY:
            state, detail = _toggle(preferences.memory_intelligence.memory_after_task_enabled is True, "I propose notes after tasks, and you approve them.")
        elif entry.id == LEARN_SKILLS:
            state, detail = _toggle(preferences.memory_intelligence.skill_after_task_enabled is True, "I propose workflows after tasks.")
        elif entry.id == CAPTURE_ACTIVITY:
            state, detail = _background(
                preferences.activity_capture.enabled is True, preferences.activity_capture.start_at_startup is True
            )
        elif entry.id == DETECT_MEETINGS:
            state, detail = _background(
                preferences.meeting_detection.enabled is True, preferences.meeting_detection.start_at_startup is True
            )
        elif entry.id == VOICE_LISTENER:
            state, detail = _toggle(
                preferences.behavior.enable_voice_listener_at_startup is True, "Starts every time Basil launches."
            )
        else:
            state, detail = _toggle(
                preferences.behavior.enable_monitoring_at_startup is True, "Hotkeys are on.", "Hotkeys are off."
            )
        items.append(
            ReceiptItem(id=entry.id, group=entry.group, title=entry.title, state=state, detail=detail, where_to_change=WHERE_TO_CHANGE[entry.id])
        )
    return SetupReceipt(items=items)
