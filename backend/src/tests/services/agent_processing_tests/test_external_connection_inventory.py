"""Tests for compact external connection inventory rendering."""

from __future__ import annotations

from types import SimpleNamespace

from api.services.agent_processing.tools.external_services import external_connection_inventory


def _fake_preferences():
    return SimpleNamespace(
        connections=SimpleNamespace(
            mcp_connections=[
                SimpleNamespace(
                    id="speakeasy-id",
                    friendly_name="Speakeasy - Custom",
                    description="Salesforce production org for support escalations.",
                    server_url="https://app.speakeasy.is/mcp",
                    enabled=True,
                    cached_tools=[
                        SimpleNamespace(name="speakeasy_list_requests"),
                        SimpleNamespace(name="speakeasy_get_request"),
                        SimpleNamespace(name="speakeasy_get_request_timeline"),
                    ],
                    access_token="must-not-appear",
                    refresh_token="must-not-appear",
                ),
                SimpleNamespace(
                    id="disabled-id",
                    friendly_name="Disabled Service",
                    server_url="https://disabled.example/mcp",
                    enabled=False,
                    cached_tools=[SimpleNamespace(name="disabled_tool")],
                ),
            ]
        )
    )


def test_enabled_external_connections_are_secret_free_and_enabled_only():
    items = external_connection_inventory.get_enabled_external_connections(
        preferences=_fake_preferences(),
        max_tool_names=2,
    )

    assert len(items) == 1
    assert items[0].connection_id == "speakeasy-id"
    assert items[0].friendly_name == "Speakeasy - Custom"
    assert items[0].description == "Salesforce production org for support escalations."
    assert items[0].cached_tool_count == 3
    assert items[0].cached_tool_names == ("speakeasy_list_requests", "speakeasy_get_request")

    as_text = str(external_connection_inventory.inventory_as_dicts(items))
    assert "Disabled Service" not in as_text
    assert "must-not-appear" not in as_text


def test_connection_name_routing_summary_lists_enabled_connections_only():
    summary = external_connection_inventory.render_connection_names_for_routing(
        preferences=_fake_preferences(),
    )

    assert summary == "Speakeasy - Custom"


def test_connection_inventory_description_preserves_current_connections_shape():
    description = external_connection_inventory.render_connection_inventory_for_description(
        preferences=_fake_preferences(),
        max_tool_names=2,
    )

    assert description.startswith("**CURRENT CONNECTIONS:**")
    # Header line shape is preserved (friendly_name + connection_id + count).
    assert "- Speakeasy - Custom (connection_id=speakeasy-id, cached_tools=3)" in description
    assert "description: Salesforce production org for support escalations." in description
    # Tools render on their own bounded line. With no cached descriptions we
    # fall back to bare names, separated by "; ", with a "more" remainder.
    assert "tools: speakeasy_list_requests; speakeasy_get_request; … 1 more" in description
    assert "Disabled Service" not in description
    assert "must-not-appear" not in description


def _enriched_preferences():
    long_desc = (
        "Query and update Salesforce CRM records including Leads, Contacts, and "
        "Opportunities for the connected org. " + ("x" * 200)
    )
    return SimpleNamespace(
        connections=SimpleNamespace(
            mcp_connections=[
                SimpleNamespace(
                    id="speakeasy-id",
                    friendly_name="Speakeasy - Custom",
                    description="Primary Salesforce production org for escalations.",
                    server_url="https://app.speakeasy.is/mcp",
                    enabled=True,
                    server_name="salesforce-mcp",
                    server_instructions=(
                        "Use these tools to read and write Salesforce records. " + ("y" * 400)
                    ),
                    cached_tools=[
                        SimpleNamespace(name="sf_query", description=long_desc),
                        SimpleNamespace(name="sf_update", description="Update a Salesforce record."),
                    ],
                    access_token="must-not-appear",
                ),
            ]
        )
    )


def test_connection_inventory_surfaces_server_and_tool_descriptions():
    description = external_connection_inventory.render_connection_inventory_for_description(
        preferences=_enriched_preferences(),
    )

    # Server identity and guidance surface so the model can recognize Salesforce.
    assert "description: Primary Salesforce production org for escalations." in description
    assert "server: salesforce-mcp" in description
    assert "guidance: Use these tools to read and write Salesforce records." in description
    # Tool descriptions surface (truncated), proving the domain signal is present.
    assert "sf_query: Query and update Salesforce CRM records" in description
    assert "sf_update: Update a Salesforce record." in description
    # Secrets never leak.
    assert "must-not-appear" not in description


def test_connection_inventory_bounds_long_text():
    from api.services.agent_processing.tools.external_services import (
        external_connection_capability,
    )

    description = external_connection_inventory.render_connection_inventory_for_description(
        preferences=_enriched_preferences(),
    )

    guidance_line = next(
        line for line in description.splitlines() if line.strip().startswith("guidance:")
    )
    description_line = next(
        line for line in description.splitlines() if line.strip().startswith("description:")
    )
    tool_line = next(
        line for line in description.splitlines() if line.strip().startswith("tools:")
    )
    # Truncated content carries the ellipsis marker and respects the bounds
    # (plus the small "guidance: "/"sf_query: " label prefixes and the marker).
    assert "…" in guidance_line
    assert len(guidance_line) <= external_connection_capability.MAX_INSTRUCTIONS_CHARS + 16
    assert len(description_line) <= external_connection_capability.MAX_USER_DESCRIPTION_CHARS + 16
    assert "…" in tool_line


def test_enabled_connection_routing_labels_include_served_system():
    labels = external_connection_inventory.enabled_connection_routing_labels(
        preferences=_enriched_preferences(),
    )
    assert labels == ["Speakeasy - Custom (salesforce-mcp)"]

    # Without a captured server name the label is just the friendly name.
    plain_labels = external_connection_inventory.enabled_connection_routing_labels(
        preferences=_fake_preferences(),
    )
    assert plain_labels == ["Speakeasy - Custom"]


def _mixed_read_action_preferences():
    """Read tools first, action tools sorted PAST a small max_tool_names bound."""
    return SimpleNamespace(
        connections=SimpleNamespace(
            mcp_connections=[
                SimpleNamespace(
                    id="speakeasy-id",
                    friendly_name="Speakeasy - Custom",
                    server_url="https://app.speakeasy.is/mcp",
                    enabled=True,
                    cached_tools=[
                        SimpleNamespace(name="speakeasy_list_requests", is_read_only_hint=True),
                        SimpleNamespace(name="speakeasy_get_request", is_read_only_hint=True),
                        SimpleNamespace(name="speakeasy_create_request", is_read_only_hint=False),
                        SimpleNamespace(name="speakeasy_run_recipe", is_read_only_hint=False),
                    ],
                    access_token="must-not-appear",
                ),
            ]
        )
    )


def test_action_tool_names_derived_from_read_only_hint_beyond_name_bound():
    items = external_connection_inventory.get_enabled_external_connections(
        preferences=_mixed_read_action_preferences(),
        max_tool_names=2,
    )
    item = items[0]
    # Display names honor the bound...
    assert item.cached_tool_names == ("speakeasy_list_requests", "speakeasy_get_request")
    # ...but action names come from the FULL cached list, so the write tools
    # surface even though they sort past max_tool_names.
    assert item.cached_action_tool_names == (
        "speakeasy_create_request",
        "speakeasy_run_recipe",
    )


def test_connection_inventory_description_includes_actions_line():
    description = external_connection_inventory.render_connection_inventory_for_description(
        preferences=_mixed_read_action_preferences(),
        max_tool_names=2,
    )
    assert (
        "actions: speakeasy_create_request, speakeasy_run_recipe (require approval)"
        in description
    )
    assert "must-not-appear" not in description
