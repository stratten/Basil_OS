"""Tests for staged tool-loading post-pass repair decisions."""

from __future__ import annotations

import json

from langchain_classic.schema import AgentAction

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.staged_tool_loading_repair import (
    collect_new_tool_families_from_steps,
)


def _action(tool: str, tool_input: dict | None = None) -> AgentAction:
    return AgentAction(tool=tool, tool_input=tool_input or {}, log=f"invoke {tool}")


def test_loader_tool_name_mapping_produces_new_family():
    steps = [
        (_action("load_tool_family", {"family_names": ["external_catalog"]}), json.dumps({
            "loaded_families": ["external"],
            "invalid_families": [],
            "mapped_family_inputs": {"external_catalog": ["external"]},
            "suggested_families": ["external"],
        })),
    ]

    decision = collect_new_tool_families_from_steps(steps, loaded_families=[])

    assert decision.should_continue is True
    assert decision.new_families == ["external"]
    assert decision.suggested_families == ["external"]
    assert decision.invalid_loader_requests == []
    assert decision.details["mapped_family_inputs"] == {"external_catalog": ["external"]}


def test_loaded_families_are_not_repeated():
    steps = [
        (_action("load_tool_family", {"family_names": ["external_catalog"]}), json.dumps({
            "loaded_families": ["external"],
            "invalid_families": [],
            "mapped_family_inputs": {"external_catalog": ["external"]},
            "suggested_families": ["external"],
        })),
    ]

    decision = collect_new_tool_families_from_steps(steps, loaded_families=["external"])

    assert decision.should_continue is False
    assert decision.new_families == []
    assert decision.suggested_families == []


def test_existing_invalid_tool_repair_still_works():
    steps = [
        (
            _action("email_service_search_messages"),
            "email_service_search_messages is not a valid tool. Available tools: load_tool_family",
        ),
    ]

    decision = collect_new_tool_families_from_steps(steps, loaded_families=[])

    assert decision.should_continue is True
    assert decision.new_families == ["email"]
    assert decision.repair_families == ["email"]


def test_reload_of_baseline_family_is_not_new():
    steps = [
        (_action("load_tool_family", {"family_names": ["automation"]}), json.dumps({
            "loaded_families": ["automation"],
            "invalid_families": [],
            "mapped_family_inputs": {},
            "suggested_families": ["automation"],
        })),
    ]

    decision = collect_new_tool_families_from_steps(steps, loaded_families=[])

    assert decision.new_families == []
    assert decision.should_continue is False
    assert decision.requested_families == ["automation"]
    assert decision.had_non_loader_activity is False


def test_non_loader_activity_detected():
    steps = [
        (_action("applescript_service_generate_and_execute_applescript"), "Created event"),
    ]

    decision = collect_new_tool_families_from_steps(steps, loaded_families=["automation"])

    assert decision.had_non_loader_activity is True


def test_loader_only_pass_has_no_non_loader_activity():
    steps = [
        (_action("load_tool_family", {"family_names": ["automation"]}), json.dumps({
            "loaded_families": ["automation"],
        })),
    ]

    decision = collect_new_tool_families_from_steps(steps, loaded_families=[])

    assert decision.had_non_loader_activity is False


def test_unmapped_invalid_loader_request_produces_diagnostics_without_family():
    steps = [
        (_action("load_tool_family", {"family_names": ["speakeasy_list_requests"]}), json.dumps({
            "loaded_families": [],
            "invalid_families": ["speakeasy_list_requests"],
            "mapped_family_inputs": {},
            "suggested_families": [],
        })),
    ]

    decision = collect_new_tool_families_from_steps(steps, loaded_families=[])

    assert decision.should_continue is False
    assert decision.new_families == []
    assert decision.invalid_loader_requests == ["speakeasy_list_requests"]
    assert "unresolved loader inputs" in (decision.diagnostic or "")
