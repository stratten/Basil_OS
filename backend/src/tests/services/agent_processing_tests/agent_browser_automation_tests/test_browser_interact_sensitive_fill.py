from __future__ import annotations

import json

import pytest

from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_interact_tool,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_sensitive_approval import (
    BrowserSensitiveFillDecision,
)


class BlockingApprovalManager:
    async def evaluate_sensitive_fill_request(self, _request):
        return BrowserSensitiveFillDecision(
            allowed=False,
            reason="blocked",
            domain="example.com",
            requires_user_input=True,
        )


class ApprovedApprovalManager:
    async def evaluate_sensitive_fill_request(self, _request):
        return BrowserSensitiveFillDecision(
            allowed=True,
            reason="approved",
            domain="example.com",
        )


@pytest.mark.asyncio
async def test_sensitive_selector_without_approval_is_blocked(monkeypatch):
    async def fake_run_browser_js(_browser, js_code, timeout=30.0, **_kwargs):
        assert timeout
        if "Metadata inspect failed" in js_code:
            return {
                "success": True,
                "url": "https://example.com/login",
                "type": "password",
                "credentialLike": True,
            }
        raise AssertionError("fill JS should not run when approval blocks")

    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", fake_run_browser_js)
    monkeypatch.setattr(browser_interact_tool, "get_browser_sensitive_approval_manager", lambda: BlockingApprovalManager())

    result = json.loads(await browser_interact_tool._browser_interact_impl(
        browser="Safari",
        action="fill",
        selector="input[type=password]",
        value="secret",
    ))

    assert result["success"] is False
    assert result["sensitive_fill"] is True
    assert result["requires_user_input"] is True


@pytest.mark.asyncio
async def test_approved_sensitive_fill_redacts_value(monkeypatch):
    calls = []

    async def fake_run_browser_js(_browser, js_code, timeout=30.0, **_kwargs):
        calls.append(js_code)
        if "Metadata inspect failed" in js_code:
            return {
                "success": True,
                "url": "https://example.com/login",
                "type": "password",
                "credentialLike": True,
            }
        assert "allowSensitiveFill = true" in js_code
        return {
            "success": True,
            "action": "fill",
            "selector": "input[type=password]",
            "valueFilled": "secret",
        }

    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", fake_run_browser_js)
    monkeypatch.setattr(browser_interact_tool, "get_browser_sensitive_approval_manager", lambda: ApprovedApprovalManager())

    result = json.loads(await browser_interact_tool._browser_interact_impl(
        browser="Safari",
        action="fill",
        selector="input[type=password]",
        value="secret",
    ))

    assert len(calls) == 2
    assert result["success"] is True
    assert result["sensitive_fill"] is True
    assert result["value_redacted"] is True
    assert result["valueFilled"] == "[redacted]"


@pytest.mark.asyncio
async def test_non_sensitive_fill_still_works(monkeypatch):
    async def fake_run_browser_js(_browser, js_code, timeout=30.0, **_kwargs):
        if "Metadata inspect failed" in js_code:
            return {
                "success": True,
                "url": "https://example.com/search",
                "type": "text",
                "credentialLike": False,
            }
        return {
            "success": True,
            "action": "fill",
            "selector": "#search",
            "valueFilled": "query",
        }

    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", fake_run_browser_js)

    result = json.loads(await browser_interact_tool._browser_interact_impl(
        browser="Safari",
        action="fill",
        selector="#search",
        value="query",
    ))

    assert result["success"] is True
    assert "sensitive_fill" not in result
    assert result["valueFilled"] == "query"

