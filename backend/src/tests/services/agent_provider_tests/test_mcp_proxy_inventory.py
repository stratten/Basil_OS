"""Focused coverage for Package 6A.1's read-only Basil MCP proxy inventory."""
from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.core.knowledge.sqlite.sqlite_knowledge_service_component_services.mcp.call_log_repository import (
    MCPCallLogRepository,
)
from api.services.agent_providers.mcp_proxy_inventory import (
    BasilMcpProxyInventoryService,
    create_basil_mcp_proxy_inventory_server,
)


def _tool(
    name: str,
    *,
    description: str = "Fixture tool.",
    read_only: bool = True,
    input_schema: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=description,
        is_read_only_hint=read_only,
        input_schema=(
            input_schema
            if input_schema is not None
            else {"type": "object", "properties": {}}
        ),
    )


def _connection(
    connection_id: str,
    *,
    enabled: bool = True,
    tools: list[SimpleNamespace] | None = None,
    policies: dict[str, str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=connection_id,
        friendly_name=f"Connection {connection_id}",
        description=f"Description for {connection_id}.",
        server_url=f"https://{connection_id}.example/mcp",
        enabled=enabled,
        cached_tools=tools if tools is not None else [_tool("read_tool")],
        tool_policies=policies or {},
        access_token="must-not-appear",
        oauth_client_id="must-not-appear",
        server_instructions="must-not-appear",
    )


def _service(*records: SimpleNamespace) -> BasilMcpProxyInventoryService:
    preferences = SimpleNamespace(
        connections=SimpleNamespace(mcp_connections=list(records)),
    )
    return BasilMcpProxyInventoryService(preferences_loader=lambda: preferences)


def test_inventory_returns_enabled_policy_eligible_sanitized_metadata_only() -> None:
    service = _service(
        _connection(
            "eligible",
            tools=[
                _tool("read_tool", read_only=True),
                _tool("write_tool", read_only=False),
                _tool("blocked_tool", read_only=False),
            ],
            policies={
                "write_tool": "always_ask",
                "blocked_tool": "never_allow",
            },
        ),
        _connection("disabled", enabled=False),
    )

    payload = service.list_eligible_tools()

    assert payload == {
        "ok": True,
        "result": {
            "connections": [
                {
                    "connection_id": "eligible",
                    "friendly_name": "Connection eligible",
                    "description": "Description for eligible.",
                    "tools": [
                        {
                            "name": "read_tool",
                            "description": "Fixture tool.",
                            "has_input_schema": True,
                            "is_read_only_hint": True,
                            "approval_policy": "always_allow",
                            "metadata_source": "cached",
                        },
                        {
                            "name": "write_tool",
                            "description": "Fixture tool.",
                            "has_input_schema": True,
                            "is_read_only_hint": False,
                            "approval_policy": "always_ask",
                            "metadata_source": "cached",
                        },
                    ],
                }
            ]
        },
    }
    serialized = str(payload)
    assert "disabled" not in serialized
    assert "blocked_tool" not in serialized
    assert "server_url" not in serialized
    assert "https://eligible.example/mcp" not in serialized
    assert "must-not-appear" not in serialized


def test_inventory_reports_schema_presence_without_exposing_schema_content() -> None:
    payload = _service(
        _connection(
            "eligible",
            tools=[
                _tool("empty_schema", input_schema={}),
                _tool(
                    "populated_schema",
                    input_schema={
                        "type": "object",
                        "description": "remote-schema-secret-must-not-appear",
                    },
                ),
            ],
        )
    ).list_eligible_tools()

    tools = payload["result"]["connections"][0]["tools"]

    assert tools == [
        {
            "name": "empty_schema",
            "description": "Fixture tool.",
            "has_input_schema": False,
            "is_read_only_hint": True,
            "approval_policy": "always_allow",
            "metadata_source": "cached",
        },
        {
            "name": "populated_schema",
            "description": "Fixture tool.",
            "has_input_schema": True,
            "is_read_only_hint": True,
            "approval_policy": "always_allow",
            "metadata_source": "cached",
        },
    ]
    assert "remote-schema-secret-must-not-appear" not in str(payload)


def test_inventory_omits_enabled_connections_without_an_eligible_tool() -> None:
    payload = _service(
        _connection("blocked", policies={"read_tool": "never_allow"}),
        _connection("disabled", enabled=False),
    ).list_eligible_tools()

    assert payload == {"ok": True, "result": {"connections": []}}


def test_inventory_reports_unavailable_preferences_without_leaking_the_exception() -> None:
    def unavailable_preferences() -> object:
        raise RuntimeError("keychain token must-not-appear")

    payload = BasilMcpProxyInventoryService(
        preferences_loader=unavailable_preferences,
    ).list_eligible_tools()

    assert payload == {
        "ok": False,
        "error": {
            "kind": "inventory_unavailable",
            "message": "Basil connection inventory is unavailable.",
            "retryable": True,
        },
    }


def test_inventory_rejects_malformed_enabled_data_without_returning_a_partial_inventory() -> None:
    malformed = _connection(
        "malformed",
        tools=[_tool("bad_schema", input_schema="not-an-object")],
    )

    payload = _service(_connection("valid"), malformed).list_eligible_tools()

    assert payload["ok"] is False
    assert payload["error"] == {
        "kind": "malformed_inventory",
        "message": "connections.mcp_connections[1].cached_tools[0].input_schema must be an object.",
        "retryable": False,
    }
    assert "valid" not in str(payload)


def test_inventory_rejects_an_invalid_effective_policy() -> None:
    payload = _service(
        _connection("invalid-policy", policies={"read_tool": "allow_everything"}),
    ).list_eligible_tools()

    assert payload == {
        "ok": False,
        "error": {
            "kind": "malformed_inventory",
            "message": (
                "connections.mcp_connections[0].cached_tools[0] has an unsupported "
                "effective policy."
            ),
            "retryable": False,
        },
    }


def test_inventory_rejects_a_connection_count_beyond_its_bound() -> None:
    records = [_connection(f"connection-{index}") for index in range(33)]

    payload = _service(*records).list_eligible_tools()

    assert payload == {
        "ok": False,
        "error": {
            "kind": "inventory_limit_exceeded",
            "message": "connections.mcp_connections exceeds the 32-connection inventory limit.",
            "retryable": False,
        },
    }


def test_inventory_rejects_identifier_and_metadata_strings_beyond_their_bounds() -> None:
    oversized_identifier_payload = _service(
        _connection("x" * 257),
    ).list_eligible_tools()
    oversized_metadata_record = _connection("valid")
    oversized_metadata_record.friendly_name = "x" * 1_025
    oversized_metadata_payload = _service(oversized_metadata_record).list_eligible_tools()

    assert oversized_identifier_payload == {
        "ok": False,
        "error": {
            "kind": "inventory_limit_exceeded",
            "message": (
                "connections.mcp_connections[0].id exceeds the 256-byte inventory limit."
            ),
            "retryable": False,
        },
    }
    assert oversized_metadata_payload == {
        "ok": False,
        "error": {
            "kind": "inventory_limit_exceeded",
            "message": (
                "connections.mcp_connections[0].friendly_name exceeds the "
                "1024-byte inventory limit."
            ),
            "retryable": False,
        },
    }


def test_inventory_rejects_a_tool_count_beyond_its_bound() -> None:
    tools = [_tool(f"tool-{index}") for index in range(65)]

    payload = _service(_connection("too-many-tools", tools=tools)).list_eligible_tools()

    assert payload == {
        "ok": False,
        "error": {
            "kind": "inventory_limit_exceeded",
            "message": (
                "connections.mcp_connections[0].cached_tools exceeds the "
                "64-tool inventory limit."
            ),
            "retryable": False,
        },
    }


def test_inventory_rejects_duplicate_enabled_connection_and_tool_identifiers() -> None:
    duplicate_connection_payload = _service(
        _connection("duplicate"),
        _connection("duplicate"),
    ).list_eligible_tools()
    duplicate_tool_payload = _service(
        _connection("valid", tools=[_tool("same_tool"), _tool("same_tool")]),
    ).list_eligible_tools()

    assert duplicate_connection_payload == {
        "ok": False,
        "error": {
            "kind": "malformed_inventory",
            "message": (
                "connections.mcp_connections[1].id duplicates an enabled connection id."
            ),
            "retryable": False,
        },
    }
    assert duplicate_tool_payload == {
        "ok": False,
        "error": {
            "kind": "malformed_inventory",
            "message": (
                "connections.mcp_connections[0].cached_tools[1].name duplicates a "
                "cached tool name."
            ),
            "retryable": False,
        },
    }


def test_inventory_does_not_write_an_mcp_call_log_record(tmp_path, monkeypatch) -> None:
    knowledge = SQLiteKnowledgeService(tmp_path / "inventory.db")
    record_call = AsyncMock()
    monkeypatch.setattr(MCPCallLogRepository, "record_call", record_call)

    assert _service(_connection("eligible")).list_eligible_tools()["ok"] is True

    with sqlite3.connect(knowledge.db_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM mcp_call_log").fetchone()
    assert count == (0,)
    record_call.assert_not_awaited()


def test_fastmcp_server_exposes_only_the_read_only_inventory_tool() -> None:
    server = create_basil_mcp_proxy_inventory_server(
        inventory_service=_service(_connection("eligible")),
    )

    tools = asyncio.run(server.list_tools())
    result = asyncio.run(server.call_tool("basil_list_eligible_tools", {}))

    assert [tool.name for tool in tools] == ["basil_list_eligible_tools"]
    assert tools[0].annotations.readOnlyHint is True
    assert tools[0].annotations.destructiveHint is False
    assert tools[0].annotations.idempotentHint is True
    assert tools[0].annotations.openWorldHint is False
    assert result[1] == _service(_connection("eligible")).list_eligible_tools()
