"""Plain-language labels and outcomes for tool steps in the run timeline."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from ..runtime.agent_timeline_contract import sanitize_timeline_title

EXTERNAL_CATALOG_TOOL_NAME = "external_catalog"


def _connection_name(connection_id: Any) -> Optional[str]:
    """The friendly name of a saved connection, or None when it cannot be resolved."""
    if not isinstance(connection_id, str) or not connection_id.strip():
        return None
    try:
        from ...tools.external_services.external_catalog.auth import (
            find_external_catalog_connection,
            load_external_catalog_preferences,
        )

        record = find_external_catalog_connection(load_external_catalog_preferences(), connection_id.strip())
    except Exception:
        return None
    name = getattr(record, "friendly_name", None) if record is not None else None
    return name.strip() if isinstance(name, str) and name.strip() else None


def describe_external_catalog_step(tool_inputs: Dict[str, Any]) -> Optional[str]:
    """Name the connection and the call, such as `Gmail: search_threads`, so a connection's use is visible in the timeline. Returns None for anything that is not a recognized external_catalog request."""
    action = tool_inputs.get("action") if isinstance(tool_inputs, dict) else None
    if action == "list_servers":
        return "Listing your connections"
    if action not in ("describe_server", "call_tool"):
        return None
    name = _connection_name(tool_inputs.get("connection_id")) or "a connection"
    if action == "describe_server":
        label = f"Reading the tools of {name}"
    else:
        called = tool_inputs.get("tool_name")
        called_text = called.strip() if isinstance(called, str) and called.strip() else "a tool"
        label = f"{name}: {called_text}"
    return sanitize_timeline_title(label, fallback="Using a connection")[:120]


def _parsed_output(output: Any) -> Any:
    """A tool's output as a dict when it is, or encodes, a JSON object; otherwise the text or the value unchanged."""
    content = getattr(output, "content", None)
    if content is not None and not isinstance(output, (str, dict)):
        output = content
    if isinstance(output, str):
        stripped = output.strip()
        if stripped.startswith("{"):
            try:
                return json.loads(stripped)
            except ValueError:
                return stripped
        return stripped
    return output


def tool_failure_reason(output: Any) -> Optional[str]:
    """A short reason when a tool's output reports its own failure (`ok` or `success` false), else None. A tool that returned normally is not an error to the agent framework, so this is what tells a failed call from a finished one."""
    parsed = _parsed_output(output)
    if not isinstance(parsed, dict):
        return None
    if parsed.get("ok") is not False and parsed.get("success") is not False:
        return None
    error = parsed.get("error")
    if isinstance(error, dict):
        error = error.get("message") or error.get("kind")
    if not error and isinstance(parsed.get("result"), dict):
        error = parsed["result"].get("error")
    text = str(error).strip() if error else ""
    return text[:300] if text else "The tool reported a failure."
