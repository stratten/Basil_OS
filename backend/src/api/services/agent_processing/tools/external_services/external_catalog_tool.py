"""External MCP catalog tool — single agent surface for all remote connectors.

This is intentionally one tool, not N. Each registered remote MCP
server (Linear, GitHub, anything the user adds) exposes its own tool
catalog, but the agent is given a single LangChain tool, the
``external_catalog``, that can:

  * ``list_servers``   — enumerate the user's connections.
  * ``describe_server``— ask one server for its current tool catalog.
  * ``call_tool``      — invoke a tool on one server.

The point of the single-tool design is context-window discipline.
If we instead exposed every remote MCP tool individually, the agent's
prompt would balloon as users add connections, and tool-selection
quality would degrade. The discover-then-call pattern keeps the
prompt size constant while still giving the agent unbounded reach
into whatever the user has connected.

Per-tool approval policy is read from preferences at dispatch time:

  * ``always_allow``  — proceed; record success/failure in audit log.
  * ``always_ask``    — ask the user via ExecutionApprovalService; on
                        approval, proceed; on denial, return a
                        ``permission_denied`` envelope.
  * ``never_allow``   — return ``permission_denied`` without asking.
  * (missing key)     — falls back to ``always_ask`` for safety.

Every dispatch — successful, failed, denied, or skipped — produces
one row in ``mcp_call_log`` so the user has a complete audit trail.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile
from .external_catalog.actions import (
    call_external_catalog_tool as _call_tool,
    describe_external_catalog_server as _describe_server,
    list_external_catalog_servers as _list_servers,
)
from .external_catalog.approval import request_external_catalog_user_approval as _request_user_approval
from .external_catalog.descriptions import (
    SLIM_DESCRIPTION,
    build_full_external_catalog_description,
    format_connection_inventory_for_description as _format_connection_inventory_for_description,
)
from .external_catalog.envelopes import (
    encode_external_catalog_envelope as _encode,
    make_external_catalog_auth_unavailable as _make_auth_unavailable,
    make_external_catalog_invalid_arguments as _envelope_invalid,
    make_external_catalog_not_found as _envelope_not_found,
    make_external_catalog_permission_denied as _make_permission_denied,
)
from .external_catalog.rate_limits import try_rate_limit_wait_and_retry as _try_rate_limit_wait_and_retry

logger = logging.getLogger(__name__)


CATALOG_TOOL_NAME = "external_catalog"

ACTION_LIST = "list_servers"
ACTION_DESCRIBE = "describe_server"
ACTION_CALL = "call_tool"


class ExternalCatalogInput(BaseModel):
    """Single input schema for all three actions.

    The agent picks ``action`` and supplies whichever subset of the
    other fields that action needs. Validation of "required for this
    action" happens in the implementation rather than the schema so
    the model can correct itself from a clear error rather than a
    Pydantic stack trace.
    """
    action: Literal["list_servers", "describe_server", "call_tool"] = Field(
        description=(
            "Which catalog operation to perform: "
            f"'{ACTION_LIST}' (no other fields), "
            f"'{ACTION_DESCRIBE}' (requires connection_id), "
            f"'{ACTION_CALL}' (requires connection_id, tool_name, arguments)."
        )
    )
    connection_id: Optional[str] = Field(
        default=None,
        description="Connection id from list_servers; required for describe_server and call_tool."
    )
    tool_name: Optional[str] = Field(
        default=None,
        description="Name of the tool to invoke; required for call_tool."
    )
    arguments: Optional[Dict[str, Any]] = Field(
        default=None,
        description="JSON object of arguments to pass to the tool; required for call_tool."
    )


def create_external_catalog_tool(profile=None) -> StructuredTool:
    """Build the LangChain StructuredTool wrapping the catalog dispatcher.

    Under a slim rendering profile the description is swapped to the
    hand-authored ``SLIM_DESCRIPTION`` companion above; otherwise the
    full description (with the dynamic CURRENT CONNECTIONS inventory)
    flows through unchanged.
    """
    connection_inventory = _format_connection_inventory_for_description()
    full_description = build_full_external_catalog_description(connection_inventory)
    description = select_description_for_profile(profile, full_description, SLIM_DESCRIPTION)

    return StructuredTool.from_function(
        func=_external_catalog_impl,
        name=CATALOG_TOOL_NAME,
        description=description,
        args_schema=ExternalCatalogInput,
        coroutine=_external_catalog_impl,
    )


async def _external_catalog_impl(
    action: str,
    connection_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    arguments: Optional[Dict[str, Any]] = None,
) -> str:
    """Dispatch the catalog action and return a JSON-encoded envelope.

    LangChain renders tool returns as strings into the agent's
    transcript, so we encode the structured envelope as JSON. Logging
    at INFO captures every dispatch for ops visibility; failures log
    at WARNING with the envelope kind so SRE-style triage is easy.
    """
    try:
        if action == ACTION_LIST:
            return _encode(await _list_servers())
        if action == ACTION_DESCRIBE:
            if not connection_id:
                return _encode(_envelope_invalid("describe_server requires connection_id"))
            return _encode(await _describe_server(connection_id))
        if action == ACTION_CALL:
            if not (connection_id and tool_name):
                return _encode(_envelope_invalid("call_tool requires connection_id and tool_name"))
            return _encode(await _call_tool(connection_id, tool_name, arguments or {}))
        return _encode(_envelope_invalid(f"Unknown action '{action}'"))
    except Exception as exc:
        logger.exception("external_catalog dispatch crashed")
        return _encode({
            "ok": False,
            "error": {
                "kind": "unknown",
                "message": f"external_catalog crashed: {type(exc).__name__}: {exc}",
                "retryable": False,
                "user_action_required": None,
                "raw": {},
            },
        })


