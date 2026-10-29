"""A tool error the agent recovered from must not make the provisional (no-LLM) outcome partial."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from api.services.agent_processing.lifecycle.finalization.result_finalizer_tool import (
    finalize_agent_task_result,
    unrecovered_failed_steps,
)


def _catalog_step(tool_name: str, *, success: bool, arguments: Dict[str, Any] | None = None, connection_id: str = "conn-1") -> Dict[str, Any]:
    return {
        "service": "external_catalog",
        "method": "invoke",
        "success": success,
        "tool_input": {"action": "call_tool", "connection_id": connection_id, "tool_name": tool_name, "arguments": arguments or {}},
    }


def _write_step(path: str, *, success: bool) -> Dict[str, Any]:
    return {"service": "text_files", "method": "write", "success": success, "tool_input": {"path": path, "content": "x"}}


async def _provisional(steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    # llm_model=None is exactly what build_provisional_envelope passes, so this is the deterministic path.
    return await finalize_agent_task_result(
        original_prompt="How is the Lido request progressing?",
        agent_task_id=None,
        active_app="Cursor",
        steps=steps,
        standardized_messages=["REQ-2026-0636 is ready for final review."],
        metrics={"steps_completed": len(steps), "steps_total": len(steps)},
        llm_model=None,
        is_local_model=True,
    )


def test_a_failed_call_followed_by_the_same_tool_succeeding_is_recovered():
    steps = [
        _catalog_step("speakeasy_list_requests", success=True),
        _catalog_step("speakeasy_get_request_timeline", success=False, arguments={"requestId": "r1"}),
        _catalog_step("speakeasy_get_request_timeline", success=True, arguments={"requestId": "r1", "limit": 10}),
    ]

    assert unrecovered_failed_steps(steps) == []


def test_a_failure_stays_when_the_success_was_a_different_tool_or_connection():
    different_tool = [_catalog_step("a_tool", success=False), _catalog_step("another_tool", success=True)]
    different_connection = [_catalog_step("a_tool", success=False, connection_id="c1"), _catalog_step("a_tool", success=True, connection_id="c2")]

    assert len(unrecovered_failed_steps(different_tool)) == 1
    assert len(unrecovered_failed_steps(different_connection)) == 1


def test_a_success_before_the_failure_does_not_recover_it():
    steps = [_catalog_step("a_tool", success=True), _catalog_step("a_tool", success=False)]

    assert len(unrecovered_failed_steps(steps)) == 1


def test_a_non_dispatcher_tool_is_only_recovered_by_the_same_exact_input():
    other_file = [_write_step("/tmp/a.txt", success=False), _write_step("/tmp/b.txt", success=True)]
    same_file = [_write_step("/tmp/a.txt", success=False), _write_step("/tmp/a.txt", success=True)]

    assert len(unrecovered_failed_steps(other_file)) == 1
    assert unrecovered_failed_steps(same_file) == []


def test_steps_without_enough_detail_to_match_are_never_treated_as_recovered():
    steps = [{"success": False}, {"success": True}, {"status": "failed"}, {"status": "completed"}]

    assert len(unrecovered_failed_steps(steps)) == 2


def test_empty_and_missing_steps_have_no_failures():
    assert unrecovered_failed_steps(None) == []
    assert unrecovered_failed_steps([]) == []


@pytest.mark.asyncio
async def test_the_provisional_outcome_is_success_when_every_failure_was_recovered():
    steps = [
        _catalog_step("speakeasy_get_request_timeline", success=False),
        _catalog_step("speakeasy_get_request_timeline", success=True),
    ]

    envelope = await _provisional(steps)

    assert envelope["outcome"] == "success"
    assert envelope["success"] is True
    assert not envelope["summary_text"].startswith("Partial result")


@pytest.mark.asyncio
async def test_the_provisional_outcome_is_still_partial_when_a_failure_was_not_recovered():
    steps = [
        _catalog_step("speakeasy_list_requests", success=True),
        _catalog_step("speakeasy_get_request_timeline", success=False),
    ]

    envelope = await _provisional(steps)

    assert envelope["outcome"] == "partial"
    assert envelope["success"] is False
    assert envelope["summary_text"].startswith("Partial result")
