"""The closed list of things an agent can ask the Mac app to do, and the checks on what it may ask.

Each verb is defined here and again in the Mac app (client/Sources/Services/WebSocket/WebSocketService+NativeCommand.swift). A test fails if the two lists differ. Verbs never take free-form text, file paths or commands, only a choice from a fixed list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Tuple

# The Settings window's top-level tabs, as the Settings screen names them.
SETTINGS_TABS: Dict[str, str] = {
    "home": "Home",
    "hotkeys": "Hotkeys",
    "profile": "Profile",
    "memory-intelligence": "Personal Context",
    "writing-examples": "Writing Examples",
    "models": "Models",
    "reasoning": "Automation & Agents",
    "transcription": "Transcription",
    "meetings": "Notetaker",
    "capture": "Capture",
    "connections": "Connections",
    "permissions": "Permissions",
    "account": "Account",
    "appearance": "Appearance & Format",
}


class NativeCommandError(ValueError):
    """The request is not an allowed verb with allowed parameters."""


@dataclass(frozen=True)
class NativeVerb:
    name: str
    description: str
    validate: Callable[[Mapping[str, Any]], Dict[str, Any]]


def _validate_open_settings(params: Mapping[str, Any]) -> Dict[str, Any]:
    unknown = set(params) - {"tab"}
    if unknown:
        raise NativeCommandError(f"open_settings takes only tab, not {sorted(unknown)}.")
    tab = params.get("tab")
    if tab is None or tab == "":
        return {}
    if not isinstance(tab, str) or tab not in SETTINGS_TABS:
        raise NativeCommandError(f"Unknown settings tab. Use one of: {', '.join(sorted(SETTINGS_TABS))}.")
    return {"tab": tab}


VERBS: Dict[str, NativeVerb] = {
    "open_settings": NativeVerb(
        name="open_settings",
        description="Bring the Settings window to the front, on a given tab when one is named.",
        validate=_validate_open_settings,
    ),
}


def validate_native_command(verb: str, params: Mapping[str, Any] | None) -> Tuple[str, Dict[str, Any]]:
    """Return the verb and its cleaned parameters, or raise NativeCommandError."""
    definition = VERBS.get(verb)
    if definition is None:
        raise NativeCommandError(f"Unknown command {verb!r}. Use one of: {', '.join(sorted(VERBS))}.")
    return verb, definition.validate(dict(params or {}))
