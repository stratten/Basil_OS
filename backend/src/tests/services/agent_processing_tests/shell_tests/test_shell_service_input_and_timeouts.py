"""ShellService integration: relayed prompts, partial timeout output, attribution, and env defaults."""

from __future__ import annotations

import asyncio
import sys

import pytest

from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.command_input_broker import (
    CommandInputBroker,
)
from api.services.agent_processing.tools.direct_application_interactions.shell.shell_service import ShellService


class AnsweringWebSocketManager:
    """Answers every relayed prompt as soon as it is broadcast."""

    def __init__(self, answer: str = "", action: str = "answer"):
        self.events: list[dict] = []
        self._answer = answer
        self._action = action

    async def broadcast(self, event):
        self.events.append(event)
        request_id = event["approval_id"]
        asyncio.get_running_loop().call_soon(
            lambda: CommandInputBroker.respond(request_id, action=self._action, value=self._answer)
        )


@pytest.mark.asyncio
async def test_prompt_is_relayed_through_the_broker_and_answered():
    manager = AnsweringWebSocketManager(answer="yes")
    service = ShellService(websocket_manager=manager)
    token = set_current_agent_context({"agent_task_id": "task-relay"})
    try:
        result = await service.execute_command(
            command=sys.executable,
            args=["-c", "a = input('Continue? (yes/no) '); print('reply=' + a)"],
            timeout_s=20,
            skip_approval_check=True,
        )
    finally:
        reset_current_agent_context(token)
    assert result["success"] is True, result
    assert "reply=yes" in result["stdout"]
    assert result["input_exchanges"] == [{"prompt": "Continue? (yes/no)", "secret": False, "status": "answered"}]
    assert manager.events[0]["agent_task_id"] == "task-relay"
    assert manager.events[0]["execution_type"] == "command_input"


@pytest.mark.asyncio
async def test_prompt_without_agent_context_returns_input_required():
    service = ShellService()
    result = await service.execute_command(
        command=sys.executable,
        args=["-c", "input('Overwrite? [y/N] ')"],
        timeout_s=30,
        skip_approval_check=True,
    )
    assert result["success"] is False
    assert result["error_type"] == "input_required"
    assert result["input_prompt"] == "Overwrite? [y/N]"
    assert "non-interactively" in result["stderr"]


@pytest.mark.asyncio
async def test_canceled_prompt_reports_input_canceled():
    service = ShellService(websocket_manager=AnsweringWebSocketManager(action="cancel"))
    token = set_current_agent_context({"agent_task_id": "task-cancel"})
    try:
        result = await service.execute_command(
            command=sys.executable,
            args=["-c", "input('Delete everything? [y/N] ')"],
            timeout_s=20,
            skip_approval_check=True,
        )
    finally:
        reset_current_agent_context(token)
    assert result["error_type"] == "input_canceled"
    assert result["input_status"] == "input_canceled"


@pytest.mark.asyncio
async def test_timeout_result_keeps_partial_stdout():
    service = ShellService()
    result = await service.execute_command(
        command="bash",
        args=["-lc", "echo started; sleep 30"],
        timeout_s=1,
        skip_approval_check=True,
    )
    assert result["timed_out"] is True
    assert result["error_type"] == "timeout"
    assert "started" in result["stdout"]
    assert result["partial_output"] is True
    assert "Command timed out after 1s" in result["stderr"]
    assert result["timeout_clock"] == "monotonic"


@pytest.mark.asyncio
async def test_non_interactive_env_defaults_and_overrides():
    service = ShellService()
    defaults = await service.execute_command(
        command="bash", args=["-c", "echo $PAGER:$GIT_PAGER:$TERM"], timeout_s=10, skip_approval_check=True
    )
    assert defaults["stdout"].strip() == "cat:cat:dumb"
    overridden = await service.execute_command(
        command="bash",
        args=["-c", "echo $TERM"],
        env_overrides={"TERM": "xterm-256color"},
        timeout_s=10,
        skip_approval_check=True,
    )
    assert overridden["stdout"].strip() == "xterm-256color"


@pytest.mark.asyncio
async def test_context_task_id_wins_over_stale_instance_attribute():
    manager = AnsweringWebSocketManager(answer="ok")
    service = ShellService(websocket_manager=manager)
    service._agent_task_id = "stale-other-task"
    token = set_current_agent_context({"agent_task_id": "task-current"})
    try:
        await service.execute_command(
            command=sys.executable,
            args=["-c", "input('Name: ')"],
            timeout_s=20,
            skip_approval_check=True,
        )
    finally:
        reset_current_agent_context(token)
    assert manager.events[0]["agent_task_id"] == "task-current"


@pytest.mark.asyncio
async def test_missing_executable_still_reports_executable_not_found():
    result = await ShellService().execute_command(
        command="basil-definitely-missing-executable", timeout_s=5, skip_approval_check=True
    )
    assert result["error_type"] == "executable_not_found"
