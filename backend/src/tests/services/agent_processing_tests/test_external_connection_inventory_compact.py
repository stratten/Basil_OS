"""Tests for the shared-body external connection inventory embedded in the external_catalog description."""

from __future__ import annotations

from types import SimpleNamespace

from api.services.agent_processing.tools.external_services import external_connection_inventory
from api.services.agent_processing.tools.external_services.external_catalog import descriptions

TOOL_DESCRIPTION = "Lists the threads that match a query, newest first, for the signed-in account only."


def _tool(name: str, *, read_only: bool = True, description: str = TOOL_DESCRIPTION) -> SimpleNamespace:
    return SimpleNamespace(name=name, description=description, is_read_only_hint=read_only)


def _record(
    connection_id: str,
    friendly_name: str,
    description: str | None,
    tools: list[SimpleNamespace],
    *,
    server_name: str = "shared-server",
    instructions: str | None = "Guidance for the shared server.",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=connection_id,
        friendly_name=friendly_name,
        description=description,
        server_url="https://example.test/mcp",
        enabled=True,
        server_name=server_name,
        server_instructions=instructions,
        cached_tools=tools,
        access_token="must-not-appear",
    )


def _preferences(*records: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(connections=SimpleNamespace(mcp_connections=list(records)))


def _gmail_tools() -> list[SimpleNamespace]:
    return [_tool("search_threads"), _tool("get_thread"), _tool("create_draft", read_only=False)]


def _render(preferences: SimpleNamespace, *, compact: bool) -> str:
    return external_connection_inventory.render_connection_inventory_for_description(preferences=preferences, compact=compact)


def test_a_connection_that_shares_nothing_renders_exactly_as_the_default_form_does():
    preferences = _preferences(
        _record("a-id", "Alpha", "The alpha account.", _gmail_tools(), server_name="alpha-server"),
        _record("b-id", "Beta", None, [_tool("beta_tool")], server_name="beta-server", instructions=None),
    )

    assert _render(preferences, compact=True) == _render(preferences, compact=False)
    assert _render(preferences, compact=True).startswith("**CURRENT CONNECTIONS:**")
    assert f"search_threads: {TOOL_DESCRIPTION}" in _render(preferences, compact=True)
    assert "must-not-appear" not in _render(preferences, compact=True)


def test_connections_to_one_server_share_one_body_and_keep_their_own_identity():
    preferences = _preferences(
        _record("one", "Gmail - One", "One - Owner", _gmail_tools()),
        _record("two", "Gmail - Two", "Two - Owner", _gmail_tools()),
        _record("three", "Gmail - Three", "Three - Owner", _gmail_tools()),
    )

    compact = _render(preferences, compact=True)
    full = _render(preferences, compact=False)

    assert compact.count("  tools:") == 1
    assert compact.count("  guidance:") == 1
    assert compact.count("  actions:") == 1
    assert compact.count(f"search_threads: {TOOL_DESCRIPTION}") == 1
    assert full.count(f"search_threads: {TOOL_DESCRIPTION}") == 3
    for connection_id, label in (("one", "One - Owner"), ("two", "Two - Owner"), ("three", "Three - Owner")):
        assert f"(connection_id={connection_id}, cached_tools=3)" in compact
        assert f"description: {label}" in compact
    assert "separate accounts on one server" in compact
    assert len(compact) < len(full)


def test_every_line_of_the_default_form_is_still_present_when_a_body_is_shared():
    preferences = _preferences(
        _record("one", "Gmail - One", "One - Owner", _gmail_tools()),
        _record("two", "Gmail - Two", "Two - Owner", _gmail_tools()),
    )

    compact_lines = set(_render(preferences, compact=True).splitlines())

    assert set(_render(preferences, compact=False).splitlines()) <= compact_lines


def test_connections_whose_tool_descriptions_differ_do_not_share_a_body():
    preferences = _preferences(
        _record("one", "Gmail - One", None, [_tool("search_threads", description="Searches the older index.")]),
        _record("two", "Gmail - Two", None, [_tool("search_threads", description="Searches the current index.")]),
    )

    text = _render(preferences, compact=True)

    assert text == _render(preferences, compact=False)
    assert text.count("  tools:") == 2
    assert "separate accounts on one server" not in text


def test_connections_with_different_tools_do_not_share_a_body():
    text = _render(
        _preferences(
            _record("one", "First", None, [_tool("first_tool")]),
            _record("two", "Second", None, [_tool("second_tool")]),
        ),
        compact=True,
    )

    assert text.count("  tools:") == 2
    assert "separate accounts on one server" not in text


def test_connections_without_cached_tools_are_never_grouped():
    text = _render(_preferences(_record("one", "First", None, []), _record("two", "Second", None, [])), compact=True)

    assert text.count("tool list not cached yet; call describe_server to refresh") == 2
    assert "separate accounts on one server" not in text


def test_the_shared_form_counts_the_tools_it_does_not_name_exactly_as_the_default_form_does():
    many = [_tool(f"tool_{index:02d}") for index in range(15)]
    preferences = _preferences(_record("many", "Many", None, many))

    text = _render(preferences, compact=True)

    assert text == _render(preferences, compact=False)
    assert "; … 7 more" in text


def test_no_connections_message_is_unchanged_in_both_forms():
    empty = _preferences()
    expected = "**CURRENT CONNECTIONS:** No enabled external connections are currently registered."

    assert _render(empty, compact=False) == expected
    assert _render(empty, compact=True) == expected


def test_external_catalog_description_uses_the_shared_form(monkeypatch):
    preferences = _preferences(
        _record("one", "Gmail - One", "One - Owner", _gmail_tools()),
        _record("two", "Gmail - Two", "Two - Owner", _gmail_tools()),
    )
    monkeypatch.setattr(external_connection_inventory, "_load_preferences", lambda: preferences)

    text = descriptions.format_connection_inventory_for_description()

    assert text.startswith("**CURRENT CONNECTIONS:**")
    assert "separate accounts on one server" in text
    assert f"search_threads: {TOOL_DESCRIPTION}" in text
