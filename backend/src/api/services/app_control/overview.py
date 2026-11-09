"""A short map of what an agent can and cannot do to Basil, so it learns the shape of its reach without a long prompt."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict

from .classification import SECTION_LABELS
from .manifest import APPROVAL_TIERS, ControlRegistry, Tier
from .native_commands import SETTINGS_TABS, VERBS
from .route_classification import DEFERRED_BASELINE

# What each deferred domain covers, in the words an agent should repeat to a user. Every domain in DEFERRED_BASELINE needs one; a test enforces it.
DOMAIN_LABELS: Dict[str, str] = {
    "agent_and_schedule_audit": "editing, deleting or running schedules, and controlling other agent tasks",
    "appearance_themes": "saving and deleting named themes",
    "capture_and_detection": "starting and stopping screen capture, ambient suggestions, meeting detection and the voice listener, and clearing captured history",
    "connections_and_profiles": "editing or removing connections, and turning provider profiles on or off",
    "meeting_automation": "starting, stopping and editing meetings and the meeting companion",
    "memory_todos_board": "deleting To-Dos, editing memory files and skills, and board routing",
    "models_and_downloads": "downloading, adding and removing models, and choosing which cloud models are on",
    "personalization": "the user's profile, writing samples and style analysis",
}

_EXTRA_SECTION_LABELS = {"appearance": "Appearance", "security": "Permissions", "connections": "Connections"}


def build_overview(registry: ControlRegistry) -> Dict[str, Any]:
    """Counts by settings section, plus what other abilities exist, what is not available yet, and what only the user can do."""
    sections: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for entry in sorted(registry.all(), key=lambda item: item.key):
        prefix = entry.key.split(".", 1)[0]
        label = _EXTRA_SECTION_LABELS.get(prefix) or SECTION_LABELS.get(prefix) or prefix.replace("_", " ").title()
        bucket = sections.setdefault(prefix, {"section": prefix, "label": label, "free": 0, "needs_approval": 0, "only_the_user": 0})
        if not entry.changeable:
            bucket["only_the_user"] += 1
        elif entry.tier in APPROVAL_TIERS:
            bucket["needs_approval"] += 1
        else:
            bucket["free"] += 1
    return {
        "ok": True,
        "settings_sections": list(sections.values()),
        "how_to_use": "Use action list with query words to find exact keys and allowed values for a section. free settings apply at once and can be undone; needs_approval settings show the user a card and wait; only_the_user settings are listed when a query matches them but you cannot change them.",
        "other_abilities": [
            "To-Dos: create, list, inspect, edit, add notes and references, and change status with the To-Do tools.",
            "Schedules: create a schedule, list the schedules and pause one with the schedule tools.",
            "Settings window: show_in_settings opens it on one of these tabs: " + ", ".join(SETTINGS_TABS) + ".",
        ],
        "native_commands": {name: verb.description for name, verb in VERBS.items()},
        "not_available_yet": [DOMAIN_LABELS[domain] for domain in sorted(DEFERRED_BASELINE)],
        "only_the_user_can": "approve commands, change credentials, API keys, sign-ins and connections' tokens, change what Basil is permitted to do, grant macOS permissions, and reset settings. Tell the user where in Settings to do it, and offer show_in_settings.",
    }
