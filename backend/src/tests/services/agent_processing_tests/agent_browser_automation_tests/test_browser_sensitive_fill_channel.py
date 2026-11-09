"""Sensitive-fill approvals receive the agent task id and websocket manager from the agent context."""

from __future__ import annotations

import json

import pytest

from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_interact_tool,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_sensitive_approval import (
    BrowserSensitiveFillDecision,
)


class RecordingApprovalManager:
    def __init__(self):
        self.requests = []

    async def evaluate_sensitive_fill_request(self, request):
        self.requests.append(request)
        return BrowserSensitiveFillDecision(allowed=False, reason="blocked", domain="example.com", requires_user_input=True)


@pytest.mark.asyncio
async def test_sensitive_fill_request_carries_the_approval_channel(monkeypatch):
    sentinel_manager = object()
    approval_manager = RecordingApprovalManager()

    async def fake_run_browser_js(_browser, js_code, timeout=30.0, **_kwargs):
        if "Metadata inspect failed" in js_code:
            return {"success": True, "url": "https://example.com/login", "type": "password", "credentialLike": True}
        raise AssertionError("fill JS should not run when approval blocks")

    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", fake_run_browser_js)
    monkeypatch.setattr(browser_interact_tool, "get_browser_sensitive_approval_manager", lambda: approval_manager)
    token = set_current_agent_context({"agent_task_id": "task-7", "websocket_manager": sentinel_manager})
    try:
        result = json.loads(
            await browser_interact_tool._browser_interact_impl(
                browser="Chrome",
                action="fill",
                selector="input[type=password]",
                value="secret",
            )
        )
    finally:
        reset_current_agent_context(token)

    assert result["success"] is False
    assert len(approval_manager.requests) == 1
    assert approval_manager.requests[0].agent_task_id == "task-7"
    assert approval_manager.requests[0].websocket_manager is sentinel_manager


@pytest.mark.asyncio
async def test_sensitive_fill_request_still_works_outside_an_agent_run(monkeypatch):
    approval_manager = RecordingApprovalManager()

    async def fake_run_browser_js(_browser, js_code, timeout=30.0, **_kwargs):
        return {"success": True, "url": "https://example.com/login", "type": "password", "credentialLike": True}

    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", fake_run_browser_js)
    monkeypatch.setattr(browser_interact_tool, "get_browser_sensitive_approval_manager", lambda: approval_manager)

    await browser_interact_tool._browser_interact_impl(
        browser="Chrome", action="fill", selector="input[type=password]", value="secret"
    )

    assert approval_manager.requests[0].agent_task_id is None
    assert approval_manager.requests[0].websocket_manager is None
