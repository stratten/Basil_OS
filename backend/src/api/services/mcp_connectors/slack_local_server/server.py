"""Tool registry plus public ``list_tools`` / ``call_tool`` entry points.

The dispatcher in :mod:`api.services.mcp_connectors.mcp_client_service`
imports ``LOCAL_SLACK_SENTINEL_URL``, ``list_tools``, and ``call_tool``
from this module (re-exported via the package ``__init__``). Both
entry points are stateless and accept the access token directly so
this server can be invoked from any task without ambient state.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from ..error_normalizer import (
    ERROR_KIND_AUTH_EXPIRED,
    ERROR_KIND_INVALID_ARGUMENTS,
    ERROR_KIND_NOT_FOUND,
    ERROR_KIND_SERVER_ERROR,
    make_envelope,
    make_success,
)
from . import handlers, schemas
from .error_mapping import normalize_slack_api_error

logger = logging.getLogger(__name__)


LOCAL_SLACK_SENTINEL_URL = "basil-local://slack"
"""Connection ``server_url`` value that routes a connection to this
package instead of the streamable-HTTP transport. Persisted by
``slack_routes._persist_slack_connection`` and matched by
``MCPClientService`` in its dispatch branching."""

_LOCAL_SERVER_NAME = "basil-local-slack"
_LOCAL_SERVER_VERSION = "0.1.0"
_LOCAL_PROTOCOL_VERSION = "2024-11-05"

_SLACK_API_TIMEOUT_SECONDS = 30.0
"""Per-call HTTP deadline for Slack Web API requests. Mirrors the
default in ``MCPClientService`` so a local call cannot exceed the
budget the agent expects of an MCP dispatch."""


@dataclass(frozen=True)
class _ToolDescriptor:
    """Static description of one Slack tool exposed to the agent.

    Kept frozen and module-level because the registry is fixed at
    import time. The agent does not see this dataclass; it sees the
    serialized form returned by :func:`list_tools`.
    """

    name: str
    description: str
    is_read_only_hint: bool
    input_model: Type[BaseModel]
    handler: Callable[[AsyncWebClient, dict], Awaitable[dict]]


_TOOL_REGISTRY: List[_ToolDescriptor] = [
    _ToolDescriptor(
        name="slack_search_messages",
        description=(
            "Search messages across Slack channels and DMs the user can see. "
            "Supports operators like 'from:@user', 'in:#channel', "
            "'after:YYYY-MM-DD'."
        ),
        is_read_only_hint=True,
        input_model=schemas.SearchMessagesInput,
        handler=handlers.handle_search_messages,
    ),
    _ToolDescriptor(
        name="slack_search_files",
        description=(
            "Search files shared in Slack the user can see. Supports filtering "
            "by type (e.g. 'type:pdf')."
        ),
        is_read_only_hint=True,
        input_model=schemas.SearchFilesInput,
        handler=handlers.handle_search_files,
    ),
    _ToolDescriptor(
        name="slack_list_channels",
        description="List channels the user is a member of, with id, name, and visibility.",
        is_read_only_hint=True,
        input_model=schemas.ListChannelsInput,
        handler=handlers.handle_list_channels,
    ),
    _ToolDescriptor(
        name="slack_read_channel_history",
        description="Read recent messages from a specific channel, optionally bounded by timestamp.",
        is_read_only_hint=True,
        input_model=schemas.ReadChannelHistoryInput,
        handler=handlers.handle_read_channel_history,
    ),
    _ToolDescriptor(
        name="slack_read_thread",
        description="Read every message in a specific message thread, including the parent.",
        is_read_only_hint=True,
        input_model=schemas.ReadThreadInput,
        handler=handlers.handle_read_thread,
    ),
    _ToolDescriptor(
        name="slack_create_channel",
        description="Create a new public or private channel.",
        is_read_only_hint=False,
        input_model=schemas.CreateChannelInput,
        handler=handlers.handle_create_channel,
    ),
    _ToolDescriptor(
        name="slack_send_message",
        description=(
            "Post a Slack message to a channel, DM, or thread on the user's "
            "behalf. To 'draft' a Slack reply, write the proposed text in your "
            "visible response so the user can review it, then call this tool "
            "with the same text to send. Sending requires user approval each "
            "time, so the user can edit or cancel before anything is posted."
        ),
        is_read_only_hint=False,
        input_model=schemas.SendMessageInput,
        handler=handlers.handle_send_message,
    ),
    _ToolDescriptor(
        name="slack_open_dm",
        description="Open or retrieve a direct-message channel with one Slack user. Write-capable because Slack may create a DM conversation.",
        is_read_only_hint=False,
        input_model=schemas.OpenDMInput,
        handler=handlers.handle_open_dm,
    ),
    _ToolDescriptor(
        name="slack_open_group_dm",
        description="Open or retrieve a group-DM channel for multiple Slack users. Write-capable because Slack may create a group conversation.",
        is_read_only_hint=False,
        input_model=schemas.OpenGroupDMInput,
        handler=handlers.handle_open_group_dm,
    ),
    _ToolDescriptor(
        name="slack_add_reaction",
        description="Add an emoji reaction to a message.",
        is_read_only_hint=False,
        input_model=schemas.AddReactionInput,
        handler=handlers.handle_add_reaction,
    ),
    _ToolDescriptor(
        name="slack_create_canvas",
        description="Create a Slack canvas with Markdown content, optionally attached to a channel.",
        is_read_only_hint=False,
        input_model=schemas.CreateCanvasInput,
        handler=handlers.handle_create_canvas,
    ),
    _ToolDescriptor(
        name="slack_read_canvas",
        description="Read a Slack canvas's content by canvas/file id.",
        is_read_only_hint=True,
        input_model=schemas.ReadCanvasInput,
        handler=handlers.handle_read_canvas,
    ),
    _ToolDescriptor(
        name="slack_list_users",
        description="List active users in the workspace with id, handle, and display name.",
        is_read_only_hint=True,
        input_model=schemas.ListUsersInput,
        handler=handlers.handle_list_users,
    ),
    _ToolDescriptor(
        name="slack_get_workspace_info",
        description="Fetch Slack workspace metadata through team.info, including id, name, and domain.",
        is_read_only_hint=True,
        input_model=schemas.GetWorkspaceInfoInput,
        handler=handlers.handle_get_workspace_info,
    ),
    _ToolDescriptor(
        name="slack_list_emoji",
        description="List custom Slack emoji visible to the user through emoji.list, with alias markers.",
        is_read_only_hint=True,
        input_model=schemas.ListEmojiInput,
        handler=handlers.handle_list_emoji,
    ),
    _ToolDescriptor(
        name="slack_get_message_reactions",
        description="Read emoji reactions for a specific Slack message through reactions.get.",
        is_read_only_hint=True,
        input_model=schemas.GetMessageReactionsInput,
        handler=handlers.handle_get_message_reactions,
    ),
    _ToolDescriptor(
        name="slack_get_user_profile",
        description=(
            "Fetch a single user's profile through users.info, including "
            "name, title, status, and email when users:read.email is granted. "
            "Custom profile field labels are not returned by this fallback."
        ),
        is_read_only_hint=True,
        input_model=schemas.GetUserProfileInput,
        handler=handlers.handle_get_user_profile,
    ),
    _ToolDescriptor(
        name="slack_list_unread_messages",
        description=(
            "List unread messages found in a bounded scan of the user's Slack "
            "channels, DMs, and group DMs. Walks recent conversations in "
            "users.conversations order, checks Slack read cursors, and uses "
            "conversations.history(oldest=last_read, inclusive=false) to "
            "retrieve messages after the user's last-read cursor. A no-result "
            "response means none were found in the scanned conversations, not "
            "an all-workspace guarantee. Local to Basil's embedded Slack "
            "server, not available on the hosted mcp.slack.com server."
        ),
        is_read_only_hint=True,
        input_model=schemas.ListUnreadMessagesInput,
        handler=handlers.handle_list_unread_messages,
    ),
    _ToolDescriptor(
        name="slack_scan_unread_messages",
        description=(
            "Stage through unread Slack messages with explicit cursor continuation. "
            "Scans one users.conversations page, checks each conversation's "
            "last_read cursor, and returns next_cursor/is_complete so the agent "
            "can say whether the result is partial or complete. Use this when "
            "the user asks for a deeper unread scan than slack_list_unread_messages."
        ),
        is_read_only_hint=True,
        input_model=schemas.ScanUnreadMessagesInput,
        handler=handlers.handle_scan_unread_messages,
    ),
]


def _find_tool(name: str) -> Optional[_ToolDescriptor]:
    for t in _TOOL_REGISTRY:
        if t.name == name:
            return t
    return None


async def list_tools(*, access_token: Optional[str] = None) -> Dict[str, Any]:
    """Return the catalog payload that ``MCPClientService.list_tools`` produces.

    ``access_token`` is currently unused — the catalog is static — but
    the parameter is kept so the dispatcher can call this function
    with the same signature it would use against a remote server later
    if any future tool gates its visibility on scope.
    """
    return {
        "server": {
            "name": _LOCAL_SERVER_NAME,
            "version": _LOCAL_SERVER_VERSION,
            "protocol": _LOCAL_PROTOCOL_VERSION,
        },
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_model.model_json_schema(),
                "is_read_only_hint": t.is_read_only_hint,
            }
            for t in _TOOL_REGISTRY
        ],
    }


async def call_tool(
    *,
    tool_name: str,
    arguments: Optional[Dict[str, Any]],
    access_token: Optional[str],
) -> Dict[str, Any]:
    """Dispatch one tool invocation. Returns a fully-normalized envelope.

    On success: ``make_success({"text": ..., "structured": ...})``.
    On any failure (validation, Slack API, transport, programming): an
    error envelope produced via :mod:`error_normalizer`.

    Tokens are passed in directly rather than read from an instance
    field so this module is completely stateless. A missing token is
    classified as ``auth_expired`` so the agent surfaces it the same
    way it surfaces an expired remote token.
    """
    if not access_token:
        return make_envelope(
            kind=ERROR_KIND_AUTH_EXPIRED,
            message="Slack connection has no access token. Reconnect Slack in Settings.",
            retryable=False,
            user_action_required="Reconnect this server in Settings → Connections.",
        )

    descriptor = _find_tool(tool_name)
    if descriptor is None:
        return make_envelope(
            kind=ERROR_KIND_NOT_FOUND,
            message=f"No such Slack tool: {tool_name!r}.",
            retryable=False,
            raw={"available_tools": [t.name for t in _TOOL_REGISTRY]},
        )

    client = AsyncWebClient(token=access_token, timeout=_SLACK_API_TIMEOUT_SECONDS)
    try:
        shaped = await descriptor.handler(client, arguments or {})
    except ValidationError as exc:
        return make_envelope(
            kind=ERROR_KIND_INVALID_ARGUMENTS,
            message=f"Invalid arguments for {tool_name}: {exc.errors()}",
            retryable=False,
            raw={"errors": exc.errors()},
        )
    except SlackApiError as exc:
        return normalize_slack_api_error(exc, tool_name=tool_name)
    except Exception as exc:
        logger.exception("Unhandled exception in slack_local_server.%s", tool_name)
        return make_envelope(
            kind=ERROR_KIND_SERVER_ERROR,
            message=f"Local Slack tool {tool_name} failed: {type(exc).__name__}: {exc}",
            retryable=False,
            raw={"exc_type": type(exc).__name__},
        )

    return make_success(shaped)


__all__ = [
    "LOCAL_SLACK_SENTINEL_URL",
    "call_tool",
    "list_tools",
]
