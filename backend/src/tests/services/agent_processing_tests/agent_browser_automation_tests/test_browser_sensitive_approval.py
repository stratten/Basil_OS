from __future__ import annotations

import asyncio

import pytest

from api.core.models.preferences import (
    BrowserDomainApproval,
    BrowserSensitiveFillPolicy,
    Preferences,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_sensitive_approval,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_sensitive_approval import (
    BrowserSensitiveApprovalManager,
    BrowserSensitiveFillRequest,
)


class FakeWebSocketManager:
    def __init__(self) -> None:
        self.events = []
        self.broadcast_event = asyncio.Event()

    async def broadcast(self, event):
        self.events.append(event)
        self.broadcast_event.set()


def _request(websocket_manager=None) -> BrowserSensitiveFillRequest:
    return BrowserSensitiveFillRequest(
        browser="Safari",
        selector="input[type=password]",
        url="https://example.com/login",
        field_metadata={"type": "password"},
        websocket_manager=websocket_manager,
    )


@pytest.mark.asyncio
async def test_sensitive_fill_policy_never_blocks(monkeypatch):
    preferences = Preferences()
    preferences.browser_automation.sensitive_fill_policy = BrowserSensitiveFillPolicy.NEVER
    monkeypatch.setattr(browser_sensitive_approval, "load_preferences", lambda: preferences)

    decision = await BrowserSensitiveApprovalManager().evaluate_sensitive_fill_request(_request())

    assert decision.allowed is False
    assert decision.requires_user_input is True
    assert decision.domain == "example.com"


@pytest.mark.asyncio
async def test_approved_domains_policy_permits_exact_domain(monkeypatch):
    saved = []
    preferences = Preferences()
    preferences.browser_automation.sensitive_fill_policy = BrowserSensitiveFillPolicy.APPROVED_DOMAINS
    preferences.browser_automation.approved_sensitive_fill_domains = [
        BrowserDomainApproval(domain="example.com")
    ]
    monkeypatch.setattr(browser_sensitive_approval, "load_preferences", lambda: preferences)
    monkeypatch.setattr(browser_sensitive_approval, "save_preferences", lambda prefs: saved.append(prefs))

    decision = await BrowserSensitiveApprovalManager().evaluate_sensitive_fill_request(_request())

    assert decision.allowed is True
    assert decision.remember_domain is True
    assert preferences.browser_automation.approved_sensitive_fill_domains[0].use_count == 1
    assert saved == [preferences]


@pytest.mark.asyncio
async def test_ask_every_time_emits_approval_and_denial(monkeypatch):
    preferences = Preferences()
    preferences.browser_automation.sensitive_fill_policy = BrowserSensitiveFillPolicy.ASK_EVERY_TIME
    monkeypatch.setattr(browser_sensitive_approval, "load_preferences", lambda: preferences)
    websocket = FakeWebSocketManager()
    manager = BrowserSensitiveApprovalManager()

    task = asyncio.create_task(manager.evaluate_sensitive_fill_request(_request(websocket)))
    await websocket.broadcast_event.wait()
    approval_id = websocket.events[0]["approval_id"]
    resolved = await BrowserSensitiveApprovalManager.resolve_browser_sensitive_fill_approval(
        approval_id=approval_id,
        approved=False,
    )
    decision = await task

    assert resolved is True
    assert websocket.events[0]["execution_type"] == "browser_sensitive_fill"
    assert decision.allowed is False
    assert decision.approval_denied is True


@pytest.mark.asyncio
async def test_remembered_approval_writes_domain_record(monkeypatch):
    saved = []
    preferences = Preferences()
    preferences.browser_automation.sensitive_fill_policy = BrowserSensitiveFillPolicy.ASK_EVERY_TIME
    monkeypatch.setattr(browser_sensitive_approval, "load_preferences", lambda: preferences)
    monkeypatch.setattr(browser_sensitive_approval, "save_preferences", lambda prefs: saved.append(prefs))
    websocket = FakeWebSocketManager()
    manager = BrowserSensitiveApprovalManager()

    task = asyncio.create_task(manager.evaluate_sensitive_fill_request(_request(websocket)))
    await websocket.broadcast_event.wait()
    approval_id = websocket.events[0]["approval_id"]
    await BrowserSensitiveApprovalManager.resolve_browser_sensitive_fill_approval(
        approval_id=approval_id,
        approved=True,
        remember_domain=True,
    )
    decision = await task

    assert decision.allowed is True
    assert [approval.domain for approval in preferences.browser_automation.approved_sensitive_fill_domains] == [
        "example.com"
    ]
    assert saved == [preferences]

