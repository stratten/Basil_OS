"""Compact tool index for the staged-loader tool's description.

The index lists every tool that is not bound from the first step, grouped by family, with each tool's required arguments and the allowed values of any required enumeration.
A model that can see the exact tool names and their required arguments calls the right tool directly, so the loader no longer has to be a separate step.
In a replay of the 23 routing cases on Qwen3-8B this index, together with call-through loading, passed 44 of 46 runs against 26 of 46 for the family catalog, with no first-try argument errors.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

from .tool_family_catalog import (
    CONNECTED_SERVICE_ROUTING_RULE,
    describe_tool_families,
    get_family_definitions,
    select_tools_for_families,
)

TOOL_INDEX_INTRO = (
    "Tool index. Your current tool list holds the always-available tools. Every other tool is listed below by family. "
    "Call any of them directly by name with your best arguments: Basil loads the tool's family and runs the call, and the family's exact schemas are in your tool list from your next step, so you can correct an argument and retry. "
    "Call load_tool_family only when you want to read the full schemas of a family before using it. "
    "Each tool lists its required arguments in parentheses; a value such as action=list|get means choose exactly one of those values."
)


# A connection is a mailbox when its routing label names mail (Gmail, Fastmail, Outlook Mail) or Outlook; the label is connection metadata, not the user's request.
MAIL_CONNECTION_PATTERN = re.compile(r"mail|outlook", re.IGNORECASE)
CONNECTED_MAIL_ENTRY_NAME = "connected mail"
CONNECTED_MAIL_SCOPE = "Gmail and other mailboxes you have connected"
CONNECTED_MAIL_TOOLS = "external_catalog(action=list_servers|describe_server|call_tool)"


def render_connected_mail_entry(connected_services: Sequence[str], all_tools: Sequence[Any]) -> str:
    """One index line that gives an enabled mail connection the same standing as the local email family, or an empty string.

    A small local model picks by tool name and by the index's wording, so a mailbox that is reachable only through the generic external_catalog tool needs its own entry that says email.
    The line is empty when no enabled connection is a mailbox or when external_catalog is not registered, so it never advertises a tool the model cannot call.
    """
    labels = [label for label in connected_services if MAIL_CONNECTION_PATTERN.search(label)]
    if not labels or not any(getattr(tool, "name", "") == "external_catalog" for tool in all_tools):
        return ""
    return f"- {CONNECTED_MAIL_ENTRY_NAME} ({CONNECTED_MAIL_SCOPE}: {'; '.join(labels)}): to search or read email in any of these accounts, call external_catalog(action=list_servers|describe_server|call_tool). Tools: {CONNECTED_MAIL_TOOLS}"


def tool_signature(tool: Any) -> str:
    """The tool name with its required arguments, and the allowed values of any required argument that is an enumeration."""
    schema_class = getattr(tool, "args_schema", None)
    try:
        schema = schema_class.model_json_schema() if hasattr(schema_class, "model_json_schema") else {}
    except Exception:
        schema = {}
    properties = schema.get("properties", {})
    parts: list[str] = []
    for key in schema.get("required", []):
        spec = properties.get(key, {})
        values = spec.get("enum") or [option["const"] for option in spec.get("anyOf", []) if "const" in option]
        parts.append(f"{key}={'|'.join(str(value) for value in values)}" if values else key)
    return f"{tool.name}({', '.join(parts)})"


def render_tool_index(all_tools: Sequence[Any], exclude_names: Iterable[str] = ()) -> str:
    """Render the intro and one line per family that owns at least one registered tool.

    Families named in ``exclude_names`` are left out because their tools are already bound from the first step.
    """
    excluded = {str(name).strip().lower() for name in exclude_names if str(name).strip()}
    lines = [TOOL_INDEX_INTRO]
    external = next((item for item in describe_tool_families() if item["name"] == "external"), {})
    connected_services = external.get("connected_services") or []
    if connected_services and "external" not in excluded:
        lines.append(f"Currently enabled external services: {', '.join(connected_services)}. {CONNECTED_SERVICE_ROUTING_RULE}")
    mail_entry = "" if "external" in excluded else render_connected_mail_entry(connected_services, all_tools)
    if mail_entry:
        lines.append(mail_entry)
    for family in get_family_definitions():
        if family.name in excluded:
            continue
        owned = select_tools_for_families(all_tools, [family.name], include_core_tools=False)
        if not owned:
            continue
        note = f" {family.index_note}" if family.index_note else ""
        lines.append(f"- {family.name}: {family.purpose} Tools: {', '.join(tool_signature(tool) for tool in owned)}{note}")
    return "\n".join(lines)
