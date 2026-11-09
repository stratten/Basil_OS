"""Coverage for capturing a pinned Basil browser window without activating the browser."""

from __future__ import annotations

import json

import pytest

from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_screenshot_tool as screenshot_tool,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_window_capture_target as capture_target,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_pinned_target import (
    clear_pinned_browser_targets,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_target_runtime import (
    BrowserAutomationTarget,
)


@pytest.fixture(autouse=True)
def _clear_pins():
    clear_pinned_browser_targets()
    yield
    clear_pinned_browser_targets()


def test_script_reads_frame_without_activating_the_browser():
    script = capture_target.build_window_frame_script("Chrome", 42)

    assert 'tell application "Google Chrome"' in script
    assert "window id 42" in script
    assert "title of active tab of window id 42" in script
    assert "activate" not in script.lower()
    assert "set index" not in script.lower()


def test_safari_script_uses_its_own_tab_title_syntax():
    script = capture_target.build_window_frame_script("Safari", 7)

    assert 'tell application "Safari"' in script
    assert "name of current tab of window id 7" in script


def test_parse_reply_builds_a_window_target():
    target, error = capture_target.parse_window_frame_reply("Chrome", "ok|100|80|1200|800|Annual Report")

    assert error is None
    assert target == {
        "owner_name": "Google Chrome",
        "bounds": {"x": 100.0, "y": 80.0, "width": 1200.0, "height": 800.0},
        "title": "Annual Report",
    }


def test_parse_reply_keeps_a_title_that_contains_the_separator():
    target, error = capture_target.parse_window_frame_reply("Chrome", "ok|0|0|900|700|A | B | C")

    assert error is None
    assert target["title"] == "A | B | C"


@pytest.mark.parametrize(
    "reply, fragment",
    [
        ("error|window_missing", "no longer exists"),
        ("garbage", "Unexpected reply"),
        ("ok|a|b|c|d|title", "Could not read"),
        ("ok|0|0|0|0|title", "no visible area"),
        ("", "Unexpected reply"),
    ],
)
def test_parse_reply_reports_a_clear_error(reply, fragment):
    target, error = capture_target.parse_window_frame_reply("Chrome", reply)

    assert target is None
    assert fragment in error


@pytest.mark.asyncio
async def test_resolve_reports_applescript_failure(monkeypatch):
    async def fake_run(script, timeout_s=30.0):
        return False, "", "Not authorized to send Apple events"

    monkeypatch.setattr(capture_target, "run_applescript", fake_run)
    pinned = BrowserAutomationTarget(browser="Chrome", window_id=42, created_by_basil=True)

    target, error = await capture_target.resolve_window_capture_target(pinned)

    assert target is None
    assert "Not authorized" in error


@pytest.mark.asyncio
async def test_screenshot_of_a_pinned_window_sends_the_window_target_and_never_activates(monkeypatch):
    scripts = []

    async def fake_run(script, timeout_s=30.0):
        scripts.append(script)
        return True, "ok|100|80|1200|800|Annual Report", ""

    captured = {}

    async def fake_capture(reason, **kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "image_path": "/tmp/shot.png",
            "app_name": "Google Chrome",
            "window_title": "Annual Report - Google Chrome",
            "capture_method": "swift_window_service",
        }

    monkeypatch.setattr(capture_target, "run_applescript", fake_run)
    monkeypatch.setattr(screenshot_tool, "request_swift_window_capture", fake_capture)

    result = json.loads(
        await screenshot_tool._browser_screenshot_impl(
            browser="Chrome",
            browser_automation_target={"browser": "Chrome", "window_id": 42, "created_by_basil": True},
        )
    )

    assert result["success"] is True
    assert result["capture_scope"] == "automation_window"
    assert "warning" not in result
    assert captured["window_target"]["owner_name"] == "Google Chrome"
    assert captured["window_target"]["bounds"]["width"] == 1200.0
    assert len(scripts) == 1
    assert "activate" not in scripts[0].lower()


@pytest.mark.asyncio
async def test_screenshot_of_a_missing_pinned_window_fails_instead_of_capturing_another_app(monkeypatch):
    async def fake_run(script, timeout_s=30.0):
        return True, "error|window_missing", ""

    async def fake_capture(reason, **kwargs):
        raise AssertionError("must not capture when the pinned window cannot be located")

    monkeypatch.setattr(capture_target, "run_applescript", fake_run)
    monkeypatch.setattr(screenshot_tool, "request_swift_window_capture", fake_capture)

    result = json.loads(
        await screenshot_tool._browser_screenshot_impl(
            browser="Chrome",
            browser_automation_target={"browser": "Chrome", "window_id": 42, "created_by_basil": True},
        )
    )

    assert result["success"] is False
    assert "no longer exists" in result["error"]


@pytest.mark.asyncio
async def test_screenshot_without_a_pinned_window_keeps_the_active_window_behavior(monkeypatch):
    captured = {}

    async def fake_capture(reason, **kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "image_path": "/tmp/shot.png",
            "app_name": "Google Chrome",
            "window_title": "Anything",
            "capture_method": "swift_window_service",
        }

    monkeypatch.setattr(screenshot_tool, "request_swift_window_capture", fake_capture)

    result = json.loads(await screenshot_tool._browser_screenshot_impl(browser="Chrome"))

    assert result["success"] is True
    assert captured["window_target"] is None
    assert "capture_scope" not in result
