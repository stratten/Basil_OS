"""Tests for retrieval-resilience levers A-D on the external_catalog surface.

Covers:
- Lever A (capability hydration): MCPCachedTool schema field, refresh-route
  persistence, and the dispatch-time schema-surfacing guard (normal, negative,
  adversarial).
- Levers B/C/D (query strategy, reformulation ladder, feedback): the tool
  description and system-prompt guidance.
"""

from types import SimpleNamespace

import pytest

from api.core.models.preference_models.execution_and_connections import (
    MCPCachedTool,
    MCPConnectionRecord,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.external_services.external_catalog import (
    descriptions as external_catalog_descriptions,
)
from api.services.agent_processing.tools.external_services.external_catalog import (
    schema_guard,
)
from api.services.agent_processing.lifecycle.execution_graph.system_prompts import (
    AGENT_SYSTEM_PROMPT_TEMPLATE,
)


PARAM_SCHEMA = {
    "type": "object",
    "properties": {"requestNumber": {"type": "string"}},
    "required": ["requestNumber"],
}
ZERO_ARG_SCHEMA = {"type": "object", "properties": {}}
ALL_OPTIONAL_SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}}


def _record(cached_tools=None, server_url="https://svc.example/mcp"):
    return SimpleNamespace(
        id="conn-1",
        friendly_name="Speakeasy",
        server_url=server_url,
        cached_tools=cached_tools or [],
    )


def _cached_tool(name, input_schema):
    return SimpleNamespace(name=name, input_schema=input_schema, is_read_only_hint=True)


# --------------------------------------------------------------------------
# Lever A1 - the cache model carries the schema
# --------------------------------------------------------------------------

def test_cached_tool_defaults_schema_to_empty_dict():
    tool = MCPCachedTool(name="t")
    assert tool.input_schema == {}


def test_cached_tool_preserves_input_schema():
    tool = MCPCachedTool(name="speakeasy_list_requests", input_schema=PARAM_SCHEMA)
    assert tool.input_schema == PARAM_SCHEMA


# --------------------------------------------------------------------------
# Lever A2 - the refresh route persists the schema into cached_tools
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_tools_persists_input_schema(monkeypatch):
    from api.routes.connections import routes as conn_routes

    record = MCPConnectionRecord(
        id="conn-1", friendly_name="Speakeasy", server_url="https://svc.example/mcp"
    )
    prefs = SimpleNamespace(connections=SimpleNamespace(mcp_connections=[record]))

    monkeypatch.setattr(conn_routes, "load_connection_preferences", lambda: prefs)
    monkeypatch.setattr(conn_routes, "save_connection_preferences", lambda _p: None)

    async def fake_token(_connection_id):
        return SimpleNamespace(
            access_token="tok", kind="ok", message=None, user_action_required=None
        )

    monkeypatch.setattr(conn_routes, "_request_access_token_from_swift", fake_token)

    class FakeClient:
        async def list_tools(self, _url, _token):
            return {
                "ok": True,
                "result": {
                    "server": {},
                    "tools": [
                        {
                            "name": "speakeasy_list_requests",
                            "description": "List requests",
                            "input_schema": PARAM_SCHEMA,
                            "is_read_only_hint": True,
                        }
                    ],
                },
            }

    monkeypatch.setattr(conn_routes, "_mcp_client", FakeClient())

    await conn_routes.refresh_tools("conn-1", request=None)

    assert record.cached_tools[0].input_schema == PARAM_SCHEMA


# --------------------------------------------------------------------------
# Lever A - the dispatch-time schema-surfacing guard
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_guard_proceeds_when_tool_already_surfaced():
    token = set_current_agent_context({"agent_task_id": "test-run"})
    try:
        schema_guard.mark_tools_surfaced("conn-1", ["speakeasy_list_requests"])
        result = await schema_guard.ensure_tool_schema_surfaced(
            _record(), "conn-1", "speakeasy_list_requests"
        )
    finally:
        reset_current_agent_context(token)
    assert result is None


@pytest.mark.asyncio
async def test_guard_returns_corrective_for_cold_parameterized_tool_from_record_cache():
    record = _record([_cached_tool("speakeasy_list_requests", PARAM_SCHEMA)])
    token = set_current_agent_context({"agent_task_id": "test-run"})
    try:
        first = await schema_guard.ensure_tool_schema_surfaced(
            record, "conn-1", "speakeasy_list_requests"
        )
        # After the corrective handshake the tool is surfaced, so the re-issue proceeds.
        second = await schema_guard.ensure_tool_schema_surfaced(
            record, "conn-1", "speakeasy_list_requests"
        )
    finally:
        reset_current_agent_context(token)

    assert first is not None
    assert first["ok"] is False
    assert first["error"]["kind"] == "schema_required"
    assert first["error"]["retryable"] is True
    assert first["error"]["raw"]["input_schema"] == PARAM_SCHEMA
    assert first["error"]["raw"]["tool_name"] == "speakeasy_list_requests"
    assert second is None


@pytest.mark.asyncio
async def test_guard_proceeds_for_zero_arg_tool_without_corrective():
    record = _record([_cached_tool("speakeasy_ping", ZERO_ARG_SCHEMA)])
    token = set_current_agent_context({"agent_task_id": "test-run"})
    try:
        result = await schema_guard.ensure_tool_schema_surfaced(
            record, "conn-1", "speakeasy_ping"
        )
        assert schema_guard.is_tool_surfaced("conn-1", "speakeasy_ping") is True
    finally:
        reset_current_agent_context(token)
    assert result is None


@pytest.mark.asyncio
async def test_guard_proceeds_for_all_optional_tool_without_corrective():
    # A parameterized tool whose properties are ALL optional (no "required")
    # can be called cold with an empty/partial args dict, so the guard proceeds
    # instead of forcing a corrective round-trip (e.g. a list tool with only
    # optional filters). Regression guard for the speakeasy_list_requests({})
    # friction observed in the field.
    record = _record([_cached_tool("speakeasy_list_requests", ALL_OPTIONAL_SCHEMA)])
    token = set_current_agent_context({"agent_task_id": "test-run"})
    try:
        result = await schema_guard.ensure_tool_schema_surfaced(
            record, "conn-1", "speakeasy_list_requests"
        )
        assert schema_guard.is_tool_surfaced("conn-1", "speakeasy_list_requests") is True
    finally:
        reset_current_agent_context(token)
    assert result is None


@pytest.mark.asyncio
async def test_guard_returns_corrective_for_required_param_tool():
    # The complement of the all-optional case: a tool that declares a required
    # parameter still has its schema surfaced before the first call.
    record = _record([_cached_tool("speakeasy_get_request", PARAM_SCHEMA)])
    token = set_current_agent_context({"agent_task_id": "test-run"})
    try:
        result = await schema_guard.ensure_tool_schema_surfaced(
            record, "conn-1", "speakeasy_get_request"
        )
    finally:
        reset_current_agent_context(token)
    assert result is not None
    assert result["error"]["kind"] == "schema_required"
    assert result["error"]["raw"]["input_schema"] == PARAM_SCHEMA


@pytest.mark.asyncio
async def test_guard_live_fetches_once_when_record_schema_empty(monkeypatch):
    # Record has the tool but with an empty (uncached) schema -> guard live-fetches.
    record = _record([_cached_tool("speakeasy_list_requests", {})])
    fetch_calls = {"n": 0}

    async def fake_token(_connection_id):
        return SimpleNamespace(access_token="tok")

    class FakeClient:
        async def list_tools(self, _url, _token):
            fetch_calls["n"] += 1
            return {
                "ok": True,
                "result": {
                    "tools": [
                        {"name": "speakeasy_list_requests", "input_schema": PARAM_SCHEMA}
                    ]
                },
            }

    monkeypatch.setattr(schema_guard, "resolve_external_catalog_access_token", fake_token)
    monkeypatch.setattr(schema_guard, "get_external_catalog_mcp_client", lambda: FakeClient())

    token = set_current_agent_context({"agent_task_id": "test-run"})
    try:
        first = await schema_guard.ensure_tool_schema_surfaced(
            record, "conn-1", "speakeasy_list_requests"
        )
        # A different tool on the same connection must not trigger a second fetch;
        # the run cache from the first fetch already covers the connection.
        _ = await schema_guard.ensure_tool_schema_surfaced(
            record, "conn-1", "speakeasy_other"
        )
    finally:
        reset_current_agent_context(token)

    assert first is not None
    assert first["error"]["kind"] == "schema_required"
    assert first["error"]["raw"]["input_schema"] == PARAM_SCHEMA
    assert fetch_calls["n"] == 1


@pytest.mark.asyncio
async def test_guard_proceeds_when_live_fetch_token_unavailable(monkeypatch):
    # Adversarial: no cached schema and token resolution fails. The guard must
    # NOT mask the real auth error - it returns None so the normal dispatch path
    # surfaces auth_unavailable.
    record = _record([])

    async def fake_token(_connection_id):
        return SimpleNamespace(access_token=None)

    fetched = {"n": 0}

    class FakeClient:
        async def list_tools(self, _url, _token):
            fetched["n"] += 1
            return {"ok": True, "result": {"tools": []}}

    monkeypatch.setattr(schema_guard, "resolve_external_catalog_access_token", fake_token)
    monkeypatch.setattr(schema_guard, "get_external_catalog_mcp_client", lambda: FakeClient())

    token = set_current_agent_context({"agent_task_id": "test-run"})
    try:
        result = await schema_guard.ensure_tool_schema_surfaced(
            record, "conn-1", "speakeasy_list_requests"
        )
    finally:
        reset_current_agent_context(token)

    assert result is None
    assert fetched["n"] == 0  # short-circuited before calling the client


@pytest.mark.asyncio
async def test_cache_tool_schemas_and_mark_surfaced_satisfy_guard():
    # Mirrors describe_server: caching schemas + marking surfaced lets a later
    # parameterized call_tool proceed with zero extra fetches.
    token = set_current_agent_context({"agent_task_id": "test-run"})
    try:
        payload = [{"name": "speakeasy_list_requests", "input_schema": PARAM_SCHEMA}]
        schema_guard.cache_tool_schemas("conn-1", payload)
        schema_guard.mark_tools_surfaced("conn-1", ["speakeasy_list_requests"])
        result = await schema_guard.ensure_tool_schema_surfaced(
            _record(), "conn-1", "speakeasy_list_requests"
        )
    finally:
        reset_current_agent_context(token)
    assert result is None


# --------------------------------------------------------------------------
# Levers B/C/D - description + system-prompt guidance
# --------------------------------------------------------------------------

def test_full_description_carries_search_and_reformulation_guidance():
    description = external_catalog_descriptions.build_full_external_catalog_description(
        "**CURRENT CONNECTIONS:** none"
    )
    # Existing contract line preserved.
    assert "Discover and invoke tools on remote services" in description
    # Lever B + C sections present.
    assert "SEARCH & RETRIEVAL STRATEGY" in description
    assert "WHEN A SEARCH RETURNS NOTHING" in description
    # Lever D: instructs reading server-returned structured guidance.
    assert "structured guidance" in description


def test_slim_description_carries_reformulation_clause():
    assert "reformulate" in external_catalog_descriptions.SLIM_DESCRIPTION
    assert "structured/exact parameters" in external_catalog_descriptions.SLIM_DESCRIPTION


def test_system_prompt_bullet_carries_reformulation_clause():
    assert "reformulate" in AGENT_SYSTEM_PROMPT_TEMPLATE
    assert "enumerate-and-filter" in AGENT_SYSTEM_PROMPT_TEMPLATE


def test_full_description_carries_actuation_guidance():
    description = external_catalog_descriptions.build_full_external_catalog_description(
        "**CURRENT CONNECTIONS:** none"
    )
    # Actuation subsection, a USE example, and the not-found rung 4 are present.
    assert "ACTUATION" in description
    assert "*_create_request" in description
    assert "action/request tool that could produce the answer" in description
    # Approval framing accompanies actuation (never authorize unapproved writes).
    assert "subject to the approval policy" in description
    # Negative: the edit preserves the load-bearing invariants.
    assert "DECISIONING RULE" in description
    assert "DISCOVER-THEN-CALL PATTERN" in description
    assert "ERROR RECOVERY" in description
    assert "permission_denied" in description
    assert "tool_name' field inside an external_catalog call" in description


def test_slim_description_carries_actuation_clause():
    slim = external_catalog_descriptions.SLIM_DESCRIPTION
    assert "action tool" in slim
    assert "approval" in slim
    # Pre-existing slim contract preserved.
    assert "reformulate" in slim
    assert "structured/exact parameters" in slim
