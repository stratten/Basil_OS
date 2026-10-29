from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.core.models.preferences import (
    BrowserAutomationSessionMode,
    BrowserDomainApproval,
    BrowserForegroundControlPolicy,
    BrowserPreferredUserBrowser,
    BrowserSensitiveFillPolicy,
    Preferences,
)
from api.routes.settings_routes import browser_automation_routes


@pytest.mark.asyncio
async def test_browser_automation_settings_default_policy_is_never(monkeypatch):
    preferences = Preferences()
    monkeypatch.setattr(browser_automation_routes, "load_preferences", lambda: preferences)

    response = await browser_automation_routes.get_browser_automation_settings()

    assert response.settings.sensitive_fill_policy == BrowserSensitiveFillPolicy.NEVER
    assert (
        response.settings.foreground_control_policy
        == BrowserForegroundControlPolicy.ASK_BEFORE_FOREGROUND
    )
    assert response.settings.default_session_mode == BrowserAutomationSessionMode.USER_BROWSER
    assert response.settings.preferred_user_browser == BrowserPreferredUserBrowser.SYSTEM_DEFAULT


@pytest.mark.asyncio
async def test_browser_automation_settings_put_round_trip(monkeypatch):
    saved = []
    preferences = Preferences()
    monkeypatch.setattr(browser_automation_routes, "load_preferences", lambda: preferences)
    monkeypatch.setattr(browser_automation_routes, "save_preferences", lambda prefs: saved.append(prefs))

    response = await browser_automation_routes.update_browser_automation_settings(
        browser_automation_routes.BrowserAutomationSettingsUpdate(
            sensitive_fill_policy=BrowserSensitiveFillPolicy.ASK_EVERY_TIME,
            foreground_control_policy=BrowserForegroundControlPolicy.BACKGROUND_ONLY,
            default_session_mode=BrowserAutomationSessionMode.BASIL_AUTOMATION_BROWSER,
            preferred_user_browser=BrowserPreferredUserBrowser.CHROME,
            show_action_highlights=False,
        )
    )

    assert response.updated_settings.sensitive_fill_policy == BrowserSensitiveFillPolicy.ASK_EVERY_TIME
    assert response.updated_settings.foreground_control_policy == BrowserForegroundControlPolicy.BACKGROUND_ONLY
    assert response.updated_settings.default_session_mode == BrowserAutomationSessionMode.BASIL_AUTOMATION_BROWSER
    assert response.updated_settings.preferred_user_browser == BrowserPreferredUserBrowser.CHROME
    assert response.updated_settings.show_action_highlights is False
    assert saved == [preferences]


@pytest.mark.asyncio
async def test_browser_automation_delete_sensitive_domain(monkeypatch):
    saved = []
    preferences = Preferences()
    preferences.browser_automation.approved_sensitive_fill_domains = [
        BrowserDomainApproval(domain="example.com"),
        BrowserDomainApproval(domain="other.example"),
    ]
    monkeypatch.setattr(browser_automation_routes, "load_preferences", lambda: preferences)
    monkeypatch.setattr(browser_automation_routes, "save_preferences", lambda prefs: saved.append(prefs))

    response = await browser_automation_routes.delete_browser_sensitive_domain_approval("example.com")

    assert response.status == "success"
    assert [approval.domain for approval in preferences.browser_automation.approved_sensitive_fill_domains] == [
        "other.example"
    ]
    assert saved == [preferences]


@pytest.mark.asyncio
async def test_clear_basil_automation_browser_profile_removes_only_profile_dir(monkeypatch, tmp_path):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir()
    (profile_dir / "state.json").write_text("{}", encoding="utf-8")
    sibling_dir = tmp_path / "downloads"
    sibling_dir.mkdir()

    from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
        basil_automation_browser_runtime,
    )

    monkeypatch.setattr(
        basil_automation_browser_runtime,
        "get_default_basil_automation_browser_profile",
        lambda: SimpleNamespace(profile_dir=profile_dir),
    )

    response = await browser_automation_routes.clear_basil_automation_browser_profile()

    assert response.status == "success"
    assert not profile_dir.exists()
    assert sibling_dir.exists()

