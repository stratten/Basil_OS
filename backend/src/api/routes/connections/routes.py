"""HTTP surface for managing remote MCP connections.

This router is the contract between the SwiftUI Connections settings
tab and the Python connector layer. It owns:

  * CRUD over the user's persisted ``ConnectionsSettings``
    (``preferences.connections.mcp_connections``).
  * Driving the OAuth coordinator: starting a flow, handling the
    redirect from the authorization server, and notifying the Swift
    client over the WebSocket bridge so it can write the access
    token to Keychain.
  * Surfacing the live tool catalog via ``MCPClientService.list_tools``
    so the UI can show the user what they just authorized.
  * Exposing the audit log so the user can see every external tool
    call routed through Basil on their behalf.

The router does NOT own:

  * Token storage — the Swift Keychain owns that. We push tokens to
    the Swift client over the WebSocket; we never persist them to
    disk on the Python side.
  * Approval policy execution — the ``external_catalog`` agent tool
    reads policy from preferences at dispatch time and invokes the
    ``ExecutionApprovalService`` if needed.
  * MCP protocol semantics — ``MCPClientService`` and
    ``OAuthCoordinator`` own those.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.models.preferences import (
    MCPCachedTool,
    MCPConnectionRecord,
)
from api.dependencies import get_sqlite_knowledge_service
from api.services.mcp_connectors.connection_status_service import STATUS_HEALTHY
from api.services.mcp_connectors.github_device_flow_coordinator import (
    GITHUB_MCP_SCOPES,
    GITHUB_OAUTH_CLIENT_ID,
    GitHubDeviceFlowCoordinator,
    GitHubDeviceFlowError,
)
from api.services.mcp_connectors.mcp_client_service import MCPClientService
from api.services.mcp_connectors.oauth_coordinator import (
    OAuthCoordinator,
    OAuthCoordinatorError,
)
from api.services.agent_processing.tools.external_services.external_connection_capability import (
    apply_server_metadata_to_record,
)
from api.services.mcp_connectors.swift_token_bridge import (
    _push_token_delete_to_swift,
    _push_token_to_swift,
    _request_access_token_from_swift,
)
from .models import (
    STARTER_SERVERS,
    CallLogEntry,
    CallLogResponse,
    ConnectionDTO,
    ConnectionsListResponse,
    GitHubDeviceFlowPollRequest,
    GitHubDeviceFlowPollResponse,
    GitHubDeviceFlowStartRequest,
    GitHubDeviceFlowStartResponse,
    RegisterManualTokenConnectionRequest,
    StartOAuthRequest,
    StartOAuthResponse,
    StarterServersResponse,
    ToolPolicyBulkUpdate,
)
from .connection_route_helpers import (
    connection_to_dto,
    default_policy_for_tool,
    find_connection_or_404,
    load_connection_preferences,
    save_connection_preferences,
)
from .metadata_routes import register_metadata_routes
from .slack_routes import register_slack_routes
from .status_routes import register_status_routes

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/settings/connections", tags=["connections"])


_oauth_coordinator = OAuthCoordinator()
"""Process-singleton coordinator. Holds in-memory PKCE state across
the ``start_oauth`` -> ``oauth_callback`` round-trip; that state must
not be split across instances or the callback won't find its
``state``."""

_mcp_client = MCPClientService()
"""Stateless dispatcher; reusing one instance keeps the API simple
without coupling lifetimes to specific connections."""

_github_device_flow_coordinator = GitHubDeviceFlowCoordinator()
"""Process-singleton coordinator for GitHub OAuth App device flow."""

_oauth_connection_descriptions: dict[str, Optional[str]] = {}
"""State-keyed pending custom descriptions for generic OAuth callbacks."""

_github_connection_descriptions: dict[str, Optional[str]] = {}
"""Device-code-keyed pending custom descriptions for GitHub OAuth flow."""


register_slack_routes(router)
"""Slack PKCE endpoints live in ``slack_routes.py`` to keep this file
under the per-file modularity budget. They are attached to the same
router so they share the ``/settings/connections`` prefix."""

register_metadata_routes(router)
register_status_routes(router)


_OAUTH_CALLBACK_SUBPATH = "/oauth/callback/mcp"
"""Path of the callback route relative to the connections router prefix.
The full URL the OAuth provider redirects to is built by
:func:`_build_redirect_uri`, which combines the live request origin
with the router's ``/settings/connections`` prefix and this subpath."""

_OAUTH_CALLBACK_FULL_PATH = "/settings/connections" + _OAUTH_CALLBACK_SUBPATH

_SWIFT_REDIRECT_SCHEME = "basil://mcp/connection_complete"


def _connection_to_dto(record: MCPConnectionRecord) -> ConnectionDTO:
    return connection_to_dto(record)


@router.get("/starter_servers", response_model=StarterServersResponse)
async def list_starter_servers() -> StarterServersResponse:
    """Return the curated list of starter MCP servers."""
    return StarterServersResponse(starter_servers=STARTER_SERVERS)


@router.get("", response_model=ConnectionsListResponse)
async def list_connections() -> ConnectionsListResponse:
    """List every registered remote MCP connection."""
    prefs = load_connection_preferences()
    return ConnectionsListResponse(
        connections=[_connection_to_dto(r) for r in prefs.connections.mcp_connections]
    )


@router.post("/manual_token", response_model=ConnectionDTO)
async def register_manual_token_connection(
    payload: RegisterManualTokenConnectionRequest,
) -> ConnectionDTO:
    """Register an MCP server whose bearer token is supplied by the client.

    Some hosted MCP servers (notably GitHub's official remote MCP server)
    expose a streamable-HTTP endpoint but do not support OAuth Dynamic Client
    Registration. For those, the Swift client stores the user-supplied bearer
    token directly in Keychain after this route returns the new connection id.
    The Python backend persists only metadata and later requests the token over
    the existing WebSocket bridge before dispatch.
    """
    prefs = load_connection_preferences()
    record = MCPConnectionRecord(
        friendly_name=payload.friendly_name,
        description=_normalize_optional_description(payload.description),
        server_url=payload.server_url,
    )
    prefs.connections.mcp_connections.append(record)
    save_connection_preferences(prefs)
    return _connection_to_dto(record)


@router.post("/github/start_device_flow", response_model=GitHubDeviceFlowStartResponse)
async def start_github_device_flow(
    payload: GitHubDeviceFlowStartRequest,
) -> GitHubDeviceFlowStartResponse:
    """Start GitHub OAuth App device flow for the hosted GitHub MCP server."""
    try:
        auth = await _github_device_flow_coordinator.begin_authorization(
            friendly_name=payload.friendly_name,
            server_url=payload.server_url,
            scopes=payload.requested_scopes or list(GITHUB_MCP_SCOPES),
        )
        _github_connection_descriptions[auth.device_code] = _normalize_optional_description(
            payload.description
        )
    except GitHubDeviceFlowError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected failure starting GitHub device flow")
        raise HTTPException(status_code=500, detail=f"GitHub device flow start failed: {exc}")

    return GitHubDeviceFlowStartResponse(
        device_code=auth.device_code,
        user_code=auth.user_code,
        verification_uri=auth.verification_uri,
        expires_in=auth.expires_in,
        interval=auth.interval,
        requested_scopes=auth.scopes,
    )


@router.post("/github/poll_device_flow", response_model=GitHubDeviceFlowPollResponse)
async def poll_github_device_flow(
    payload: GitHubDeviceFlowPollRequest,
) -> GitHubDeviceFlowPollResponse:
    """Poll GitHub device flow and persist/push the connection on success."""
    pending = await _github_device_flow_coordinator.get_pending_authorization(payload.device_code)
    if pending is None:
        raise HTTPException(status_code=404, detail="Unknown or expired GitHub device flow")

    try:
        token = await _github_device_flow_coordinator.poll_token(device_code=payload.device_code)
    except GitHubDeviceFlowError as exc:
        code = str(exc)
        if code in ("authorization_pending", "slow_down"):
            latest = await _github_device_flow_coordinator.get_pending_authorization(payload.device_code)
            return GitHubDeviceFlowPollResponse(
                status="pending",
                interval=latest.interval if latest else pending.interval,
                message=code,
            )
        if code in ("expired_token", "access_denied", "unknown_device_code"):
            raise HTTPException(status_code=400, detail=code)
        raise HTTPException(status_code=400, detail=code)
    except Exception as exc:
        logger.exception("Unexpected failure polling GitHub device flow")
        raise HTTPException(status_code=500, detail=f"GitHub device flow polling failed: {exc}")

    record = _persist_github_device_connection(
        friendly_name=pending.friendly_name,
        server_url=pending.server_url,
        scopes=(token.scope.split(",") if token.scope else pending.scopes),
        description=_github_connection_descriptions.pop(payload.device_code, None),
    )
    await _push_token_to_swift(
        connection_id=record.id,
        access_token=token.access_token,
        refresh_token=None,
        expires_in=None,
    )
    return GitHubDeviceFlowPollResponse(
        status="ok",
        connection=_connection_to_dto(record),
    )


@router.post("/start_oauth", response_model=StartOAuthResponse)
async def start_oauth(payload: StartOAuthRequest, request: Request) -> StartOAuthResponse:
    """Begin an OAuth 2.1 flow against an MCP server.

    ``redirect_uri`` is computed from ``request.base_url`` so it
    always matches the actual host+port FastAPI is listening on,
    including the dynamic-port (``--port 0``) case the bundled
    launcher uses.
    """
    redirect_uri = _build_redirect_uri(request)
    try:
        result = await _oauth_coordinator.begin_registration(
            server_url=payload.server_url,
            friendly_name=payload.friendly_name,
            redirect_uri=redirect_uri,
            requested_scopes=payload.requested_scopes,
        )
        _oauth_connection_descriptions[result["state"]] = _normalize_optional_description(
            payload.description
        )
    except OAuthCoordinatorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected failure starting MCP OAuth flow")
        raise HTTPException(status_code=500, detail=f"OAuth start failed: {exc}")
    return StartOAuthResponse(state=result["state"], authorization_url=result["authorization_url"])


@router.get(_OAUTH_CALLBACK_SUBPATH, include_in_schema=False)
async def oauth_callback(
    state: str,
    code: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
):
    """Receive the OAuth redirect, finalize the flow, hand off to the client.

    Success path: persist a stub ``MCPConnectionRecord``, push the
    access token to the Swift client over the WebSocket so it can
    store the token in Keychain, then redirect the user's browser
    back into the Basil app via the ``basil://mcp/connection_complete``
    custom URL scheme so the Connections tab can refresh.
    """
    if error:
        message = error_description or error
        return RedirectResponse(
            f"{_SWIFT_REDIRECT_SCHEME}?status=error&message={_url_quote(message)}",
            status_code=302,
        )
    if not code:
        return RedirectResponse(
            f"{_SWIFT_REDIRECT_SCHEME}?status=error&message=missing_code",
            status_code=302,
        )

    try:
        descriptor = await _oauth_coordinator.complete_registration(state=state, code=code)
    except OAuthCoordinatorError as exc:
        return RedirectResponse(
            f"{_SWIFT_REDIRECT_SCHEME}?status=error&message={_url_quote(str(exc))}",
            status_code=302,
        )

    description = _oauth_connection_descriptions.pop(state, None)
    record = _persist_connection_from_descriptor(descriptor, description=description)
    await _push_token_to_swift(
        connection_id=record.id,
        access_token=descriptor.token.access_token,
        refresh_token=descriptor.token.refresh_token,
        expires_in=descriptor.token.expires_in,
    )

    return RedirectResponse(
        f"{_SWIFT_REDIRECT_SCHEME}?status=ok&connection_id={record.id}",
        status_code=302,
    )


@router.delete("/{connection_id}")
async def delete_connection(
    connection_id: str,
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
):
    """Remove a connection, its audit history, and notify the client to
    purge its Keychain entry."""
    prefs = load_connection_preferences()
    before = len(prefs.connections.mcp_connections)
    prefs.connections.mcp_connections = [
        r for r in prefs.connections.mcp_connections if r.id != connection_id
    ]
    if len(prefs.connections.mcp_connections) == before:
        raise HTTPException(status_code=404, detail="Connection not found")
    save_connection_preferences(prefs)

    await knowledge_service.mcp_call_log_repository.delete_for_connection(connection_id)
    await _push_token_delete_to_swift(connection_id)
    return {"status": "deleted", "connection_id": connection_id}


@router.put("/{connection_id}/policy", response_model=ConnectionDTO)
async def update_tool_policy(
    connection_id: str,
    payload: ToolPolicyBulkUpdate,
) -> ConnectionDTO:
    """Replace per-tool approval policies for a single connection."""
    prefs = load_connection_preferences()
    record = find_connection_or_404(prefs, connection_id)
    for entry in payload.policies:
        record.tool_policies[entry.tool_name] = entry.policy
    save_connection_preferences(prefs)
    return _connection_to_dto(record)


@router.get("/{connection_id}/tools", response_model=ConnectionDTO)
async def refresh_tools(connection_id: str, request: Request) -> ConnectionDTO:
    """Re-fetch the live tool catalog and update the connection's cache.

    The access token is fetched on demand from the Swift client over
    the WebSocket bridge — see :func:`_request_access_token_from_swift`.
    """
    prefs = load_connection_preferences()
    record = find_connection_or_404(prefs, connection_id)
    token_outcome = await _request_access_token_from_swift(connection_id)
    if not token_outcome.access_token:
        raise HTTPException(
            status_code=401,
            detail={
                "kind": token_outcome.kind,
                "message": token_outcome.message,
                "user_action_required": token_outcome.user_action_required,
            },
        )

    envelope = await _mcp_client.list_tools(record.server_url, token_outcome.access_token)
    if not envelope.get("ok"):
        err = envelope["error"]
        raise HTTPException(
            status_code=502,
            detail={
                "kind": err["kind"],
                "message": err["message"],
                "user_action_required": err.get("user_action_required"),
            },
        )

    tools_payload = envelope["result"]["tools"]
    record.cached_tools = [
        MCPCachedTool(
            name=t["name"],
            description=t.get("description"),
            is_read_only_hint=t.get("is_read_only_hint", False),
            input_schema=t.get("input_schema") or {},
        )
        for t in tools_payload
    ]
    for tool in record.cached_tools:
        if tool.name not in record.tool_policies:
            record.tool_policies[tool.name] = default_policy_for_tool(tool)
    # Capture the server's secret-free self-description (serverInfo.name +
    # MCP `instructions`) so routing surfaces can identify which system this
    # connection serves. No-op when the server provides neither.
    apply_server_metadata_to_record(record, envelope["result"].get("server"))
    # A successful `list_tools` call already proves the token is valid and
    # the server is reachable -- the same evidence `check_connection_status`
    # would produce -- so record that here instead of leaving the status
    # stuck at "not checked yet" until the user manually clicks "Check
    # Status" right after they just finished authorizing it.
    now = datetime.utcnow()
    record.last_tool_refresh_at = now
    record.last_connection_check_at = now
    record.last_connection_status = STATUS_HEALTHY
    record.last_connection_status_message = "Connected."
    save_connection_preferences(prefs)
    return _connection_to_dto(record)


@router.get("/call_log", response_model=CallLogResponse)
async def get_call_log(
    limit: int = 100,
    connection_id: Optional[str] = None,
    knowledge_service: SQLiteKnowledgeService = Depends(get_sqlite_knowledge_service),
) -> CallLogResponse:
    """Return the most recent MCP audit-log entries (optionally filtered)."""
    repo = knowledge_service.mcp_call_log_repository
    if connection_id:
        rows = await repo.list_by_connection(connection_id, limit=limit)
    else:
        rows = await repo.list_recent(limit=limit)
    return CallLogResponse(entries=[CallLogEntry(**row) for row in rows])


def _persist_connection_from_descriptor(
    descriptor,
    *,
    description: Optional[str] = None,
) -> MCPConnectionRecord:
    """Create an MCPConnectionRecord from an OAuth ConnectionDescriptor."""
    prefs = load_connection_preferences()
    record = MCPConnectionRecord(
        friendly_name=descriptor.friendly_name,
        description=description,
        server_url=descriptor.server_url,
        oauth_client_id=descriptor.client_id,
        oauth_authorization_server=descriptor.authorization_server,
        oauth_token_endpoint=descriptor.token_endpoint,
        oauth_scopes=descriptor.scopes,
    )
    prefs.connections.mcp_connections.append(record)
    save_connection_preferences(prefs)
    return record


def _persist_github_device_connection(
    *,
    friendly_name: str,
    server_url: str,
    scopes: List[str],
    description: Optional[str] = None,
) -> MCPConnectionRecord:
    """Create an MCPConnectionRecord for GitHub's static OAuth device flow."""
    prefs = load_connection_preferences()
    record = MCPConnectionRecord(
        friendly_name=friendly_name,
        description=description,
        server_url=server_url,
        oauth_client_id=GITHUB_OAUTH_CLIENT_ID,
        oauth_authorization_server="https://github.com/login/oauth",
        oauth_token_endpoint="https://github.com/login/oauth/access_token",
        oauth_scopes=scopes,
    )
    prefs.connections.mcp_connections.append(record)
    save_connection_preferences(prefs)
    return record


def _build_redirect_uri(request: Request) -> str:
    """Construct the OAuth redirect_uri using the live request origin.

    ``request.base_url`` already includes scheme + host + port + any
    proxy prefix, so this works unchanged for ``--port 0`` /
    APP_SUPPORT_DIR-managed dynamic ports without the coordinator
    needing to know about them.
    """
    base = str(request.base_url).rstrip("/")
    return f"{base}{_OAUTH_CALLBACK_FULL_PATH}"


def _url_quote(value: str) -> str:
    """Inline url-encode helper kept here so the route file is self-contained."""
    from urllib.parse import quote
    return quote(value, safe="")


def _normalize_optional_description(value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


