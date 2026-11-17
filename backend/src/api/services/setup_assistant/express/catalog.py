"""What express setup can turn on at each comfort level, in plain words."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Set, Tuple

from .models import ComfortLevel, ItemGroup

COMFORT_RANK: Dict[str, int] = {"cautious": 0, "balanced": 1, "all_in": 2}

DOWNLOAD_THINKING = "download_thinking_model"
DOWNLOAD_VOICE_FAST = "download_voice_fast"
DOWNLOAD_VOICE_QUALITY = "download_voice_quality"
LEARN_MEMORY = "learn_memory"
LEARN_SKILLS = "learn_skills"
CAPTURE_ACTIVITY = "capture_activity"
DETECT_MEETINGS = "detect_meetings"
VOICE_LISTENER = "voice_listener"
HOTKEYS = "hotkeys"


@dataclass(frozen=True)
class CatalogEntry:
    id: str
    group: ItemGroup
    title: str
    comfort: ComfortLevel
    permissions: Tuple[str, ...] = ()
    native: bool = False
    # False means the level offers this item but the review screen shows it unticked, so it only turns on if the person ticks it.
    ticked_by_default: bool = True


CATALOG: Tuple[CatalogEntry, ...] = (
    CatalogEntry(DOWNLOAD_THINKING, "downloads", "Thinking model", "cautious"),
    CatalogEntry(DOWNLOAD_VOICE_FAST, "downloads", "Fast voice model", "cautious"),
    CatalogEntry(DOWNLOAD_VOICE_QUALITY, "downloads", "High-quality voice model", "cautious"),
    CatalogEntry(LEARN_MEMORY, "learning", "Memory after tasks", "cautious"),
    CatalogEntry(LEARN_SKILLS, "learning", "Reusable workflows", "cautious"),
    CatalogEntry(CAPTURE_ACTIVITY, "background", "Activity Capture", "balanced", permissions=("screen_recording",)),
    CatalogEntry(DETECT_MEETINGS, "background", "Meeting and Call Detection", "balanced", permissions=("microphone",)),
    # Offered at the all-in level but unticked, because the listener can react to sounds that are not the person. Revisit once wake-word false positives are fixed.
    CatalogEntry(VOICE_LISTENER, "background", "Voice Listener", "all_in", permissions=("microphone",), ticked_by_default=False),
    CatalogEntry(HOTKEYS, "hotkeys", "Hotkeys", "cautious", native=True),
)

ENTRY_BY_ID: Dict[str, CatalogEntry] = {entry.id: entry for entry in CATALOG}

_STATIC_SUMMARIES: Dict[str, str] = {
    DOWNLOAD_THINKING: "The model I think with. It runs on this Mac, so what you give me stays here.",
    DOWNLOAD_VOICE_FAST: "Turns your speech into text quickly. English only.",
    DOWNLOAD_VOICE_QUALITY: "Turns your speech into text more accurately and in many languages. It is a bigger download.",
    LEARN_MEMORY: "After a task, I propose short notes about you, such as your work and preferences. Nothing is saved until you approve it.",
    LEARN_SKILLS: "When a task goes well and looks repeatable, I propose a named workflow.",
    VOICE_LISTENER: "Starts the Voice Listener every time Basil launches, so you can speak to me without touching the keyboard.",
    HOTKEYS: "Checks that Basil's shortcuts do not clash with shortcuts already on this Mac. If one does, I switch it to a free shortcut and tell you which, and you can change it in Settings, Hotkeys.",
}

_CAUTIONS: Dict[str, str] = {
    CAPTURE_ACTIVITY: "macOS asks for screen recording access the first time capture runs.",
    DETECT_MEETINGS: "macOS asks for microphone access the first time you accept a meeting prompt.",
    VOICE_LISTENER: "In noisy places it can react to sounds that are not you. Untick it if that happens to you. macOS asks for microphone access the first time it listens.",
}


def includes(level: ComfortLevel, entry: CatalogEntry) -> bool:
    """True when `level` turns this entry on."""
    return COMFORT_RANK[level] >= COMFORT_RANK[entry.comfort]


def summary_for(entry_id: str, level: ComfortLevel) -> str:
    """One plain sentence on what this entry does at this level."""
    if entry_id == CAPTURE_ACTIVITY:
        if level == "all_in":
            return "Adds Activity Capture to the Basil menu and starts it every time Basil launches. It records what is on your screen at intervals and keeps it on this Mac."
        return "Adds Activity Capture to the Basil menu. It records your screen only when you start it from there."
    if entry_id == DETECT_MEETINGS:
        if level == "all_in":
            return "Starts watching for meetings and calls every time Basil launches. I still ask before I record anything."
        return "Adds Meeting and Call Detection. When a meeting starts I ask before I record anything, and it does not start by itself at launch."
    return _STATIC_SUMMARIES[entry_id]


def caution_for(entry_id: str) -> Optional[str]:
    return _CAUTIONS.get(entry_id)


def settings_for(entry_id: str, level: ComfortLevel) -> Dict[str, Dict[str, object]]:
    """The settings an entry writes at this level, as section -> {key: value}. Downloads and native items write none."""
    if entry_id == LEARN_MEMORY:
        return {"memory_intelligence": {"memory_after_task_enabled": True}}
    if entry_id == LEARN_SKILLS:
        return {"memory_intelligence": {"skill_after_task_enabled": True}}
    if entry_id == CAPTURE_ACTIVITY:
        return {"activity_capture": {"enabled": True, "start_at_startup": level == "all_in"}}
    if entry_id == DETECT_MEETINGS:
        return {"meeting_detection": {"enabled": True, "start_at_startup": level == "all_in", "mode": "prompt"}}
    if entry_id == VOICE_LISTENER:
        return {"behavior": {"enable_voice_listener_at_startup": True}}
    return {}


def _all_express_setting_paths() -> Set[str]:
    paths: Set[str] = set()
    for entry in CATALOG:
        for level in COMFORT_RANK:
            for section, updates in settings_for(entry.id, level).items():  # type: ignore[arg-type]
                paths.update(f"{section}.{key}" for key in updates)
    return paths


# Every setting express may write. A test pins each path to the app-control registry.
EXPRESS_SETTING_PATHS: Set[str] = _all_express_setting_paths()


def already_matches(entry_id: str, level: ComfortLevel, preferences: object) -> bool:
    """True when every setting this entry would turn on is already on. Express never turns anything off, so a False target is always satisfied."""
    targets = settings_for(entry_id, level)
    if not targets:
        return False
    for section, updates in targets.items():
        section_obj = getattr(preferences, section)
        for key, value in updates.items():
            if value is True and getattr(section_obj, key) is not True:
                return False
    return True
