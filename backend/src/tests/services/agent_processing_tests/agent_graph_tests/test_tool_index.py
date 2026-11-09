"""Tests for the compact tool index rendered in the staged loader's description."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_index import (
    TOOL_INDEX_INTRO,
    render_tool_index,
    tool_signature,
)


class _NoArguments(BaseModel):
    pass


class _EmailSearch(BaseModel):
    action: Literal["list", "get"]
    query: str
    limit: int = 10


class _ProviderCall(BaseModel):
    operation: Literal["read", "write"] | None = None
    provider: str


class _BrokenSchema:
    @classmethod
    def model_json_schema(cls) -> dict:
        raise RuntimeError("schema cannot be built")


def _tool(name: str, args_schema=None):
    return SimpleNamespace(name=name, description=f"{name} description", args_schema=args_schema)


def test_signature_lists_required_arguments_only():
    assert tool_signature(_tool("email_service_get_emails", _EmailSearch)) == "email_service_get_emails(action=list|get, query)"


def test_signature_for_a_tool_without_required_arguments_has_empty_parentheses():
    assert tool_signature(_tool("browser_inspect", _NoArguments)) == "browser_inspect()"


def test_signature_for_a_tool_without_a_schema_has_empty_parentheses():
    assert tool_signature(_tool("browser_inspect")) == "browser_inspect()"


def test_signature_tolerates_a_schema_that_cannot_be_built():
    assert tool_signature(_tool("browser_inspect", _BrokenSchema)) == "browser_inspect()"


def test_signature_does_not_list_an_optional_enumeration():
    signature = tool_signature(_tool("provider_catalog_call", _ProviderCall))

    assert signature == "provider_catalog_call(provider)"


def test_index_lists_each_family_with_its_tools_and_leads_with_the_intro():
    index = render_tool_index([_tool("browser_inspect", _NoArguments), _tool("email_service_get_emails", _EmailSearch)])

    assert index.startswith(TOOL_INDEX_INTRO)
    assert "\n- browser:" in index
    assert "browser_inspect()" in index
    assert "\n- email:" in index
    assert "email_service_get_emails(action=list|get, query)" in index


def test_index_leaves_out_excluded_families():
    tools = [_tool("browser_inspect", _NoArguments), _tool("shell_service_execute_command", _NoArguments)]

    index = render_tool_index(tools, exclude_names=["shell", "core"])

    assert "\n- browser:" in index
    assert "shell_service_execute_command" not in index
    assert "\n- shell:" not in index


def test_index_for_no_tools_is_only_the_intro():
    assert render_tool_index([]) == TOOL_INDEX_INTRO


def test_index_skips_a_tool_no_family_owns():
    index = render_tool_index([_tool("mystery_helper", _NoArguments)])

    assert "mystery_helper" not in index


def test_index_states_connected_services_and_the_connector_first_rule(monkeypatch):
    from api.services.agent_processing.tools.external_services import external_connection_inventory

    fake_preferences = SimpleNamespace(
        connections=SimpleNamespace(
            mcp_connections=[
                SimpleNamespace(
                    id="gmail-id",
                    friendly_name="Gmail - Basil",
                    server_url="https://gmail.example/mcp",
                    enabled=True,
                    cached_tools=[],
                ),
            ]
        )
    )
    monkeypatch.setattr(external_connection_inventory, "_load_preferences", lambda: fake_preferences)

    index = render_tool_index([_tool("browser_inspect", _NoArguments)])

    assert "Currently enabled external services: Gmail - Basil." in index
    assert "A connected service is the first route for any request it can serve" in index


def test_index_omits_the_connected_service_line_when_none_is_enabled(monkeypatch):
    from api.services.agent_processing.tools.external_services import external_connection_inventory

    monkeypatch.setattr(
        external_connection_inventory,
        "_load_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=[])),
    )

    assert "Currently enabled external services" not in render_tool_index([_tool("browser_inspect", _NoArguments)])


def _enable_connections(monkeypatch, *friendly_names: str) -> None:
    from api.services.agent_processing.tools.external_services import external_connection_inventory

    records = [
        SimpleNamespace(id=f"conn-{position}", friendly_name=name, server_url=f"https://example.test/{position}", enabled=True, cached_tools=[])
        for position, name in enumerate(friendly_names, start=1)
    ]
    monkeypatch.setattr(
        external_connection_inventory,
        "_load_preferences",
        lambda: SimpleNamespace(connections=SimpleNamespace(mcp_connections=records)),
    )


def _lines(index: str) -> list[str]:
    return index.split("\n")


def test_index_adds_a_connected_mail_entry_ahead_of_the_local_email_line(monkeypatch):
    _enable_connections(monkeypatch, "Gmail - Basil", "Slack")
    tools = [_tool("email_service_get_emails", _EmailSearch), _tool("external_catalog", _NoArguments)]

    lines = _lines(render_tool_index(tools))

    entry = next(line for line in lines if line.startswith("- connected mail"))
    assert "Gmail and other mailboxes you have connected: Gmail - Basil" in entry
    assert "to search or read email in any of these accounts, call external_catalog" in entry
    assert "Slack" not in entry
    assert "external_catalog(action=list_servers|describe_server|call_tool)" in entry
    # The entry leads the family lines, ahead of the local email family, so a small model reads it before any email tool name.
    family_lines = [line for line in lines if line.startswith("- ")]
    assert family_lines[0] == entry
    assert lines.index(entry) < next(position for position, line in enumerate(lines) if line.startswith("- email:"))


def test_index_describes_the_local_email_family_as_the_mail_app_and_outlook_only(monkeypatch):
    _enable_connections(monkeypatch, "Gmail - Basil")

    index = render_tool_index([_tool("email_service_get_emails", _EmailSearch), _tool("external_catalog", _NoArguments)])

    email_line = next(line for line in _lines(index) if line.startswith("- email:"))
    assert "in the Mail app or Outlook on this Mac (not Gmail or other connected mailboxes)" in email_line
    external_line = next(line for line in _lines(index) if line.startswith("- external:"))
    assert "including connected Gmail and other mail, calendar, and file accounts" in external_line


def test_index_counts_an_outlook_connection_as_a_mailbox(monkeypatch):
    _enable_connections(monkeypatch, "Work Outlook")

    index = render_tool_index([_tool("email_service_get_emails", _EmailSearch), _tool("external_catalog", _NoArguments)])

    assert any(line.startswith("- connected mail") and "Work Outlook" in line for line in _lines(index))


def test_index_leaves_out_the_connected_mail_entry_when_no_connection_is_a_mailbox(monkeypatch):
    _enable_connections(monkeypatch, "Slack", "GitHub")

    index = render_tool_index([_tool("email_service_get_emails", _EmailSearch), _tool("external_catalog", _NoArguments)])

    assert not any(line.startswith("- connected mail") for line in _lines(index))


def test_index_leaves_out_the_connected_mail_entry_when_external_catalog_is_not_registered(monkeypatch):
    _enable_connections(monkeypatch, "Gmail - Basil")

    index = render_tool_index([_tool("email_service_get_emails", _EmailSearch)])

    assert not any(line.startswith("- connected mail") for line in _lines(index))


def test_index_leaves_out_the_connected_mail_entry_when_the_external_family_is_excluded(monkeypatch):
    _enable_connections(monkeypatch, "Gmail - Basil")

    index = render_tool_index([_tool("email_service_get_emails", _EmailSearch), _tool("external_catalog", _NoArguments)], exclude_names=["external"])

    assert not any(line.startswith("- connected mail") for line in _lines(index))


def test_index_leads_with_the_connected_mail_entry_when_the_email_family_has_no_tools(monkeypatch):
    _enable_connections(monkeypatch, "Gmail - Basil")

    lines = _lines(render_tool_index([_tool("browser_inspect", _NoArguments), _tool("external_catalog", _NoArguments)]))

    assert next(line for line in lines if line.startswith("- ")).startswith("- connected mail")
    assert not any(line.startswith("- email:") for line in lines)


def test_index_prints_the_browser_note_after_the_browser_tools():
    index = render_tool_index([_tool("browser_inspect", _NoArguments)])

    browser_line = next(line for line in _lines(index) if line.startswith("- browser:"))
    assert browser_line.index("browser_inspect()") < browser_line.index("Use these, not AppleScript or the shell")
    assert browser_line.endswith("even when a browser is already open on screen.")


def test_index_prints_no_note_for_a_family_without_one():
    index = render_tool_index([_tool("email_service_get_emails", _EmailSearch)])

    email_line = next(line for line in _lines(index) if line.startswith("- email:"))
    assert email_line.endswith("email_service_get_emails(action=list|get, query)")
