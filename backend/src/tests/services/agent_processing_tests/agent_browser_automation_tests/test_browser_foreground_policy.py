"""The foreground policy gate: background_only blocks, allow permits, ask uses one approval card."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from api.core.models.preferences import BrowserForegroundControlPolicy
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_foreground_policy,
)


def use_policy(monkeypatch, policy: BrowserForegroundControlPolicy) -> None:
    from api.core.preferences import preferences_io

    monkeypatch.setattr(
        preferences_io,
        "load_preferences",
        lambda: SimpleNamespace(browser_automation=SimpleNamespace(foreground_control_policy=policy)),
    )


@pytest.fixture
def approval(monkeypatch):
    from api.services.agent_processing.tools import safety

    class FakeApprovalService:
        instances: List["FakeApprovalService"] = []
        answer = True

        def __init__(self, websocket_manager=None):
            self.websocket_manager = websocket_manager
            self.requests: List[Dict[str, Any]] = []
            FakeApprovalService.instances.append(self)

        async def request_approval(self, summary, context=None):
            self.requests.append({"summary": summary, "context": context})
            return FakeApprovalService.answer, False, None

    monkeypatch.setattr(safety, "ExecutionApprovalService", FakeApprovalService)
    return FakeApprovalService


async def authorize():
    return await browser_foreground_policy.authorize_browser_foreground(
        purpose="Show the CAPTCHA to the user",
        details="Bring the Google Chrome window (id 77) to the front.",
        browser="Google Chrome",
    )


@pytest.mark.asyncio
async def test_background_only_blocks_without_asking(monkeypatch, approval):
    use_policy(monkeypatch, BrowserForegroundControlPolicy.BACKGROUND_ONLY)

    decision = await authorize()

    assert decision.allowed is False
    assert decision.reason == "blocked_by_policy"
    assert decision.to_result() == {
        "foreground_blocked": True,
        "foreground_policy": "background_only",
        "reason": "blocked_by_policy",
        "message": "Foreground browser control is turned off in Basil's Browser Automation settings.",
    }
    assert approval.instances == []


@pytest.mark.asyncio
async def test_allow_when_needed_permits_without_asking(monkeypatch, approval):
    use_policy(monkeypatch, BrowserForegroundControlPolicy.ALLOW_FOREGROUND_WHEN_NEEDED)

    decision = await authorize()

    assert decision.allowed is True
    assert decision.reason == "allowed_by_policy"
    assert decision.to_result()["foreground_blocked"] is False
    assert approval.instances == []


@pytest.mark.asyncio
async def test_ask_without_a_websocket_channel_is_blocked(monkeypatch, approval):
    use_policy(monkeypatch, BrowserForegroundControlPolicy.ASK_BEFORE_FOREGROUND)
    token = set_current_agent_context({"agent_task_id": "agent-1"})
    try:
        decision = await authorize()
    finally:
        reset_current_agent_context(token)

    assert decision.allowed is False
    assert decision.reason == "no_approval_channel"
    assert approval.instances == []


@pytest.mark.asyncio
async def test_ask_sends_one_approval_card_and_honors_approval(monkeypatch, approval):
    use_policy(monkeypatch, BrowserForegroundControlPolicy.ASK_BEFORE_FOREGROUND)
    approval.answer = True
    manager = object()
    token = set_current_agent_context({"agent_task_id": "agent-1", "websocket_manager": manager})
    try:
        decision = await authorize()
    finally:
        reset_current_agent_context(token)

    assert decision.allowed is True
    assert decision.reason == "approved"
    assert len(approval.instances) == 1
    service = approval.instances[0]
    assert service.websocket_manager is manager
    request = service.requests[0]
    assert request["summary"] == "Browser foreground control: Show the CAPTCHA to the user"
    context = request["context"]
    assert context["execution_type"] == "browser_foreground_control"
    assert context["risk_level"] == "high"
    assert context["agent_task_id"] == "agent-1"
    assert context["script_content"] == "Bring the Google Chrome window (id 77) to the front."
    assert context["purpose"] == "Basil wants to bring Google Chrome to the front of your screen: Show the CAPTCHA to the user"
    assert context["purpose_source"] == "basil"


@pytest.mark.asyncio
async def test_ask_honors_denial(monkeypatch, approval):
    use_policy(monkeypatch, BrowserForegroundControlPolicy.ASK_BEFORE_FOREGROUND)
    approval.answer = False
    token = set_current_agent_context({"agent_task_id": "agent-1", "websocket_manager": object()})
    try:
        decision = await authorize()
    finally:
        reset_current_agent_context(token)

    assert decision.allowed is False
    assert decision.reason == "denied"
    assert "declined" in decision.message
