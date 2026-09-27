"""Tests for staged tool-family catalog behavior."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from langchain_classic.schema import AgentAction

from api.services.agent_processing.lifecycle.execution_graph.service_tools import ServiceToolFactory
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.optional_tool_registry import (
    should_register_provider_catalog,
)
from api.services.agent_processing.lifecycle.execution_graph.service_tooling.tool_family_catalog import (
    create_load_tool_family_tool,
    describe_tool_families,
    extract_loaded_families_from_steps,
    extract_repair_families_from_steps,
    extract_suggested_families_from_loader_observation,
    family_for_tool_name,
    get_family_names,
    normalize_family_load_request,
    render_family_routing_catalog,
    select_core_tools,
    select_tools_for_families,
)


def _tool(name: str):
    return SimpleNamespace(name=name, description=f"{name} description", args_schema=None)


def test_family_catalog_exposes_stable_metadata():
    family_names = get_family_names()

    assert "core" in family_names
    assert "file" in family_names
    assert "email" in family_names
    assert "browser" in family_names
    assert "vision" in family_names
    assert "schedule" in family_names
    assert "provider" in family_names

    descriptions = describe_tool_families()
    browser = next(item for item in descriptions if item["name"] == "browser")
    assert browser["purpose"]
    assert browser["when_to_load"]
    assert browser["examples"]
    assert browser["routing_hints"]
    assert browser["risk_class"]


def test_family_routing_catalog_includes_connected_external_services(monkeypatch):
    from api.services.agent_processing.tools.external_services import external_connection_inventory

    fake_preferences = SimpleNamespace(
        connections=SimpleNamespace(
            mcp_connections=[
                SimpleNamespace(
                    id="speakeasy-id",
                    friendly_name="Speakeasy - Custom",
                    server_url="https://app.speakeasy.is/mcp",
                    enabled=True,
                    cached_tools=[SimpleNamespace(name="speakeasy_list_requests")],
                ),
                SimpleNamespace(
                    id="disabled-id",
                    friendly_name="Disabled Service",
                    server_url="https://disabled.example/mcp",
                    enabled=False,
                    cached_tools=[],
                ),
            ]
        )
    )
    monkeypatch.setattr(external_connection_inventory, "_load_preferences", lambda: fake_preferences)

    descriptions = describe_tool_families()
    external = next(item for item in descriptions if item["name"] == "external")
    browser = next(item for item in descriptions if item["name"] == "browser")
    catalog = render_family_routing_catalog()

    assert external["connected_services"] == ["Speakeasy - Custom"]
    assert "Speakeasy - Custom" in external["when_to_load"]
    assert "Speakeasy - Custom" in catalog
    assert "Disabled Service" not in catalog
    assert "connected third-party services" in external["routing_hints"]
    assert "not configured service records" in browser["routing_hints"]
    assert "connected_services" not in browser


def test_family_routing_catalog_labels_connection_with_served_system(monkeypatch):
    from api.services.agent_processing.tools.external_services import external_connection_inventory

    fake_preferences = SimpleNamespace(
        connections=SimpleNamespace(
            mcp_connections=[
                SimpleNamespace(
                    id="speakeasy-id",
                    friendly_name="Speakeasy - Custom",
                    server_url="https://app.speakeasy.is/mcp",
                    enabled=True,
                    server_name="salesforce-mcp",
                    server_instructions="Read and write Salesforce records.",
                    cached_tools=[SimpleNamespace(name="sf_query", description="Query Salesforce.")],
                ),
            ]
        )
    )
    monkeypatch.setattr(external_connection_inventory, "_load_preferences", lambda: fake_preferences)

    descriptions = describe_tool_families()
    external = next(item for item in descriptions if item["name"] == "external")
    catalog = render_family_routing_catalog()

    # First-pass routing now sees which system the connection serves.
    assert external["connected_services"] == ["Speakeasy - Custom (salesforce-mcp)"]
    assert "Speakeasy - Custom (salesforce-mcp)" in external["when_to_load"]
    assert "Speakeasy - Custom (salesforce-mcp)" in catalog


def test_loader_description_contains_family_routing_catalog(monkeypatch):
    from api.services.agent_processing.tools.external_services import external_connection_inventory

    fake_preferences = SimpleNamespace(
        connections=SimpleNamespace(
            mcp_connections=[
                SimpleNamespace(
                    id="speakeasy-id",
                    friendly_name="Speakeasy - Custom",
                    server_url="https://app.speakeasy.is/mcp",
                    enabled=True,
                    cached_tools=[],
                ),
            ]
        )
    )
    monkeypatch.setattr(external_connection_inventory, "_load_preferences", lambda: fake_preferences)

    loader = create_load_tool_family_tool([_tool("external_catalog")])

    assert "Available tool families for first-pass routing" in loader.description
    assert "external:" in loader.description
    assert "Speakeasy - Custom" in loader.description
    assert "browser:" in loader.description


def test_core_surface_keeps_loader_and_collaborative_tools_only():
    all_tools = [
        _tool("request_user_input"),
        _tool("skill_search"),
        _tool("skill_load"),
        _tool("applescript_service_generate_and_execute_applescript"),
        _tool("shell_service_execute_command"),
        _tool("browser_inspect"),
        _tool("file_service_read_file"),
    ]
    loader = _tool("load_tool_family")

    core_tools = select_core_tools(all_tools, loader)
    core_names = [tool.name for tool in core_tools]

    assert core_names == [
        "load_tool_family",
        "request_user_input",
        "skill_search",
        "skill_load",
        "applescript_service_generate_and_execute_applescript",
        "shell_service_execute_command",
    ]
    assert "browser_inspect" not in core_names
    assert "file_service_read_file" not in core_names


def test_provider_catalog_has_a_distinct_non_authorizing_family():
    descriptions = describe_tool_families()
    provider = next(item for item in descriptions if item["name"] == "provider")

    assert provider["risk_class"] == "durable non-authorizing provider proposal and target authorization"
    assert "ACP providers" in provider["routing_hints"]
    assert "target authorization checkpoint" in provider["routing_hints"]
    assert family_for_tool_name("provider_catalog") == "provider"
    assert family_for_tool_name("external_catalog") == "external"


def test_todo_tools_are_discoverable_and_loadable_as_a_dedicated_family():
    todo_tools = [
        _tool("create_todos"),
        _tool("list_todos"),
        _tool("inspect_todo"),
        _tool("append_todo_note"),
        _tool("delegate_todo_work"),
    ]

    assert "todos" in get_family_names()
    assert family_for_tool_name("append_todo_note") == "todos"
    assert normalize_family_load_request(["append_todo_note"]).mapped_families == ["todos"]
    assert select_tools_for_families(todo_tools, ["todos"], include_core_tools=False) == todo_tools


@pytest.mark.asyncio
async def test_load_tool_family_exposes_provider_catalog_without_external_catalog():
    loader = create_load_tool_family_tool(
        [_tool("provider_catalog"), _tool("external_catalog")]
    )

    raw = await loader.ainvoke(
        {"family_names": ["provider"], "reason": "Need registered ACP providers"}
    )
    data = json.loads(raw)

    assert data["success"] is True
    assert data["loaded_families"] == ["provider"]
    assert data["tool_names_by_family"]["provider"] == ["provider_catalog"]


def test_recall_family_present():
    family_names = get_family_names()
    assert "recall" in family_names

    descriptions = describe_tool_families()
    recall = next(item for item in descriptions if item["name"] == "recall")
    assert recall["purpose"]
    assert recall["when_to_load"]
    assert family_for_tool_name("recall_agent_tasks") == "recall"
    assert family_for_tool_name("recall_conversations") == "recall"


def test_retrieval_family_keeps_chronological_history_query_available():
    retrieval_tools = [
        _tool("retrieve_basil_history"),
        _tool("query_unified_history"),
    ]

    selected = select_tools_for_families(
        retrieval_tools,
        ["retrieval"],
        include_core_tools=False,
    )

    assert family_for_tool_name("query_unified_history") == "retrieval"
    assert [tool.name for tool in selected] == [
        "retrieve_basil_history",
        "query_unified_history",
    ]


def test_recall_tool_is_in_core_surface():
    all_tools = [
        _tool("request_user_input"),
        _tool("skill_search"),
        _tool("skill_load"),
        _tool("recall_agent_tasks"),
        _tool("recall_conversations"),
        _tool("applescript_service_generate_and_execute_applescript"),
        _tool("shell_service_execute_command"),
        _tool("browser_inspect"),
    ]
    loader = _tool("load_tool_family")

    core_tools = select_core_tools(all_tools, loader)
    core_names = [tool.name for tool in core_tools]

    assert "recall_agent_tasks" in core_names
    assert "recall_conversations" in core_names


def test_family_selection_preserves_exact_tool_objects():
    browser_inspect = _tool("browser_inspect")
    browser_interact = _tool("browser_interact")
    file_read = _tool("file_service_read_file")
    loader = _tool("load_tool_family")

    selected = select_tools_for_families(
        [browser_inspect, browser_interact, file_read],
        ["browser"],
        include_core_tools=True,
        loader_tool=loader,
    )

    assert browser_inspect in selected
    assert browser_interact in selected
    assert file_read not in selected
    assert selected[0] is loader


def test_vision_tool_can_load_with_browser_or_vision_family():
    vision_tool = _tool("analyze_with_vision")

    browser_selected = select_tools_for_families(
        [vision_tool],
        ["browser"],
        include_core_tools=False,
    )
    vision_selected = select_tools_for_families(
        [vision_tool],
        ["vision"],
        include_core_tools=False,
    )

    assert browser_selected == [vision_tool]
    assert vision_selected == [vision_tool]


def test_family_load_normalization_maps_owned_tool_names_and_prefixes():
    normalized = normalize_family_load_request([
        "provider_catalog",
        "external_catalog",
        "email_service_search_emails",
        "browser_inspect",
        "speakeasy_list_requests",
    ])

    assert normalized.valid_families == []
    assert normalized.mapped_families == ["provider", "external", "email", "browser"]
    assert normalized.invalid_names == ["speakeasy_list_requests"]
    assert normalized.name_mappings["provider_catalog"] == ["provider"]
    assert normalized.name_mappings["external_catalog"] == ["external"]
    assert normalized.name_mappings["email_service_search_emails"] == ["email"]
    assert normalized.name_mappings["browser_inspect"] == ["browser"]


@pytest.mark.asyncio
async def test_load_tool_family_returns_structured_family_contract_summary():
    all_tools = [_tool("browser_inspect"), _tool("browser_interact")]
    loader = create_load_tool_family_tool(all_tools)

    assert loader.return_direct is True

    raw = await loader.ainvoke({"family_names": ["browser"], "reason": "Need page automation"})
    data = json.loads(raw)

    assert data["success"] is True
    assert data["loaded_families"] == ["browser"]
    assert data["invalid_families"] == []
    assert data["tool_names_by_family"]["browser"] == [
        "browser_inspect",
        "browser_interact",
    ]
    assert "Stop this executor pass now" in data["next_step"]
    assert "exact full schemas" in data["next_step"]


@pytest.mark.asyncio
async def test_load_tool_family_reports_already_available_when_family_bound():
    all_tools = [_tool("applescript_service_execute_applescript")]
    loader = create_load_tool_family_tool(all_tools, get_available_families=lambda: {"automation"})

    raw = await loader.ainvoke({"family_names": ["automation"], "reason": "Need AppleScript"})
    data = json.loads(raw)

    assert data["already_available_families"] == ["automation"]
    assert data["newly_loaded_families"] == []
    assert "ALREADY available" in data["next_step"]
    assert "Do NOT call load_tool_family" in data["next_step"]
    assert "applescript_service_execute_applescript" in data["next_step"]


@pytest.mark.asyncio
async def test_load_tool_family_still_restarts_for_newly_loaded_family_with_getter():
    all_tools = [_tool("browser_inspect")]
    loader = create_load_tool_family_tool(all_tools, get_available_families=lambda: {"automation", "shell"})

    raw = await loader.ainvoke({"family_names": ["browser"], "reason": "Need page automation"})
    data = json.loads(raw)

    assert data["newly_loaded_families"] == ["browser"]
    assert data["already_available_families"] == []
    assert "Stop this executor pass now" in data["next_step"]


@pytest.mark.asyncio
async def test_load_tool_family_accepts_json_string_family_list():
    loader = create_load_tool_family_tool([_tool("browser_inspect")])

    raw = await loader.ainvoke({"family_names": '["browser"]', "reason": "Need browser"})
    data = json.loads(raw)

    assert data["success"] is True
    assert data["loaded_families"] == ["browser"]
    assert data["requested_family_inputs"] == ["browser"]


@pytest.mark.asyncio
async def test_load_tool_family_accepts_bare_family_string():
    loader = create_load_tool_family_tool([_tool("browser_inspect")])

    raw = await loader.ainvoke({"family_names": "browser", "reason": "Need browser"})
    data = json.loads(raw)

    assert data["success"] is True
    assert data["loaded_families"] == ["browser"]
    assert data["requested_family_inputs"] == ["browser"]


@pytest.mark.asyncio
async def test_load_tool_family_rejects_json_object_family_string():
    """A JSON *object* string for family_names is a genuine shape error (list expected),
    distinct from the depth-fixup this normalizer applies to over-serialized lists.

    StructuredTool.ainvoke does not raise on this: every normalized tool has
    handle_validation_error=format_tool_validation_error attached (see
    tool_input_normalization.normalize_structured_tool_args_schema) precisely so a bad
    tool call becomes a recoverable observation the model can correct and retry, rather
    than an uncaught exception that crashes the whole run. Assert that contract here.
    """
    loader = create_load_tool_family_tool([_tool("browser_inspect")])

    raw = await loader.ainvoke({"family_names": '{"family":"browser"}', "reason": "Need browser"})

    assert "family_names" in raw
    assert "validation failed" in raw.lower()


@pytest.mark.asyncio
async def test_load_tool_family_maps_tool_name_to_family():
    all_tools = [_tool("external_catalog"), _tool("web_search")]
    loader = create_load_tool_family_tool(all_tools)

    raw = await loader.ainvoke({"family_names": ["external_catalog"], "reason": "Need remote connector"})
    data = json.loads(raw)

    assert data["success"] is True
    assert data["loaded_families"] == ["external"]
    assert data["invalid_families"] == []
    assert data["mapped_family_inputs"] == {"external_catalog": ["external"]}
    assert data["suggested_families"] == ["external"]
    assert data["tool_names_by_family"]["external"] == ["external_catalog", "web_search"]


@pytest.mark.asyncio
async def test_load_tool_family_maps_service_prefix_to_family():
    all_tools = [_tool("email_service_search_emails")]
    loader = create_load_tool_family_tool(all_tools)

    raw = await loader.ainvoke({"family_names": ["email_service_search_emails"], "reason": "Need email"})
    data = json.loads(raw)

    assert data["success"] is True
    assert data["loaded_families"] == ["email"]
    assert data["invalid_families"] == []
    assert data["mapped_family_inputs"] == {"email_service_search_emails": ["email"]}


@pytest.mark.asyncio
async def test_load_tool_family_does_not_map_remote_mcp_tool_names():
    loader = create_load_tool_family_tool([_tool("external_catalog")])

    raw = await loader.ainvoke({"family_names": ["speakeasy_list_requests"], "reason": "Remote MCP tool"})
    data = json.loads(raw)

    assert data["success"] is False
    assert data["loaded_families"] == []
    assert data["invalid_families"] == ["speakeasy_list_requests"]
    assert data["mapped_family_inputs"] == {}
    assert data["suggested_families"] == []


@pytest.mark.asyncio
async def test_load_tool_family_preserves_resolved_families_with_unresolved_inputs():
    loader = create_load_tool_family_tool([_tool("external_catalog")])

    raw = await loader.ainvoke({"family_names": ["external_catalog", "not_a_family"], "reason": "Mixed request"})
    data = json.loads(raw)

    assert data["success"] is False
    assert data["loaded_families"] == ["external"]
    assert data["invalid_families"] == ["not_a_family"]
    assert data["suggested_families"] == ["external"]


def test_extract_loaded_and_repair_families_from_steps():
    load_action = AgentAction(
        tool="load_tool_family",
        tool_input={"family_names": ["browser"]},
        log="load",
    )
    invalid_action = AgentAction(
        tool="email_service_search_messages",
        tool_input={},
        log="invalid",
    )

    steps = [
        (load_action, json.dumps({"loaded_families": ["browser"]})),
        (invalid_action, "email_service_search_messages is not a valid tool. Available tools: load_tool_family"),
    ]

    assert extract_loaded_families_from_steps(steps) == ["browser"]
    assert extract_repair_families_from_steps(steps, loaded_families=["browser"]) == ["email"]


def test_extract_suggested_families_from_loader_observation():
    load_action = AgentAction(
        tool="load_tool_family",
        tool_input={"family_names": ["external_catalog"]},
        log="load",
    )
    steps = [
        (load_action, json.dumps({
            "loaded_families": ["external"],
            "invalid_families": [],
            "mapped_family_inputs": {"external_catalog": ["external"]},
            "suggested_families": ["external"],
        })),
    ]

    assert extract_suggested_families_from_loader_observation(steps) == ["external"]
    assert extract_suggested_families_from_loader_observation(steps, loaded_families=["external"]) == []


def test_provider_family_describes_durable_non_authorizing_proposals() -> None:
    provider = next(
        definition
        for definition in describe_tool_families()
        if definition["name"] == "provider"
    )

    assert family_for_tool_name("provider_catalog") == "provider"
    assert provider["risk_class"] == "durable non-authorizing provider proposal and target authorization"
    assert "authorize it against live authority" in provider["purpose"]
    assert "authorize it against live authority" in provider["purpose"]


def test_service_tool_factory_retains_explicit_delegation_submission_owner() -> None:
    submission_service = SimpleNamespace(
        submit_authorized_provider_delegation=object()
    )
    factory = ServiceToolFactory(
        service_execution_engine=SimpleNamespace(),
        capability_analyzer=SimpleNamespace(),
        agent_task_submission_service=submission_service,
    )

    assert factory.agent_task_submission_service is submission_service


def test_service_tool_factory_exposes_both_local_history_tools() -> None:
    factory = ServiceToolFactory(
        service_execution_engine=SimpleNamespace(),
        capability_analyzer=SimpleNamespace(),
    )

    result = factory.create_tools_from_services({})

    assert "retrieval.basil_history" in result.tool_map
    assert "retrieval.unified_history" in result.tool_map
    assert result.tool_map["retrieval.basil_history"].name == "retrieve_basil_history"
    assert result.tool_map["retrieval.unified_history"].name == "query_unified_history"


def test_service_tool_factory_disables_provider_catalog_for_delegation_continuation():
    factory = ServiceToolFactory(
        service_execution_engine=SimpleNamespace(),
        capability_analyzer=SimpleNamespace(),
        allow_provider_catalog=False,
    )

    assert factory.allow_provider_catalog is False
    assert should_register_provider_catalog(factory) is False
    assert should_register_provider_catalog(SimpleNamespace()) is True
