"""AppleScript approvals must be attributed to the task that is actually running."""

from __future__ import annotations

import pytest

from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.direct_application_interactions.applescript_automation.generic_applescript_service import (
    GenericAppleScriptService,
)


class _CapturingApproval:
    def __init__(self) -> None:
        self.contexts: list = []

    async def request_approval(self, summary, context=None):
        self.contexts.append(context)
        return False, False, None


def _service(instance_task_id: str) -> tuple[GenericAppleScriptService, _CapturingApproval]:
    service = GenericAppleScriptService()
    service._agent_task_id = instance_task_id
    approval = _CapturingApproval()
    service._approval_service = approval
    return service, approval


@pytest.mark.asyncio
async def test_applescript_approval_prefers_current_agent_context():
    service, approval = _service("stale-task")
    token = set_current_agent_context({"agent_task_id": "current-task"})
    try:
        result = await service.execute_applescript(
            'display dialog "hello"',
            context={"task_description": "Say hello", "agent_task_id": "explicit-task"},
        )
    finally:
        reset_current_agent_context(token)

    assert result.success is False
    assert result.approval_denied is True
    assert approval.contexts[0]["agent_task_id"] == "current-task"


@pytest.mark.asyncio
async def test_applescript_approval_uses_explicit_context_then_instance_fallback():
    service, approval = _service("fallback-task")

    await service.execute_applescript(
        'display dialog "hello"',
        context={"task_description": "Say hello", "agent_task_id": "explicit-task"},
    )
    await service.execute_applescript('display dialog "hello"', context={"task_description": "Say hello"})

    assert approval.contexts[0]["agent_task_id"] == "explicit-task"
    assert approval.contexts[1]["agent_task_id"] == "fallback-task"
