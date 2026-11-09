"""Agent tool for looking up and changing Basil's own settings, such as colors and text size."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile
from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context
from api.services.app_control.engine import get_app_control_engine
from api.services.app_control.native_command_bridge import send_native_command
from api.services.app_control.native_commands import SETTINGS_TABS

logger = logging.getLogger(__name__)

TOOL_NAME = "app_settings"

SLIM_DESCRIPTION = (
    "Look up and change Basil's own settings, such as its colors, text size and font. "
    "Actions: list (find settings; query narrows by words), get (keys), set (changes is a list of {key, value}; reason says why), undo (reverses your last change, or change_id), show_in_settings (opens the Settings window on a tab, for when the user asks where something is), overview (what you can and cannot do to Basil, by section; call it when asked what you can change). "
    "Always call list first to learn the exact keys and allowed values. Colors are hex such as #FF69B4. Some settings need the user's approval and the user may decline; some can only be changed by the user. "
    "Changes in one set call are applied together or not at all. The processing bubble colors are the exception to palette changes: touch them only if the user names the bubble, alone in their own call. Tell the user what you changed."
)

_FULL_DESCRIPTION = """Look up and change Basil's own settings. Use it when the user asks you to change how Basil looks or behaves, for example "make your UI pink" or "make your text larger".

Actions:
- list: the settings you can see. Pass query to narrow by words, such as "color" or "text size". Each setting has a key, what it does, its tier, whether you can change it, its current value, and the allowed values when the choices are fixed.
- get: the same detail for specific keys. Pass keys.
- set: change one or more settings. Pass changes, a list of {key, value} items, and reason, a short plain sentence for the user explaining why. All changes in one call succeed or fail together, so send a whole palette in one call.
- undo: reverse your most recent change, or pass change_id for a specific one. It refuses if the setting has been changed since.
- overview: a short map of Basil's setting sections with how many settings in each you can change freely, with approval, or not at all, plus your other abilities and what only the user can do. Call it first when the user asks what you can control.
- show_in_settings: open the Settings window, on a tab when you pass tab (home, hotkeys, profile, memory-intelligence, writing-examples, models, reasoning, transcription, meetings, capture, connections, permissions, account, appearance). Use it when the user asks where a setting is or wants to change one that only they can change. It brings a window to the front, so use it only when asked.

Tiers: cosmetic changes apply at once and can be undone. Behavioral and privacy changes show the user an approval card and wait for the answer; the user may decline or not answer, and then nothing changes. Human-only settings, such as approvals, credentials and sign-ins, cannot be changed by you at all; tell the user where in Settings they can change them.

The processing bubble's colors are a status signal. Change them only when the user names the processing bubble; a request for a new palette, theme or color scheme does not include them. Send them in a call that changes nothing else.

Text and background colors must keep a contrast ratio of at least 4.5 to 1, or the whole call is rejected with an explanation. Colors are six-digit hex strings. Call list first so you use exact keys and allowed values, and after a change tell the user exactly what you changed and that it can be undone."""


class AppSettingsChange(BaseModel):
    key: str = Field(description="A setting key from list, such as appearance.primary_color.")
    value: Any = Field(description="The new value: a hex color string, a number, a true or false, or one of the allowed words.")


class AppSettingsInput(BaseModel):
    """Input schema for the app settings tool."""

    action: Literal["list", "get", "set", "undo", "show_in_settings", "overview"] = Field(description="list, get, set, undo, show_in_settings, or overview.")
    query: Optional[str] = Field(default=None, description="For list: words to search for in setting names and descriptions.")
    keys: Optional[List[str]] = Field(default=None, description="For get: the setting keys to read.")
    changes: Optional[List[AppSettingsChange]] = Field(default=None, description="For set: the changes to make together, at most 12.")
    reason: Optional[str] = Field(default=None, description="For set: a short plain sentence telling the user why you are changing this.")
    change_id: Optional[str] = Field(default=None, description="For undo: the change_id of a specific earlier change. Omit to undo the latest.")
    tab: Optional[str] = Field(default=None, description="For show_in_settings: the Settings tab to open. Omit to open Settings where it was.")


def _json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


async def _app_settings_impl(
    action: str,
    query: Optional[str] = None,
    keys: Optional[List[str]] = None,
    changes: Optional[List[Any]] = None,
    reason: Optional[str] = None,
    change_id: Optional[str] = None,
    tab: Optional[str] = None,
) -> str:
    engine = get_app_control_engine()
    try:
        if action == "overview":
            return _json(engine.overview())
        if action == "list":
            return _json(engine.list_entries(query or ""))
        if action == "get":
            if not keys:
                return _json({"ok": False, "error": "get needs keys, a list of setting keys. Use action list to find them."})
            return _json(engine.get_entries(list(keys)))
        if action == "set":
            context = get_current_agent_context()
            requested = [
                change.model_dump() if isinstance(change, BaseModel) else change
                for change in (changes or [])
            ]
            result = await engine.apply(
                requested,
                reason=(reason or "").strip(),
                agent_task_id=context.get("agent_task_id"),
                websocket_manager=context.get("websocket_manager"),
            )
            return _json(result)
        if action == "undo":
            return _json(await engine.undo(change_id))
        if action == "show_in_settings":
            outcome = await send_native_command("open_settings", {"tab": tab} if tab else {})
            if outcome.get("ok") and tab:
                outcome["tab_label"] = SETTINGS_TABS[tab]
            return _json(outcome)
    except Exception as exc:
        logger.error("app_settings %s failed: %s", action, exc, exc_info=True)
        return _json({"ok": False, "error": "The settings request failed unexpectedly, and nothing is known to have changed. Tell the user."})
    return _json({"ok": False, "error": "Unknown action. Use list, get, set, undo, show_in_settings, or overview."})


def create_app_settings_tool(profile=None) -> StructuredTool:
    """Build the LangChain StructuredTool for Basil's own settings."""
    return StructuredTool.from_function(
        func=_app_settings_impl,
        name=TOOL_NAME,
        description=select_description_for_profile(profile, _FULL_DESCRIPTION, SLIM_DESCRIPTION),
        args_schema=AppSettingsInput,
        coroutine=_app_settings_impl,
    )
