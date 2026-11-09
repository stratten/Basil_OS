"""The agent prompt must send Gmail work to a connected Gmail connection first, and always when the user names it, without forbidding the Mail app."""

from __future__ import annotations

from api.services.agent_processing.lifecycle.execution_graph.system_prompts import AGENT_SYSTEM_PROMPT_TEMPLATE


def _email_guidance() -> str:
    lines = [line for line in AGENT_SYSTEM_PROMPT_TEMPLATE.splitlines() if line.startswith("- For email operations")]
    assert len(lines) == 1
    return lines[0]


def test_gmail_connection_is_named_as_the_first_route_for_mailbox_work():
    guidance = _email_guidance()
    assert "connected Gmail connection" in guidance
    assert "external_catalog" in guidance
    assert "unlabel_thread" in guidance
    assert "take over Mail's windows" in guidance
    assert "use that connection first" in guidance
    assert "needs no approval" in guidance
    assert "reading, searching, archiving" in guidance


def test_a_user_who_names_the_connection_always_gets_it():
    assert "Always use it when the user names the connection" in _email_guidance()


def test_the_mail_app_is_no_longer_called_the_general_default():
    assert "general default" not in _email_guidance()


def test_the_general_service_tool_line_defers_to_a_connected_service():
    lines = [line for line in AGENT_SYSTEM_PROMPT_TEMPLATE.splitlines() if line.startswith("- Specialized service tools")]
    assert len(lines) == 1
    assert "unless a connected service already covers the work" in lines[0]
    assert "not your only option" in lines[0]


def test_the_guidance_keeps_the_mail_app_available_and_allows_mixing_routes():
    guidance = _email_guidance()
    assert "Use email_service tools (the Mail app) for mailboxes that have no connection" in guidance
    assert "mix routes" in guidance
    assert "drafts in Mail" in guidance
    assert "do not abandon either route" in guidance


def test_the_guidance_does_not_forbid_any_route():
    guidance = _email_guidance().lower()
    for forbidden in ("never use email_service", "never use the mail app", "must use the gmail connection", "only use the gmail connection"):
        assert forbidden not in guidance


def _prompt_with_connections(monkeypatch, labels):
    from api.services.agent_processing.lifecycle.execution_graph import system_prompts
    from api.services.agent_processing.tools.external_services import external_connection_inventory

    monkeypatch.setattr(external_connection_inventory, "enabled_connection_routing_labels", lambda: list(labels))
    monkeypatch.setattr(system_prompts, "build_working_memory_prompt_section", lambda: "")
    monkeypatch.setattr(system_prompts, "build_skill_catalog_prompt_section", lambda: "")
    monkeypatch.setattr(system_prompts, "build_screen_context_prompt_section", lambda: "")
    return system_prompts.get_agent_system_prompt()


def test_the_connector_first_rule_sits_at_the_start_of_the_system_prompt(monkeypatch):
    prompt = _prompt_with_connections(monkeypatch, ["Gmail - Basil (basil-gmail-api)", "Linear (Linear MCP)"])

    opening = "You are an AI assistant that executes tasks using available tools."
    assert prompt.startswith(opening)
    assert prompt.index("CONNECTED SERVICES (check these first):") < prompt.index("EXECUTION PRINCIPLES:")
    assert prompt.index("CONNECTED SERVICES (check these first):") == len(opening) + 2
    assert "Enabled connections: Gmail - Basil (basil-gmail-api), Linear (Linear MCP)." in prompt


def test_the_rule_covers_a_request_that_does_not_name_the_service(monkeypatch):
    prompt = _prompt_with_connections(monkeypatch, ["Gmail - Basil (basil-gmail-api)"])

    assert "including a request that does not name the service" in prompt
    assert "starts with the mail connections, not the Mail app" in prompt
    assert "Use a local app tool instead only when the user names that app, or a connection fails or does not cover the work." in prompt


def test_several_connections_of_one_kind_are_all_queried_and_compared(monkeypatch):
    prompt = _prompt_with_connections(monkeypatch, ["Gmail - Baobab (basil-gmail-api)", "Gmail - Basil (basil-gmail-api)", "Gmail - Speakeasy (basil-gmail-api)"])

    assert "query each of them, compare the results, and report the true answer across all of them, naming the account it came from" in prompt


def test_no_connection_means_no_connector_block_and_no_blank_line_gap(monkeypatch):
    prompt = _prompt_with_connections(monkeypatch, [])

    assert "CONNECTED SERVICES" not in prompt
    assert "\n\n\n" not in prompt
    assert prompt.startswith("You are an AI assistant that executes tasks using available tools.\n\nEXECUTION PRINCIPLES:")


def test_a_failing_connection_inventory_leaves_the_prompt_intact(monkeypatch):
    from api.services.agent_processing.lifecycle.execution_graph import system_prompts
    from api.services.agent_processing.tools.external_services import external_connection_inventory

    def broken():
        raise RuntimeError("preferences unavailable")

    monkeypatch.setattr(external_connection_inventory, "enabled_connection_routing_labels", broken)
    monkeypatch.setattr(system_prompts, "build_working_memory_prompt_section", lambda: "")
    monkeypatch.setattr(system_prompts, "build_skill_catalog_prompt_section", lambda: "")
    monkeypatch.setattr(system_prompts, "build_screen_context_prompt_section", lambda: "")

    assert "CONNECTED SERVICES" not in system_prompts.get_agent_system_prompt()
