"""Remembering an approval for one connected (MCP) tool.

A connected-tool call cannot be remembered as a command pattern (see ``whitelist_eligibility``), so the card's remember choice instead sets that one tool's policy on that one connection to ``always_allow``. The policy is the same setting Settings → Connections shows, so the choice is visible and reversible there.

The scope travels in the approval's presentation fields (``whitelist.tool_policy``), which the backend builds and persists in the approval's ``render_context``. The decision route reads it back from the durable record, never from the request.
"""

import re
from typing import Any, Dict, Mapping, Optional

# Words in a tool name that mean the call removes data or sends something out of Basil's reach. Matching is on whole words of the name, so ``untrash_message`` (which restores) is not caught by ``trash``.
_DESTRUCTIVE_WORDS = frozenset({
    "delete", "remove", "trash", "destroy", "purge", "erase", "drop", "wipe", "truncate", "revoke",
    "send", "publish", "post",
})

_NAME_WORD_BOUNDARY = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")

ALWAYS_ALLOW = "always_allow"
NEVER_ALLOW = "never_allow"


def is_destructive_tool_name(tool_name: str) -> bool:
    """True when a word of the tool's name says it deletes data or sends something out, such as ``trash_thread`` or ``send_message``."""
    words = {word.lower() for word in _NAME_WORD_BOUNDARY.split(tool_name or "") if word}
    return bool(words & _DESTRUCTIVE_WORDS)


def build_tool_policy_scope(
    connection_id: str,
    connection_name: str,
    tool_name: str,
    server_marked_destructive: bool = False,
) -> Dict[str, Any]:
    """The remember scope the approval context carries for one connected-tool call.

    A tool counts as destructive when its name says so or when its server declared it destructive.
    """
    return {
        "connection_id": connection_id,
        "connection_name": connection_name,
        "tool_name": tool_name,
        "destructive": server_marked_destructive or is_destructive_tool_name(tool_name),
    }


def server_marks_tool_destructive(record: Any, tool_name: str) -> bool:
    """True when the connection's cached catalog says its server declared ``tool_name`` destructive.

    Only an explicit ``destructiveHint`` of True counts, and a tool the server also marks read-only never does, since those two hints would contradict each other. An unknown tool, or a server that declared nothing, is False.
    """
    for tool in getattr(record, "cached_tools", None) or []:
        if getattr(tool, "name", None) == tool_name:
            return getattr(tool, "is_destructive_hint", None) is True and not getattr(tool, "is_read_only_hint", False)
    return False


def normalize_tool_policy_scope(raw: Any) -> Optional[Dict[str, Any]]:
    """Return a well-formed scope, or None when ``raw`` is not one. The id and tool name are required."""
    if not isinstance(raw, Mapping):
        return None
    connection_id = raw.get("connection_id")
    tool_name = raw.get("tool_name")
    if not isinstance(connection_id, str) or not connection_id.strip():
        return None
    if not isinstance(tool_name, str) or not tool_name.strip():
        return None
    connection_name = raw.get("connection_name")
    return {
        "connection_id": connection_id.strip(),
        "connection_name": connection_name.strip() if isinstance(connection_name, str) else "",
        "tool_name": tool_name.strip(),
        "destructive": raw.get("destructive") is True,
    }


def tool_policy_scope_of_record(record: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The remember scope a persisted approval was shown with, or None for an ordinary approval."""
    render_context = record.get("render_context")
    if not isinstance(render_context, Mapping):
        return None
    whitelist = render_context.get("whitelist")
    if not isinstance(whitelist, Mapping):
        return None
    return normalize_tool_policy_scope(whitelist.get("tool_policy"))


def remember_always_allow(scope: Mapping[str, Any]) -> str:
    """Set the scoped tool's policy to ``always_allow`` and return a message for the user.

    Raises ``ValueError`` with a plain-language reason when the connection is gone or the tool is set to Never allow, so the caller can approve this one call and say why nothing was remembered.
    """
    from api.core.preferences.preferences_io import load_preferences, save_preferences

    prefs = load_preferences()
    record = next((item for item in prefs.connections.mcp_connections if item.id == scope["connection_id"]), None)
    if record is None:
        raise ValueError("That connection no longer exists, so there is nothing to remember it for.")
    tool_name = str(scope["tool_name"])
    if record.tool_policies.get(tool_name) == NEVER_ALLOW:
        raise ValueError("This tool is set to Never allow in Settings → Connections, so Basil did not change it.")
    record.tool_policies[tool_name] = ALWAYS_ALLOW
    save_preferences(prefs)
    return f"Approved. Basil will no longer ask before {tool_name} runs on {record.friendly_name}. You can change this in Settings → Connections."
