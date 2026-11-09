"""browser_native_input: allow-listed keys only, policy gated, pinned window only, always released."""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError

from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_native_input_tool,
    browser_pinned_target,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_foreground_policy import (
    ForegroundDecision,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_target_runtime import (
    BrowserAutomationTarget,
)

TARGET = BrowserAutomationTarget(browser="Chrome", window_index=1, tab_index=1, expected_title="Basil window", window_id=77)
ALLOW = ForegroundDecision(True, "allowed_by_policy", "allow_foreground_when_needed", "Foreground control is allowed by the user's setting.")
BLOCK = ForegroundDecision(False, "blocked_by_policy", "background_only", "Foreground browser control is turned off in Basil's Browser Automation settings.")
PURPOSE = "Choose the saved card in the payment frame"
STEPS = [{"key": "down", "count": 2}, {"key": "return", "count": 1}]
FOCUS_OK = (True, json.dumps({"success": True, "focused": True}), "")


class Harness:
    """Records the order of side effects and lets each test script the replies."""

    def __init__(self) -> None:
        self.events: List[str] = []
        self.scripts: Dict[str, str] = {}
        self.decision = ALLOW
        self.probe_reply = (True, "true", "")
        self.focus_reply = FOCUS_OK
        self.keys_reply = (True, "ok", "")
        self.keys_error: Exception | None = None
        self.reveal_result: Dict[str, Any] = {"success": True, "revealed": True}
        self.reveal_kwargs: Dict[str, Any] = {}


@pytest.fixture
def harness(monkeypatch):
    state = Harness()

    async def fake_authorize(**kwargs):
        state.events.append("authorize")
        return state.decision

    async def fake_applescript(script, *args, **kwargs):
        if script == browser_native_input_tool.ACCESSIBILITY_PROBE_SCRIPT:
            state.events.append("probe")
            return state.probe_reply
        if "basil:native_focus" in script:
            state.events.append("focus")
            state.scripts["focus"] = script
            return state.focus_reply
        if "key code" in script:
            state.events.append("keys")
            state.scripts["keys"] = script
            if state.keys_error is not None:
                raise state.keys_error
            return state.keys_reply
        raise AssertionError(f"Unexpected AppleScript: {script[:80]}")

    async def fake_reveal(browser, target, *, purpose, authorized=False):
        state.events.append("reveal")
        state.reveal_kwargs = {"purpose": purpose, "authorized": authorized}
        return state.reveal_result

    async def fake_release(browser):
        state.events.append("release")
        return {"success": True, "released": True}

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(browser_native_input_tool, "authorize_browser_foreground", fake_authorize)
    monkeypatch.setattr(browser_native_input_tool, "run_applescript", fake_applescript)
    monkeypatch.setattr(browser_native_input_tool, "reveal_automation_window", fake_reveal)
    monkeypatch.setattr(browser_native_input_tool, "release_automation_window", fake_release)
    monkeypatch.setattr(browser_native_input_tool, "_sleep", no_sleep)
    return state


@pytest.fixture(autouse=True)
def pinned_window():
    browser_pinned_target.clear_pinned_browser_targets()
    token = set_current_agent_context({"root_task_id": "native-input-task"})
    browser_pinned_target.pin_browser_target(TARGET)
    yield
    reset_current_agent_context(token)
    browser_pinned_target.clear_pinned_browser_targets()


async def run_tool(**overrides) -> Dict[str, Any]:
    arguments = {"purpose": PURPOSE, "steps": STEPS, **overrides}
    return json.loads(await browser_native_input_tool._browser_native_input_impl(**arguments))


def test_normalize_steps_accepts_dicts_and_models():
    model_step = browser_native_input_tool.NativeKeyStep(key="tab", count=3)

    normalized, error = browser_native_input_tool.normalize_steps([{"key": "down", "count": 2}, model_step])

    assert error is None
    assert normalized == [("down", 2), ("tab", 3)]


@pytest.mark.parametrize(
    ("steps", "fragment"),
    [
        ([{"key": "a", "count": 1}], "not allowed"),
        ([{"key": "cmd", "count": 1}], "not allowed"),
        ([{"key": "tab", "count": 0}], "at least 1"),
        ([{"key": "tab", "count": "many"}], "whole number"),
        ([{"key": "tab", "count": 10}, {"key": "down", "count": 10}, {"key": "up", "count": 1}], "At most 20"),
        ([], "at least one step"),
    ],
)
def test_normalize_steps_rejects_bad_input(steps, fragment):
    normalized, error = browser_native_input_tool.normalize_steps(steps)

    assert normalized == []
    assert fragment in error


def test_key_script_sends_only_key_codes_never_text():
    script = browser_native_input_tool.build_key_script("Google Chrome", [("down", 2), ("shift_tab", 1), ("return", 1)])

    assert "keystroke" not in script
    assert script.count("key code 125") == 2
    assert "key code 48 using shift down" in script
    assert script.count("key code 36") == 1
    assert 'if frontName is not "Google Chrome" then return "error|focus_lost|" & frontName' in script
    assert script.index("key code 125") < script.index("key code 48 using shift down") < script.index("key code 36")


@pytest.mark.asyncio
async def test_success_follows_the_expected_order_and_restores_the_previous_app(harness):
    result = await run_tool()

    assert harness.events == ["authorize", "probe", "reveal", "keys", "release"]
    assert harness.reveal_kwargs["authorized"] is True
    assert result["success"] is True
    assert result["keys_sent"] == 3
    assert result["steps"] == [{"key": "down", "count": 2}, {"key": "return", "count": 1}]
    assert result["restored_previous_app"] is True
    assert result["browser"] == "Chrome"
    assert "browser_screenshot" in result["next_step"]


@pytest.mark.asyncio
async def test_focus_selector_is_focused_before_the_keys(harness):
    result = await run_tool(focus_selector="iframe[title='Saved cards']")

    assert harness.events == ["authorize", "probe", "reveal", "focus", "keys", "release"]
    assert result["success"] is True


@pytest.mark.asyncio
async def test_blocked_policy_sends_nothing_and_touches_no_window(harness):
    harness.decision = BLOCK

    result = await run_tool()

    assert harness.events == ["authorize"]
    assert result["success"] is False
    assert result["foreground_blocked"] is True
    assert result["reason"] == "blocked_by_policy"
    assert "request_human_help" in result["next_step"]


@pytest.mark.asyncio
async def test_without_a_pinned_window_nothing_happens(harness):
    browser_pinned_target.clear_pinned_browser_targets()

    result = await run_tool(browser="Chrome")

    assert harness.events == []
    assert result["success"] is False
    assert "ensure_automation_window" in result["error"]


@pytest.mark.asyncio
async def test_accessibility_off_stops_before_the_window_is_revealed(harness):
    harness.probe_reply = (True, "false", "")

    result = await run_tool()

    assert harness.events == ["authorize", "probe"]
    assert result["accessibility_blocked"] is True
    assert result["requires_user_input"] is True
    assert "Accessibility" in result["error"]


@pytest.mark.asyncio
async def test_an_inconclusive_accessibility_probe_does_not_block(harness):
    harness.probe_reply = (False, "", "probe failed")

    result = await run_tool()

    assert result["success"] is True
    assert "reveal" in harness.events


@pytest.mark.asyncio
async def test_keystroke_permission_error_is_mapped_and_the_window_is_still_released(harness):
    harness.keys_reply = (False, "", "execution error: osascript is not allowed to send keystrokes. (1002)")

    result = await run_tool()

    assert result["accessibility_blocked"] is True
    assert harness.events[-1] == "release"


@pytest.mark.asyncio
async def test_browser_not_in_front_sends_no_keys_and_is_released(harness):
    harness.keys_reply = (True, "error|focus_lost|Cursor", "")

    result = await run_tool()

    assert result["success"] is False
    assert "no longer in front" in result["error"]
    assert harness.events[-1] == "release"


@pytest.mark.asyncio
async def test_failed_focus_sends_no_keys_and_is_released(harness):
    harness.focus_reply = (True, json.dumps({"success": False, "error": "focus_selector matched no element."}), "")

    result = await run_tool(focus_selector="#missing")

    assert result["success"] is False
    assert result["error"] == "focus_selector matched no element."
    assert "keys" not in harness.events
    assert harness.events[-1] == "release"


@pytest.mark.asyncio
async def test_unexpected_error_while_sending_still_releases_the_window(harness):
    harness.keys_error = RuntimeError("osascript crashed")

    result = await run_tool()

    assert result["success"] is False
    assert "Native input failed" in result["error"]
    assert harness.events[-1] == "release"


@pytest.mark.asyncio
async def test_failed_reveal_is_reported_and_nothing_is_sent(harness):
    harness.reveal_result = {"success": False, "action": "reveal_automation_window", "error": "window is gone"}

    result = await run_tool()

    assert harness.events == ["authorize", "probe", "reveal"]
    assert result["success"] is False
    assert result["error"] == "window is gone"


@pytest.mark.asyncio
async def test_missing_purpose_and_bad_steps_are_rejected_before_any_side_effect(harness):
    short = await run_tool(purpose="short")
    bad = await run_tool(steps=[{"key": "a", "count": 1}])

    assert short["success"] is False and "purpose" in short["error"]
    assert bad["success"] is False and "not allowed" in bad["error"]
    assert harness.events == []


def test_schema_refuses_text_keys_oversized_counts_and_empty_steps():
    with pytest.raises(ValidationError):
        browser_native_input_tool.NativeKeyStep(key="a")
    with pytest.raises(ValidationError):
        browser_native_input_tool.NativeKeyStep(key="tab", count=11)
    with pytest.raises(ValidationError):
        browser_native_input_tool.BrowserNativeInputInput(purpose="Choose the saved card", steps=[])
    with pytest.raises(ValidationError):
        browser_native_input_tool.BrowserNativeInputInput(purpose="short", steps=[{"key": "tab"}])


def test_tool_is_named_and_described_for_the_agent():
    tool = browser_native_input_tool.create_browser_native_input_tool()

    assert tool.name == "browser_native_input"
    assert "never text" in tool.description or "Never read card numbers" in tool.description
    assert set(tool.args_schema.model_json_schema()["properties"]) >= {"purpose", "steps", "focus_selector", "browser", "browser_automation_target"}
