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
from .external_catalog.connect import connect_external_catalog_server as _connect_server
from .external_catalog.token_connect import connect_external_catalog_server_with_token as _connect_with_token
from .external_catalog.local_server_recipe_actions import local_server_status_action as _local_server_status
from .external_catalog.local_server_register import register_external_catalog_local_server as _register_local_server
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
from ..internal_basil_tools.stored_result.spill import spill_result
from .external_catalog.output_cap import cap_external_catalog_result
from .external_catalog.rate_limits import try_rate_limit_wait_and_retry as _try_rate_limit_wait_and_retry

logger = logging.getLogger(__name__)


CATALOG_TOOL_NAME = "external_catalog"

ACTION_LIST = "list_servers"
ACTION_DESCRIBE = "describe_server"
ACTION_CALL = "call_tool"
ACTION_CONNECT = "connect_server"
ACTION_CONNECT_WITH_TOKEN = "connect_with_token"
ACTION_REGISTER_LOCAL_SERVER = "register_local_server"
ACTION_LOCAL_SERVER_STATUS = "local_server_status"


class ExternalCatalogInput(BaseModel):
    """Single input schema for all three actions.

    The agent picks ``action`` and supplies whichever subset of the
    other fields that action needs. Validation of "required for this
    action" happens in the implementation rather than the schema so
    the model can correct itself from a clear error rather than a
    Pydantic stack trace.
    """
    action: Literal["list_servers", "describe_server", "call_tool", "connect_server", "connect_with_token", "register_local_server", "local_server_status"] = Field(
        description=(
            "Which catalog operation to perform: "
            f"'{ACTION_LIST}' (no other fields), "
            f"'{ACTION_DESCRIBE}' (requires connection_id), "
            f"'{ACTION_CALL}' (requires connection_id, tool_name, arguments), "
            f"'{ACTION_CONNECT}' (requires server_url; optional friendly_name), "
            f"'{ACTION_CONNECT_WITH_TOKEN}' (requires server_url; optional friendly_name; shows an overlay in Paprika where the user types the service's token and can edit the connection's name and description; optional description), "
            f"'{ACTION_REGISTER_LOCAL_SERVER}' (requires friendly_name and arguments with command, args, cwd, env, secret_env, source_url, companion; sets up a program on this Mac as a server after the user approves it; name credentials in secret_env, never put their values in arguments; install is an optional recipe of programs to install and files to download or build, replace is the connection_id of a local server to rewrite), "
            f"'{ACTION_LOCAL_SERVER_STATUS}' (requires connection_id; reports a local server's setup step, whether its background program needs the user, and recent output)."
        )
    )
    connection_id: Optional[str] = Field(
        default=None,
        description="Connection id from list_servers; required for describe_server, call_tool and local_server_status."
    )
    tool_name: Optional[str] = Field(
        default=None,
        description="Name of the tool to invoke; required for call_tool."
    )
    arguments: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "JSON object of arguments to pass to the tool; required for call_tool. "
            "For register_local_server it is the server definition: command (the program), args (a list, one item per argument), cwd (absolute folder), env (non-secret settings only), "
            "secret_env (credential variable names, never values), source_url, companion (a background program the server needs running first, optionally with a probe that reads its status page), install (a recipe) and replace (a connection_id)."
        )
    )
    purpose: Optional[str] = Field(
        default=None,
        description=(
            "call_tool: one or two plain sentences telling the user what this call does and why, shown on the approval card. "
            "Include it on every call to a tool that needs the user's approval. It goes beside arguments, never inside them, and is not sent to the service."
        ),
    )
    server_url: Optional[str] = Field(
        default=None,
        description=(
            "connect_server and connect_with_token: the exact https MCP server address the user gave you. "
            "Never guess or reconstruct an address; ask the user to paste it."
        ),
    )
    friendly_name: Optional[str] = Field(
        default=None,
        description="connect_server and connect_with_token: optional display name for the service, such as 'Notion'. For connect_with_token it is only a suggestion the user can change in the overlay. register_local_server: required, a short name for the server.",
    )
    description: Optional[str] = Field(
        default=None,
        description="connect_with_token and register_local_server: optional one-line note about what this connection is for, such as 'Work account, read and write'. For connect_with_token it is only a suggestion the user can change in the overlay.",
    )


def create_external_catalog_tool(profile=None, max_output_chars: Optional[int] = None) -> StructuredTool:
    """Build the LangChain StructuredTool wrapping the catalog dispatcher.

    Under a slim rendering profile the description is swapped to the
    hand-authored ``SLIM_DESCRIPTION`` companion above; otherwise the
    full description (with the dynamic CURRENT CONNECTIONS inventory)
    flows through unchanged.
    """
    connection_inventory = _format_connection_inventory_for_description()
    full_description = build_full_external_catalog_description(connection_inventory)
    description = select_description_for_profile(profile, full_description, SLIM_DESCRIPTION)

    # A result over max_output_chars (the limit the service tools use, or a default) is saved whole and replaced by a preview, an outline, and a result_id for the stored_result tool, so one oversized connector response cannot fill the model's context window. If it cannot be saved it is clipped instead.
    async def _capped_external_catalog(
        action: str,
        connection_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
        server_url: Optional[str] = None,
        friendly_name: Optional[str] = None,
        description: Optional[str] = None,
        purpose: Optional[str] = None,
    ) -> str:
        encoded = await _external_catalog_impl(
            action=action,
            connection_id=connection_id,
            tool_name=tool_name,
            arguments=arguments,
            server_url=server_url,
            friendly_name=friendly_name,
            description=description,
            purpose=purpose,
        )
        capped = cap_external_catalog_result(encoded, max_output_chars, spill=spill_result)
        if capped is not encoded:
            logger.warning(
                "external_catalog result clipped from %s to %s characters (action=%s, tool=%s)",
                f"{len(encoded):,}", f"{len(capped):,}", action, tool_name,
            )
        return capped

    return StructuredTool.from_function(
        func=_capped_external_catalog,
        name=CATALOG_TOOL_NAME,
        description=description,
        args_schema=ExternalCatalogInput,
        coroutine=_capped_external_catalog,
    )


_NESTED_ENVELOPE_FIELDS = ("connection_id", "tool_name")
_NESTED_ENVELOPE_EXTRA_KEYS = ("server_url", "action")


def _hoist_nested_envelope_fields(
    connection_id: Optional[str],
    tool_name: Optional[str],
    arguments: Optional[Dict[str, Any]],
) -> tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
    """Recover a call whose envelope fields were nested inside ``arguments``.

    Small models sometimes put ``connection_id`` and ``tool_name`` (and ``server_url``) inside ``arguments`` instead of beside it. A missing top-level field is filled from a non-empty string in ``arguments``, the keys that were moved are removed, and ``server_url``/``action`` are dropped with them, since they belong to the envelope and no remote tool takes them in this shape. An inner ``arguments`` object is unwrapped as the real arguments. Nothing changes when both fields are already present at the top level, so a remote tool with a parameter of the same name is untouched.
    """

    if not isinstance(arguments, dict):
        return connection_id, tool_name, arguments
    if connection_id and tool_name:
        return connection_id, tool_name, arguments

    resolved = {"connection_id": connection_id, "tool_name": tool_name}
    moved: list[str] = []
    for field_name in _NESTED_ENVELOPE_FIELDS:
        nested_value = arguments.get(field_name)
        if not resolved[field_name] and isinstance(nested_value, str) and nested_value.strip():
            resolved[field_name] = nested_value.strip()
            moved.append(field_name)
    if not moved:
        return connection_id, tool_name, arguments

    remaining = {
        key: value
        for key, value in arguments.items()
        if key not in moved and key not in _NESTED_ENVELOPE_EXTRA_KEYS
    }
    inner_arguments = remaining.get("arguments")
    if isinstance(inner_arguments, dict) and len(remaining) == 1:
        remaining = inner_arguments
    logger.info("external_catalog: recovered %s nested inside arguments", ",".join(moved))
    return resolved["connection_id"], resolved["tool_name"], remaining


async def _external_catalog_impl(
    action: str,
    connection_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    arguments: Optional[Dict[str, Any]] = None,
    server_url: Optional[str] = None,
    friendly_name: Optional[str] = None,
    description: Optional[str] = None,
    purpose: Optional[str] = None,
) -> str:
    """Dispatch the catalog action and return a JSON-encoded envelope.

    LangChain renders tool returns as strings into the agent's
    transcript, so we encode the structured envelope as JSON. Logging
    at INFO captures every dispatch for ops visibility; failures log
    at WARNING with the envelope kind so SRE-style triage is easy.
    """
    try:
        if action in (ACTION_DESCRIBE, ACTION_CALL):
            connection_id, tool_name, arguments = _hoist_nested_envelope_fields(
                connection_id, tool_name, arguments
            )
        if action == ACTION_LIST:
            return _encode(await _list_servers())
        if action == ACTION_DESCRIBE:
            if not connection_id:
                return _encode(_envelope_invalid("describe_server requires connection_id"))
            return _encode(await _describe_server(connection_id))
        if action == ACTION_CALL:
            if not (connection_id and tool_name):
                return _encode(_envelope_invalid("call_tool requires connection_id and tool_name"))
            return _encode(await _call_tool(connection_id, tool_name, arguments or {}, purpose=purpose))
        if action == ACTION_CONNECT:
            return _encode(await _connect_server(server_url, friendly_name))
        if action == ACTION_CONNECT_WITH_TOKEN:
            return _encode(await _connect_with_token(server_url, friendly_name, description))
        if action == ACTION_REGISTER_LOCAL_SERVER:
            return _encode(await _register_local_server(arguments, friendly_name, description))
        if action == ACTION_LOCAL_SERVER_STATUS:
            return _encode(await _local_server_status(connection_id))
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


