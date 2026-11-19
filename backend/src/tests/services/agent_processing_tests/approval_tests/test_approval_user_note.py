"""The optional note a user types with an approval decision: request contract, shell denial text, and the successful-result carrier."""

import asyncio
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from api.routes.agent_tasks.execution_models import ApprovalDecisionRequest
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_execution_result import (
    build_approval_failure_result,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_service import ShellService
from api.services.agent_processing.tools.safety.models import ExecutionApprovalOutcome


def _request(**overrides):
    values = {"approval_id": "a", "command": "ls", "approved": False}
    values.update(overrides)
    return ApprovalDecisionRequest(**values)


def test_note_is_optional_and_bounded():
    assert _request().user_note is None
    assert _request(user_note="ok").user_note == "ok"
    assert _request(user_note="x" * 2000).user_note == "x" * 2000
    with pytest.raises(ValidationError):
        _request(user_note="x" * 2001)


def test_outcome_defaults_to_no_note():
    assert ExecutionApprovalOutcome(approved=False).user_note == ""


def test_denied_shell_result_carries_the_note_in_the_text_the_agent_reads():
    outcome = ExecutionApprovalOutcome(approved=False, status="user_denied", user_note="Wrong folder; use ~/Documents.")

    result = build_approval_failure_result(cwd="/tmp", command_echo="ls", outcome=outcome)

    assert result["stderr"] == "Command execution was denied by user. The user added this guidance with the denial: Wrong folder; use ~/Documents."
    assert result["approval_user_note"] == "Wrong folder; use ~/Documents."
    assert result["approval_denied"] is True


def test_denied_shell_result_without_a_note_is_unchanged():
    outcome = ExecutionApprovalOutcome(approved=False, status="user_denied")

    result = build_approval_failure_result(cwd="/tmp", command_echo="ls", outcome=outcome)

    assert result["stderr"] == "Command execution was denied by user"
    assert "approval_user_note" not in result


def test_a_note_does_not_change_the_text_of_non_denial_failures():
    outcome = ExecutionApprovalOutcome(approved=False, status="approval_timed_out", reason="Timed out.", user_note="stray")

    result = build_approval_failure_result(cwd="/tmp", command_echo="ls", outcome=outcome)

    assert result["stderr"] == "Timed out."


def _service_whose_body_returns(result, note):
    service = ShellService()

    async def body(command, **kwargs):
        if note:
            kwargs["approval_note_holder"]["note"] = note
        return dict(result)

    service._execute_command_after_policy = body
    return service


def test_an_approved_note_is_attached_to_the_successful_result():
    service = _service_whose_body_returns({"success": True, "stdout": "ok"}, "Also check the exit code.")

    result = asyncio.run(service.execute_command("ls"))

    assert result["success"] is True
    assert result["approval_user_note"] == "Also check the exit code."
    assert result["user_guidance_with_approval"] == "The user approved this command and added this guidance: Also check the exit code."


def test_a_result_without_an_approval_note_is_untouched():
    service = _service_whose_body_returns({"success": True, "stdout": "ok"}, "")

    result = asyncio.run(service.execute_command("ls"))

    assert result == {"success": True, "stdout": "ok"}
