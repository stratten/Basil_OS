"""Read-only local MCP inventory for later provider-run proxy activation."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from api.services.agent_processing.tools.external_services.external_catalog.auth import (
    default_external_catalog_policy_for_tool,
)

MAX_CONNECTIONS = 32
MAX_TOOLS_PER_CONNECTION = 64
MAX_IDENTIFIER_BYTES = 256
MAX_METADATA_BYTES = 1_024
_ALLOWED_POLICIES = frozenset({"always_allow", "always_ask", "never_allow"})


class BasilMcpProxyInventoryError(ValueError):
    """A persisted connection record cannot safely produce a proxy inventory."""

    def __init__(self, kind: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.retryable = retryable


def _load_preferences() -> Any:
    from api.core.models.preferences import Preferences

    return Preferences.load()


def _require_text(value: object, field_name: str, maximum_bytes: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BasilMcpProxyInventoryError(
            "malformed_inventory",
            f"{field_name} must be a nonblank string.",
            retryable=False,
        )
    cleaned = value.strip()
    if len(cleaned.encode("utf-8")) > maximum_bytes:
        raise BasilMcpProxyInventoryError(
            "inventory_limit_exceeded",
            f"{field_name} exceeds the {maximum_bytes}-byte inventory limit.",
            retryable=False,
        )
    return cleaned


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name, MAX_METADATA_BYTES)


def _require_sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise BasilMcpProxyInventoryError(
            "malformed_inventory",
            f"{field_name} must be an array.",
            retryable=False,
        )
    return value


def _error_envelope(error: BasilMcpProxyInventoryError) -> dict[str, object]:
    return {
        "ok": False,
        "error": {
            "kind": error.kind,
            "message": error.message,
            "retryable": error.retryable,
        },
    }


class BasilMcpProxyInventoryService:
    """Build the bounded, policy-filtered inventory without dispatching a tool."""

    def __init__(self, *, preferences_loader: Callable[[], Any] = _load_preferences) -> None:
        self._preferences_loader = preferences_loader

    def list_eligible_tools(self) -> dict[str, object]:
        """Return current eligible connection tools or a bounded safe failure."""
        try:
            preferences = self._preferences_loader()
        except Exception:
            return {
                "ok": False,
                "error": {
                    "kind": "inventory_unavailable",
                    "message": "Basil connection inventory is unavailable.",
                    "retryable": True,
                },
            }
        try:
            return {
                "ok": True,
                "result": {
                    "connections": self._build_connection_payloads(preferences),
                },
            }
        except BasilMcpProxyInventoryError as error:
            return _error_envelope(error)

    def _build_connection_payloads(self, preferences: Any) -> list[dict[str, object]]:
        connections = getattr(getattr(preferences, "connections", None), "mcp_connections", None)
        records = _require_sequence(connections, "connections.mcp_connections")
        if len(records) > MAX_CONNECTIONS:
            raise BasilMcpProxyInventoryError(
                "inventory_limit_exceeded",
                f"connections.mcp_connections exceeds the {MAX_CONNECTIONS}-connection inventory limit.",
                retryable=False,
            )
        payloads: list[dict[str, object]] = []
        seen_connection_ids: set[str] = set()
        for connection_index, record in enumerate(records):
            if getattr(record, "enabled", None) is True:
                connection_id = _require_text(
                    getattr(record, "id", None),
                    f"connections.mcp_connections[{connection_index}].id",
                    MAX_IDENTIFIER_BYTES,
                )
                if connection_id in seen_connection_ids:
                    raise BasilMcpProxyInventoryError(
                        "malformed_inventory",
                        f"connections.mcp_connections[{connection_index}].id duplicates an enabled connection id.",
                        retryable=False,
                    )
                seen_connection_ids.add(connection_id)
            payload = self._build_connection_payload(record, connection_index)
            if payload is not None:
                payloads.append(payload)
        return payloads

    def _build_connection_payload(
        self,
        record: object,
        connection_index: int,
    ) -> dict[str, object] | None:
        enabled = getattr(record, "enabled", None)
        if type(enabled) is not bool:
            raise BasilMcpProxyInventoryError(
                "malformed_inventory",
                f"connections.mcp_connections[{connection_index}].enabled must be a boolean.",
                retryable=False,
            )
        if not enabled:
            return None
        connection_prefix = f"connections.mcp_connections[{connection_index}]"
        connection_id = _require_text(
            getattr(record, "id", None),
            f"{connection_prefix}.id",
            MAX_IDENTIFIER_BYTES,
        )
        friendly_name = _require_text(
            getattr(record, "friendly_name", None),
            f"{connection_prefix}.friendly_name",
            MAX_METADATA_BYTES,
        )
        description = _optional_text(
            getattr(record, "description", None),
            f"{connection_prefix}.description",
        )
        cached_tools = _require_sequence(
            getattr(record, "cached_tools", None),
            f"{connection_prefix}.cached_tools",
        )
        if len(cached_tools) > MAX_TOOLS_PER_CONNECTION:
            raise BasilMcpProxyInventoryError(
                "inventory_limit_exceeded",
                f"{connection_prefix}.cached_tools exceeds the {MAX_TOOLS_PER_CONNECTION}-tool inventory limit.",
                retryable=False,
            )
        tool_policies = getattr(record, "tool_policies", None)
        if not isinstance(tool_policies, Mapping):
            raise BasilMcpProxyInventoryError(
                "malformed_inventory",
                f"{connection_prefix}.tool_policies must be an object.",
                retryable=False,
            )
        tools: list[dict[str, object]] = []
        seen_tool_names: set[str] = set()
        for tool_index, tool in enumerate(cached_tools):
            tool_name = _require_text(
                getattr(tool, "name", None),
                f"{connection_prefix}.cached_tools[{tool_index}].name",
                MAX_IDENTIFIER_BYTES,
            )
            if tool_name in seen_tool_names:
                raise BasilMcpProxyInventoryError(
                    "malformed_inventory",
                    f"{connection_prefix}.cached_tools[{tool_index}].name duplicates a cached tool name.",
                    retryable=False,
                )
            seen_tool_names.add(tool_name)
            tool_payload = self._build_tool_payload(
                record=record,
                tool=tool,
                tool_policies=tool_policies,
                field_prefix=f"{connection_prefix}.cached_tools[{tool_index}]",
            )
            if tool_payload is not None:
                tools.append(tool_payload)
        if not tools:
            return None
        return {
            "connection_id": connection_id,
            "friendly_name": friendly_name,
            "description": description,
            "tools": tools,
        }

    def _build_tool_payload(
        self,
        *,
        record: object,
        tool: object,
        tool_policies: Mapping[object, object],
        field_prefix: str,
    ) -> dict[str, object] | None:
        tool_name = _require_text(
            getattr(tool, "name", None),
            f"{field_prefix}.name",
            MAX_IDENTIFIER_BYTES,
        )
        description = _optional_text(
            getattr(tool, "description", None),
            f"{field_prefix}.description",
        )
        read_only_hint = getattr(tool, "is_read_only_hint", None)
        if type(read_only_hint) is not bool:
            raise BasilMcpProxyInventoryError(
                "malformed_inventory",
                f"{field_prefix}.is_read_only_hint must be a boolean.",
                retryable=False,
            )
        input_schema = getattr(tool, "input_schema", None)
        if not isinstance(input_schema, Mapping):
            raise BasilMcpProxyInventoryError(
                "malformed_inventory",
                f"{field_prefix}.input_schema must be an object.",
                retryable=False,
            )
        if tool_name in tool_policies:
            policy = tool_policies[tool_name]
        else:
            policy = default_external_catalog_policy_for_tool(record, tool_name)
        if not isinstance(policy, str) or policy not in _ALLOWED_POLICIES:
            raise BasilMcpProxyInventoryError(
                "malformed_inventory",
                f"{field_prefix} has an unsupported effective policy.",
                retryable=False,
            )
        if policy == "never_allow":
            return None
        return {
            "name": tool_name,
            "description": description,
            "has_input_schema": bool(input_schema),
            "is_read_only_hint": read_only_hint,
            "approval_policy": policy,
            "metadata_source": "cached",
        }


def create_basil_mcp_proxy_inventory_server(
    *,
    inventory_service: BasilMcpProxyInventoryService | None = None,
) -> FastMCP:
    """Create the unmounted local MCP server used by later run-scoped lifecycle work."""
    service = inventory_service or BasilMcpProxyInventoryService()
    server = FastMCP(
        name="Basil MCP proxy inventory",
        instructions=(
            "Lists only currently enabled Basil connection tools allowed by existing policy. "
            "This server cannot invoke remote tools or access credentials."
        ),
    )

    @server.tool(
        name="basil_list_eligible_tools",
        description="List sanitized enabled Basil connection tools eligible for future proxy dispatch.",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def basil_list_eligible_tools() -> dict[str, object]:
        return service.list_eligible_tools()

    return server
