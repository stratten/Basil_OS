"""Tests for naming connection steps and recognizing a tool's own reported failure."""

from __future__ import annotations

import json

import pytest

from api.services.agent_processing.lifecycle.execution_graph import tool_step_labels as labels
from api.services.agent_processing.lifecycle.execution_graph.activity_progress_callback import (
    ActivityProgressCallbackHandler,
)


@pytest.fixture
def named_connection(monkeypatch):
    monkeypatch.setattr(labels, "_connection_name", lambda connection_id: "Gmail - Work" if connection_id == "conn-1" else None)


def test_a_connection_call_names_the_connection_and_the_tool(named_connection):
    label = labels.describe_external_catalog_step({"action": "call_tool", "connection_id": "conn-1", "tool_name": "search_threads"})

    assert label == "Gmail - Work: search_threads"


def test_describing_a_connection_names_it(named_connection):
    assert labels.describe_external_catalog_step({"action": "describe_server", "connection_id": "conn-1"}) == "Reading the tools of Gmail - Work"


def test_listing_connections_has_its_own_label():
    assert labels.describe_external_catalog_step({"action": "list_servers"}) == "Listing your connections"


def test_an_unknown_connection_or_missing_tool_still_reads_plainly(named_connection):
    label = labels.describe_external_catalog_step({"action": "call_tool", "connection_id": "gone"})

    assert label == "a connection: a tool"


@pytest.mark.parametrize("tool_inputs", [{}, {"action": "bogus"}, {"action": None}, None])
def test_unrecognized_requests_fall_back_to_the_generic_label(tool_inputs):
    assert labels.describe_external_catalog_step(tool_inputs) is None


def test_the_callback_titles_a_connection_step_with_the_connection(named_connection):
    callback = ActivityProgressCallbackHandler.__new__(ActivityProgressCallbackHandler)

    title = callback._extract_rich_task_description("external_catalog", {"action": "call_tool", "connection_id": "conn-1", "tool_name": "search_threads"})

    assert title == "Gmail - Work: search_threads"


def test_other_tools_keep_their_existing_labels():
    callback = ActivityProgressCallbackHandler.__new__(ActivityProgressCallbackHandler)

    assert callback._extract_rich_task_description("email_service_list", {}) == "Working with email"
    assert callback._extract_rich_task_description("something_else", {}) == "Executing approved tool"


def test_an_error_envelope_is_a_failure_with_its_message():
    output = json.dumps({"ok": False, "error": {"kind": "permission_denied", "message": "Project not enrolled."}})

    assert labels.tool_failure_reason(output) == "Project not enrolled."


def test_a_success_false_result_is_a_failure_with_the_nested_error():
    output = {"success": False, "result": {"success": False, "error": "AppleScript timed out"}}

    assert labels.tool_failure_reason(output) == "AppleScript timed out"


def test_a_failure_without_a_message_still_reads_as_a_failure():
    assert labels.tool_failure_reason({"ok": False}) == "The tool reported a failure."


@pytest.mark.parametrize(
    "output",
    [{"ok": True, "result": {}}, {"success": True}, "plain text", "{not json", None, 42, json.dumps({"agent_task_artifact": {}})],
)
def test_ordinary_outputs_are_not_failures(output):
    assert labels.tool_failure_reason(output) is None


def test_a_message_object_is_read_through_its_content():
    class Message:
        content = json.dumps({"ok": False, "error": {"message": "Denied"}})

    assert labels.tool_failure_reason(Message()) == "Denied"
