"""Per-run schema-surfacing guard for external_catalog tool dispatch.

Locus 3 of the retrieval-resilience work (see the External-Tool Retrieval
Resilience guide, section 4.1.1): the dispatcher must not forward a
possibly-malformed ``arguments`` dict to a parameterized remote tool before
the model has been shown that tool's input schema this run. When a
parameterized tool is called cold (no prior ``describe_server`` and no cached
schema in context), the guard hydrates the schema and returns a corrective
``schema_required`` envelope instructing the model to re-issue ``call_tool``
with valid arguments.

State is kept in the per-run ``agent_runtime_context`` dict (the same store
used for the run token cache and rate-limit coalescing), so nothing leaks
across runs and no new mechanism is introduced. The guard never validates
arguments against the schema (Basil has no ``jsonschema`` dependency); it only
enforces that the schema has been *surfaced*.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from api.services.agent_processing.shared.agent_runtime_context import (
    get_current_agent_context,
)

from .auth import (
    get_external_catalog_mcp_client,
    resolve_external_catalog_access_token,
)
from .envelopes import make_external_catalog_schema_required

logger = logging.getLogger(__name__)

_SURFACED_KEY = "external_catalog_surfaced_tools"
_SCHEMA_CACHE_KEY = "external_catalog_schema_cache"


def _surfaced_map(context: Dict[str, Any]) -> Dict[str, set]:
    surfaced = context.get(_SURFACED_KEY)
    if not isinstance(surfaced, dict):
        surfaced = {}
        context[_SURFACED_KEY] = surfaced
    return surfaced


def _schema_cache(context: Dict[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    cache = context.get(_SCHEMA_CACHE_KEY)
    if not isinstance(cache, dict):
        cache = {}
        context[_SCHEMA_CACHE_KEY] = cache
    return cache


def mark_tools_surfaced(connection_id: str, tool_names: Iterable[str]) -> None:
    """Record that these tool names' schemas have been shown to the model this run."""
    context = get_current_agent_context()
    if not isinstance(context, dict):
        return
    surfaced = _surfaced_map(context)
    bucket = surfaced.get(connection_id)
    if not isinstance(bucket, set):
        bucket = set()
        surfaced[connection_id] = bucket
    for name in tool_names:
        if name:
            bucket.add(str(name))


def is_tool_surfaced(connection_id: str, tool_name: str) -> bool:
    """True when ``tool_name`` on ``connection_id`` was surfaced earlier this run."""
    context = get_current_agent_context()
    if not isinstance(context, dict):
        return False
    bucket = _surfaced_map(context).get(connection_id)
    return isinstance(bucket, set) and tool_name in bucket


def cache_tool_schemas(connection_id: str, tools_payload: Iterable[Dict[str, Any]]) -> None:
    """Store ``{tool_name: input_schema}`` for a connection for the rest of the run.

    Always creates the connection's entry (even when empty) so the guard treats
    the connection as already fetched and never repeats the live round-trip.
    """
    context = get_current_agent_context()
    if not isinstance(context, dict):
        return
    cache = _schema_cache(context)
    conn_schemas: Dict[str, Dict[str, Any]] = {}
    for tool in tools_payload or []:
        name = tool.get("name") if isinstance(tool, dict) else getattr(tool, "name", None)
        if not name:
            continue
        schema = (
            tool.get("input_schema")
            if isinstance(tool, dict)
            else getattr(tool, "input_schema", None)
        )
        conn_schemas[str(name)] = schema if isinstance(schema, dict) else {}
    cache[connection_id] = conn_schemas


def _run_cached_schema(
    context: Dict[str, Any], connection_id: str, tool_name: str
) -> tuple[bool, Optional[Dict[str, Any]]]:
    """Return ``(connection_fetched_this_run, schema_or_None)`` from the run cache."""
    cache = _schema_cache(context)
    if connection_id not in cache:
        return (False, None)
    return (True, cache[connection_id].get(tool_name))


def _record_schema(record: Any, tool_name: str) -> Optional[Dict[str, Any]]:
    """Return the persisted cached input_schema for a tool, or None when absent/empty."""
    for tool in getattr(record, "cached_tools", []) or []:
        name = getattr(tool, "name", None)
        if name == tool_name:
            schema = getattr(tool, "input_schema", None)
            return schema if isinstance(schema, dict) and schema else None
    return None


async def _live_fetch_schema(
    record: Any, connection_id: str, tool_name: str
) -> Optional[Dict[str, Any]]:
    """Fetch the connection's live tool schemas once per run; return this tool's schema.

    On any token/list failure returns ``None`` and does not raise: the normal
    ``call_tool`` path then runs and surfaces the real auth/network error rather
    than the guard masking it behind a schema handshake.
    """
    server_url = getattr(record, "server_url", None)
    if not server_url:
        return None
    token_outcome = await resolve_external_catalog_access_token(connection_id)
    access_token = getattr(token_outcome, "access_token", None)
    if not access_token:
        return None
    client = get_external_catalog_mcp_client()
    envelope = await client.list_tools(server_url, access_token)
    if not isinstance(envelope, dict) or not envelope.get("ok"):
        return None
    tools: List[Dict[str, Any]] = (envelope.get("result") or {}).get("tools") or []
    cache_tool_schemas(connection_id, tools)
    _, schema = _run_cached_schema(get_current_agent_context(), connection_id, tool_name)
    return schema


async def ensure_tool_schema_surfaced(
    record: Any, connection_id: str, tool_name: str
) -> Optional[Dict[str, Any]]:
    """Guard a ``call_tool`` dispatch. Return None to proceed, or a corrective envelope.

    Resolution order for the tool's schema: per-run cache (from a prior
    describe/fetch this run) -> persisted ``record.cached_tools`` -> a single
    live ``list_tools`` per connection per run. A tool with no parameters, only
    optional parameters, or an unresolvable schema is marked surfaced and allowed
    through so it never incurs a corrective round-trip; only tools that declare
    required parameters have their schema surfaced before the first call.
    """
    if is_tool_surfaced(connection_id, tool_name):
        return None

    context = get_current_agent_context()
    fetched, schema = _run_cached_schema(context, connection_id, tool_name)
    if not fetched:
        schema = _record_schema(record, tool_name)
        if schema is None:
            schema = await _live_fetch_schema(record, connection_id, tool_name)

    if not isinstance(schema, dict) or not schema.get("properties"):
        mark_tools_surfaced(connection_id, [tool_name])
        return None

    # A schema whose parameters are all optional can be called with an empty or
    # partial arguments dict without risking a malformed required-field call, so
    # proceed cold rather than forcing a corrective schema round-trip (e.g. a
    # list tool where every filter is optional). Tools that declare required
    # parameters still get their schema surfaced first.
    if not schema.get("required"):
        mark_tools_surfaced(connection_id, [tool_name])
        return None

    mark_tools_surfaced(connection_id, [tool_name])
    logger.info(
        "external_catalog schema guard surfaced schema for %s on %s before first call",
        tool_name,
        connection_id,
    )
    return make_external_catalog_schema_required(tool_name, connection_id, schema)
