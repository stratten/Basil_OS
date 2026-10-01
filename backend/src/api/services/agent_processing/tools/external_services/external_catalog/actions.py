"""Action implementations for the external_catalog tool."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from .approval import request_external_catalog_user_approval
from .audit import record_external_catalog_audit
from .auth import (
    default_external_catalog_policy_for_tool,
    find_external_catalog_connection,
    get_external_catalog_mcp_client,
    invalidate_cached_access_token_on_auth_error,
    load_external_catalog_preferences,
    record_connection_auth_rejection,
    resolve_external_catalog_access_token,
    try_generic_oauth_refresh_and_retry,
    try_slack_refresh_and_retry,
)
from .envelopes import (
    make_external_catalog_auth_unavailable,
    make_external_catalog_needs_reconnect,
    make_external_catalog_not_found,
    make_external_catalog_permission_denied,
)
from .rate_limits import try_rate_limit_wait_and_retry
from .schema_guard import (
    cache_tool_schemas,
    ensure_tool_schema_surfaced,
    mark_tools_surfaced,
)


async def _reject_if_known_needs_reconnect(
    record: Any,
    tool_name: str,
    arguments: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Fail fast for a connection already marked ``needs_reconnect``, so a dead token never triggers a Keychain read or a doomed remote call. Reconnect or Check Status clears the mark."""
    if getattr(record, "last_connection_status", None) != "needs_reconnect":
        return None
    started_at = datetime.utcnow()
    envelope = make_external_catalog_needs_reconnect(record.friendly_name)
    await record_external_catalog_audit(
        record=record, tool_name=tool_name, arguments=arguments,
        classification="error", envelope=envelope,
        started_at=started_at, completed_at=datetime.utcnow(),
    )
    return envelope


async def list_external_catalog_servers() -> Dict[str, Any]:
    prefs = load_external_catalog_preferences()
    servers = []
    for r in prefs.connections.mcp_connections:
        if not r.enabled:
            continue
        servers.append({
            "connection_id": r.id,
            "friendly_name": r.friendly_name,
            "description": r.description,
            "server_url": r.server_url,
            "server_name": r.server_name,
            "server_instructions": r.server_instructions,
            "tool_count": len(r.cached_tools),
        })
    return {"ok": True, "result": {"servers": servers}}


async def describe_external_catalog_server(connection_id: str) -> Dict[str, Any]:
    prefs = load_external_catalog_preferences()
    record = find_external_catalog_connection(prefs, connection_id)
    if record is None:
        return make_external_catalog_not_found(f"No connection with id '{connection_id}'")

    needs_reconnect_envelope = await _reject_if_known_needs_reconnect(
        record, "describe_server", {"connection_id": connection_id}
    )
    if needs_reconnect_envelope is not None:
        return needs_reconnect_envelope

    started_at = datetime.utcnow()
    token_outcome = await resolve_external_catalog_access_token(connection_id)
    if not token_outcome.access_token:
        envelope = make_external_catalog_auth_unavailable(token_outcome)
        await record_external_catalog_audit(
            record=record, tool_name="describe_server", arguments={"connection_id": connection_id},
            classification="error", envelope=envelope,
            started_at=started_at, completed_at=datetime.utcnow(),
        )
        return envelope

    client = get_external_catalog_mcp_client()
    envelope = await client.list_tools(record.server_url, token_outcome.access_token)
    invalidate_cached_access_token_on_auth_error(connection_id, envelope)
    retry_envelope = await try_slack_refresh_and_retry(
        record=record,
        envelope=envelope,
        redo=lambda refreshed_token: client.list_tools(record.server_url, refreshed_token),
    )
    if retry_envelope is None:
        retry_envelope = await try_generic_oauth_refresh_and_retry(
            record=record,
            envelope=envelope,
            redo=lambda refreshed_token: client.list_tools(record.server_url, refreshed_token),
        )
    if retry_envelope is not None:
        envelope = retry_envelope
    record_connection_auth_rejection(connection_id, envelope)
    rate_retry_envelope = await try_rate_limit_wait_and_retry(
        record=record,
        envelope=envelope,
        redo=lambda: client.list_tools(record.server_url, token_outcome.access_token),
        tool_name="describe_server",
    )
    if rate_retry_envelope is not None:
        envelope = rate_retry_envelope
    classification = "success" if envelope.get("ok") else "error"
    await record_external_catalog_audit(
        record=record, tool_name="describe_server", arguments={"connection_id": connection_id},
        classification=classification, envelope=envelope,
        started_at=started_at, completed_at=datetime.utcnow(),
    )
    if envelope.get("ok"):
        result = envelope["result"]
        result["connection_id"] = connection_id
        result["friendly_name"] = record.friendly_name
        result["description"] = record.description
        # The model has now been shown this connection's full tool surface
        # (names + input schemas). Record that for the run so the call_tool
        # schema guard treats these tools as surfaced and never re-fetches.
        tools = result.get("tools") or []
        mark_tools_surfaced(connection_id, [t.get("name") for t in tools if t.get("name")])
        cache_tool_schemas(connection_id, tools)
        return envelope
    return envelope


async def call_external_catalog_tool(
    connection_id: str,
    tool_name: str,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    prefs = load_external_catalog_preferences()
    record = find_external_catalog_connection(prefs, connection_id)
    if record is None:
        return make_external_catalog_not_found(f"No connection with id '{connection_id}'")

    needs_reconnect_envelope = await _reject_if_known_needs_reconnect(record, tool_name, arguments)
    if needs_reconnect_envelope is not None:
        return needs_reconnect_envelope

    # Schema-surfacing guard (Locus 3): before dispatching a parameterized tool
    # whose schema the model has not seen this run, return a corrective envelope
    # carrying the schema instead of forwarding possibly-malformed arguments.
    # Returned before any audit write so this internal handshake never lands in
    # mcp_call_log; returns None (proceed) for surfaced/zero-arg tools and when
    # a live schema fetch is unavailable.
    schema_guard_envelope = await ensure_tool_schema_surfaced(record, connection_id, tool_name)
    if schema_guard_envelope is not None:
        return schema_guard_envelope

    policy = record.tool_policies.get(tool_name, default_external_catalog_policy_for_tool(record, tool_name))
    started_at = datetime.utcnow()

    if policy == "never_allow":
        envelope = make_external_catalog_permission_denied(tool_name, "Policy is 'never_allow'.")
        await record_external_catalog_audit(
            record=record, tool_name=tool_name, arguments=arguments,
            classification="denied", envelope=envelope,
            started_at=started_at, completed_at=datetime.utcnow(),
        )
        return envelope

    if policy == "always_ask":
        approved = await request_external_catalog_user_approval(record, tool_name, arguments)
        if not approved:
            envelope = make_external_catalog_permission_denied(tool_name, "User denied the request.")
            await record_external_catalog_audit(
                record=record, tool_name=tool_name, arguments=arguments,
                classification="denied", envelope=envelope,
                started_at=started_at, completed_at=datetime.utcnow(),
            )
            return envelope

    token_outcome = await resolve_external_catalog_access_token(connection_id)
    if not token_outcome.access_token:
        envelope = make_external_catalog_auth_unavailable(token_outcome)
        await record_external_catalog_audit(
            record=record, tool_name=tool_name, arguments=arguments,
            classification="error", envelope=envelope,
            started_at=started_at, completed_at=datetime.utcnow(),
        )
        return envelope
    client = get_external_catalog_mcp_client()
    envelope = await client.call_tool(record.server_url, tool_name, arguments, token_outcome.access_token)
    invalidate_cached_access_token_on_auth_error(connection_id, envelope)
    retry_envelope = await try_slack_refresh_and_retry(
        record=record,
        envelope=envelope,
        redo=lambda refreshed_token: client.call_tool(
            record.server_url,
            tool_name,
            arguments,
            refreshed_token,
        ),
    )
    if retry_envelope is None:
        retry_envelope = await try_generic_oauth_refresh_and_retry(
            record=record,
            envelope=envelope,
            redo=lambda refreshed_token: client.call_tool(
                record.server_url,
                tool_name,
                arguments,
                refreshed_token,
            ),
        )
    if retry_envelope is not None:
        envelope = retry_envelope
    record_connection_auth_rejection(connection_id, envelope)
    rate_retry_envelope = await try_rate_limit_wait_and_retry(
        record=record,
        envelope=envelope,
        redo=lambda: client.call_tool(record.server_url, tool_name, arguments, token_outcome.access_token),
        tool_name=tool_name,
    )
    if rate_retry_envelope is not None:
        envelope = rate_retry_envelope

    classification = "success" if envelope.get("ok") else "error"
    await record_external_catalog_audit(
        record=record, tool_name=tool_name, arguments=arguments,
        classification=classification, envelope=envelope,
        started_at=started_at, completed_at=datetime.utcnow(),
    )
    return envelope
