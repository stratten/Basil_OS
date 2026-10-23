"""Tests for shared external connection capability rendering + capture."""

from __future__ import annotations

from types import SimpleNamespace

from api.services.agent_processing.tools.external_services import (
    external_connection_capability as cap,
)


def _record(**overrides):
    base = dict(server_name=None, server_instructions=None)
    base.update(overrides)
    return SimpleNamespace(**base)


def _item(**overrides):
    base = dict(
        connection_id="conn-1",
        friendly_name="Speakeasy - Custom",
        description=None,
        cached_tool_count=0,
        cached_tool_names=(),
        server_name=None,
        server_instructions=None,
        cached_tool_briefs=(),
        cached_action_tool_names=(),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# --- apply_server_metadata_to_record -------------------------------------------

def test_apply_server_metadata_sets_fields_and_reports_change():
    record = _record()
    changed = cap.apply_server_metadata_to_record(
        record, {"name": "salesforce-mcp", "instructions": "Use to read Salesforce."}
    )
    assert changed is True
    assert record.server_name == "salesforce-mcp"
    assert record.server_instructions == "Use to read Salesforce."


def test_apply_server_metadata_is_idempotent():
    record = _record(server_name="salesforce-mcp", server_instructions="Use to read Salesforce.")
    changed = cap.apply_server_metadata_to_record(
        record, {"name": "salesforce-mcp", "instructions": "Use to read Salesforce."}
    )
    assert changed is False
    assert record.server_name == "salesforce-mcp"


def test_apply_server_metadata_defensive_on_none_and_bad_values():
    record = _record()
    assert cap.apply_server_metadata_to_record(record, None) is False
    assert cap.apply_server_metadata_to_record(record, "not-a-dict") is False
    # Missing keys and non-string / blank values must not mutate.
    assert cap.apply_server_metadata_to_record(record, {}) is False
    assert cap.apply_server_metadata_to_record(record, {"name": 123, "instructions": ""}) is False
    assert record.server_name is None
    assert record.server_instructions is None


def test_apply_server_metadata_strips_whitespace():
    record = _record()
    assert cap.apply_server_metadata_to_record(record, {"name": "  sf  "}) is True
    assert record.server_name == "sf"


# --- connection_routing_label --------------------------------------------------

def test_routing_label_includes_informative_server_name():
    item = _item(server_name="salesforce-mcp")
    assert cap.connection_routing_label(item) == "Speakeasy - Custom (salesforce-mcp)"


def test_routing_label_omits_redundant_server_name():
    item = _item(friendly_name="Salesforce", server_name="salesforce")
    assert cap.connection_routing_label(item) == "Salesforce"

    item_none = _item(server_name=None)
    assert cap.connection_routing_label(item_none) == "Speakeasy - Custom"


# --- render_connection_capability_block ----------------------------------------

def test_render_block_full_shape():
    item = _item(
        cached_tool_count=2,
        description="Primary Salesforce production org.",
        server_name="salesforce-mcp",
        server_instructions="Read and write Salesforce records.",
        cached_tool_briefs=(
            ("sf_query", "Query Salesforce records."),
            ("sf_update", "Update a Salesforce record."),
        ),
    )
    block = cap.render_connection_capability_block(item)

    assert block.splitlines()[0] == "- Speakeasy - Custom (connection_id=conn-1, cached_tools=2)"
    assert "  description: Primary Salesforce production org." in block
    assert "  server: salesforce-mcp" in block
    assert "  guidance: Read and write Salesforce records." in block
    assert "  tools: sf_query: Query Salesforce records.; sf_update: Update a Salesforce record." in block


def test_render_block_falls_back_to_names_without_descriptions():
    item = _item(
        cached_tool_count=2,
        cached_tool_names=("a_tool", "b_tool"),
        cached_tool_briefs=(("a_tool", None), ("b_tool", None)),
    )
    block = cap.render_connection_capability_block(item)
    assert "  tools: a_tool; b_tool" in block
    # No server/guidance lines when those fields are absent.
    assert "server:" not in block
    assert "guidance:" not in block


def test_render_block_no_tools_uses_refresh_hint():
    item = _item(cached_tool_count=0)
    block = cap.render_connection_capability_block(item)
    assert "tools: tool list not cached yet; call describe_server to refresh" in block


def test_render_block_truncates_and_counts_remainder():
    long_desc = "Z" * 500
    briefs = tuple((f"tool_{i}", long_desc) for i in range(12))
    item = _item(cached_tool_count=12, cached_tool_briefs=briefs)
    block = cap.render_connection_capability_block(item)

    tool_line = next(line for line in block.splitlines() if line.strip().startswith("tools:"))
    # Only MAX_TOOLS_IN_BLOCK rendered; the rest summarized as "… N more".
    assert f"… {12 - cap.MAX_TOOLS_IN_BLOCK} more" in tool_line
    assert "…" in tool_line  # description truncation marker present too


# --- actions line (write-capable tools) ----------------------------------------

def test_render_block_includes_actions_line_for_write_tools():
    item = _item(
        cached_tool_count=4,
        cached_tool_briefs=(
            ("speakeasy_list_requests", "List requests."),
            ("speakeasy_create_request", "Create a request."),
        ),
        cached_action_tool_names=("speakeasy_create_request", "speakeasy_run_recipe"),
    )
    block = cap.render_connection_capability_block(item)
    assert (
        "  actions: speakeasy_create_request, speakeasy_run_recipe (require approval)"
        in block
    )


def test_render_block_omits_actions_line_when_read_only_only():
    item = _item(
        cached_tool_count=2,
        cached_tool_briefs=(("r_one", "Read one."), ("r_two", "Read two.")),
        cached_action_tool_names=(),
    )
    block = cap.render_connection_capability_block(item)
    assert "actions:" not in block


def test_render_block_bounds_actions_line():
    names = tuple(f"act_{i}" for i in range(12))
    item = _item(cached_tool_count=12, cached_action_tool_names=names)
    block = cap.render_connection_capability_block(item)

    action_line = next(
        line for line in block.splitlines() if line.strip().startswith("actions:")
    )
    assert f"… {12 - cap.MAX_ACTIONS_IN_BLOCK} more" in action_line
    assert action_line.endswith("(require approval)")
