"""Reveal, release, and human-help handoff of Basil's automation window."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import pytest

from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_pinned_target,
    browser_tabs_tool,
    browser_window_handoff,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_foreground_policy import (
    ForegroundDecision,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_target_runtime import (
    BrowserAutomationTarget,
)
from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import CheckpointRequest

TASK_KEY = "handoff-task"
TARGET = BrowserAutomationTarget(browser="Chrome", window_index=1, tab_index=1, expected_title="Basil window", window_id=77)
ALLOW = ForegroundDecision(True, "allowed_by_policy", "allow_foreground_when_needed", "Foreground control is allowed by the user's setting.")
BLOCK = ForegroundDecision(False, "blocked_by_policy", "background_only", "Foreground browser control is turned off in Basil's Browser Automation settings.")
REVEAL_OK = (True, "ok|Cursor|com.todesktop.cursor", "")


class FakeAppleScript:
    def __init__(self, replies: List[Tuple[bool, str, str]]):
        self.replies = list(replies)
        self.scripts: List[str] = []

    async def __call__(self, script, *args, **kwargs):
        self.scripts.append(script)
        return self.replies.pop(0)


@pytest.fixture(autouse=True)
def isolated_state():
    browser_pinned_target.clear_pinned_browser_targets()
    browser_window_handoff._revealed.clear()
    token = set_current_agent_context({"root_task_id": TASK_KEY})
    yield
    reset_current_agent_context(token)
    browser_pinned_target.clear_pinned_browser_targets()
    browser_window_handoff._revealed.clear()


@pytest.fixture
def policy(monkeypatch):
    """Patch the foreground gate; the decision and the recorded calls are on the returned object."""

    class Gate:
        decision = ALLOW
        calls: List[Dict[str, Any]] = []

    Gate.calls = []

    async def fake_authorize(**kwargs):
        Gate.calls.append(kwargs)
        return Gate.decision

    monkeypatch.setattr(browser_window_handoff, "authorize_browser_foreground", fake_authorize)
    return Gate


def use_applescript(monkeypatch, replies) -> FakeAppleScript:
    fake = FakeAppleScript(replies)
    monkeypatch.setattr(browser_window_handoff, "run_applescript", fake)
    return fake


@pytest.mark.asyncio
async def test_reveal_brings_the_window_forward_and_remembers_the_previous_app(monkeypatch, policy):
    script = use_applescript(monkeypatch, [REVEAL_OK])

    result = await browser_window_handoff.reveal_automation_window("Chrome", TARGET, purpose="Show the CAPTCHA")

    assert result["success"] is True
    assert result["previous_app"] == "Cursor"
    assert 'tell application "Google Chrome"' in script.scripts[0]
    assert "window id 77" in script.scripts[0]
    assert policy.calls[0]["browser"] == "Google Chrome"
    state = browser_window_handoff._revealed[TASK_KEY]
    assert (state.owner_name, state.window_id, state.previous_app_name, state.previous_bundle_id) == (
        "Google Chrome",
        77,
        "Cursor",
        "com.todesktop.cursor",
    )


@pytest.mark.asyncio
async def test_reveal_is_blocked_by_policy_without_running_any_script(monkeypatch, policy):
    policy.decision = BLOCK
    script = use_applescript(monkeypatch, [])

    result = await browser_window_handoff.reveal_automation_window("Chrome", TARGET, purpose="Show the CAPTCHA")

    assert result["success"] is False
    assert result["foreground_blocked"] is True
    assert result["reason"] == "blocked_by_policy"
    assert script.scripts == []
    assert browser_window_handoff._revealed == {}


@pytest.mark.asyncio
async def test_reveal_that_is_already_authorized_skips_the_policy_check(monkeypatch, policy):
    use_applescript(monkeypatch, [REVEAL_OK])

    result = await browser_window_handoff.reveal_automation_window("Chrome", TARGET, purpose="Press keys", authorized=True)

    assert result["success"] is True
    assert policy.calls == []


@pytest.mark.asyncio
async def test_reveal_without_a_window_explains_how_to_create_one(monkeypatch, policy):
    script = use_applescript(monkeypatch, [])

    result = await browser_window_handoff.reveal_automation_window("Chrome", None, purpose="Show the CAPTCHA")

    assert result["success"] is False
    assert "ensure_automation_window" in result["error"]
    assert script.scripts == []


@pytest.mark.asyncio
async def test_reveal_reports_a_window_that_no_longer_exists(monkeypatch, policy):
    use_applescript(monkeypatch, [(True, "error|window_missing", "")])

    result = await browser_window_handoff.reveal_automation_window("Chrome", TARGET, purpose="Show the CAPTCHA")

    assert result["success"] is False
    assert "ensure_automation_window" in result["error"]
    assert browser_window_handoff._revealed == {}


@pytest.mark.asyncio
async def test_reveal_surfaces_an_applescript_failure(monkeypatch, policy):
    use_applescript(monkeypatch, [(False, "", "boom")])

    result = await browser_window_handoff.reveal_automation_window("Chrome", TARGET, purpose="Show the CAPTCHA")

    assert result["success"] is False
    assert result["error"] == "boom"


@pytest.mark.asyncio
async def test_release_restores_the_previous_app_by_bundle_id(monkeypatch, policy):
    script = use_applescript(monkeypatch, [REVEAL_OK, (True, "restored", "")])
    await browser_window_handoff.reveal_automation_window("Chrome", TARGET, purpose="Show the CAPTCHA")

    result = await browser_window_handoff.release_automation_window("Chrome")

    assert result["released"] is True
    assert result["restored_app"] == "Cursor"
    assert 'tell application id "com.todesktop.cursor" to activate' in script.scripts[1]
    assert 'if frontName is not "Google Chrome" then return "skipped|user_moved_on"' in script.scripts[1]
    assert browser_window_handoff._revealed == {}


@pytest.mark.asyncio
async def test_release_falls_back_to_the_app_name_without_a_bundle_id(monkeypatch, policy):
    script = use_applescript(monkeypatch, [(True, "ok|Cursor|", ""), (True, "restored", "")])
    await browser_window_handoff.reveal_automation_window("Chrome", TARGET, purpose="Show the CAPTCHA")

    await browser_window_handoff.release_automation_window("Chrome")

    assert 'tell application "Cursor" to activate' in script.scripts[1]


@pytest.mark.asyncio
async def test_release_changes_nothing_when_the_user_already_moved_on(monkeypatch, policy):
    use_applescript(monkeypatch, [REVEAL_OK, (True, "skipped|user_moved_on", "")])
    await browser_window_handoff.reveal_automation_window("Chrome", TARGET, purpose="Show the CAPTCHA")

    result = await browser_window_handoff.release_automation_window("Chrome")

    assert result["success"] is True
    assert result["released"] is False
    assert "already switched away" in result["note"]


@pytest.mark.asyncio
async def test_release_is_a_no_op_when_the_browser_was_already_in_front(monkeypatch, policy):
    script = use_applescript(monkeypatch, [(True, "ok|Google Chrome|com.google.Chrome", "")])
    await browser_window_handoff.reveal_automation_window("Chrome", TARGET, purpose="Show the CAPTCHA")

    result = await browser_window_handoff.release_automation_window("Chrome")

    assert result["success"] is True
    assert result["released"] is False
    assert len(script.scripts) == 1


@pytest.mark.asyncio
async def test_release_without_a_reveal_does_nothing(monkeypatch, policy):
    script = use_applescript(monkeypatch, [])

    result = await browser_window_handoff.release_automation_window("Chrome")

    assert result["success"] is True
    assert result["released"] is False
    assert script.scripts == []


@pytest.mark.parametrize(
    ("reply", "expected_ok", "previous_name", "previous_bundle"),
    [
        ("ok|Cursor|com.todesktop.cursor", True, "Cursor", "com.todesktop.cursor"),
        ("ok||", True, "", ""),
        ("error|window_missing", False, "", ""),
        ("garbage", False, "", ""),
        ("", False, "", ""),
    ],
)
def test_parse_reveal_reply(reply, expected_ok, previous_name, previous_bundle):
    ok, name, bundle, error = browser_window_handoff.parse_reveal_reply(reply)

    assert ok is expected_ok
    assert (name, bundle) == (previous_name, previous_bundle)
    assert (error is None) is expected_ok


def test_scripts_escape_quotes_in_app_names():
    reveal = browser_window_handoff.build_reveal_script('Odd "Name"', 5)
    release = browser_window_handoff.build_release_script("Chrome", 'Odd "App"', "")

    assert 'tell application "Odd \\"Name\\""' in reveal
    assert 'tell application "Odd \\"App\\"" to activate' in release


@pytest.mark.asyncio
async def test_request_human_help_with_the_window_shown_asks_the_user(monkeypatch, policy):
    use_applescript(monkeypatch, [REVEAL_OK])

    with pytest.raises(CheckpointRequest) as raised:
        await browser_window_handoff.request_human_help("Chrome", TARGET, "Please solve the CAPTCHA")

    payload = raised.value.checkpoint_data
    assert "brought the Basil browser window to the front" in payload["prompt"]
    assert "Please solve the CAPTCHA" in payload["prompt"]
    assert [option["value"] for option in payload["options"]] == ["browser_human_help_done", "browser_human_help_stop"]
    assert payload["metadata"]["window_revealed"] is True
    assert payload["input_type"] == "choice"


@pytest.mark.asyncio
async def test_request_human_help_when_blocked_still_asks_and_names_the_window(monkeypatch, policy):
    policy.decision = BLOCK
    script = use_applescript(monkeypatch, [])

    with pytest.raises(CheckpointRequest) as raised:
        await browser_window_handoff.request_human_help("Chrome", TARGET, "Please solve the CAPTCHA")

    payload = raised.value.checkpoint_data
    assert "could not bring the browser window forward" in payload["prompt"]
    assert "Basil window" in payload["prompt"]
    assert payload["metadata"]["window_revealed"] is False
    assert script.scripts == []


@pytest.mark.asyncio
async def test_request_human_help_without_any_window_still_asks(monkeypatch, policy):
    use_applescript(monkeypatch, [])

    with pytest.raises(CheckpointRequest) as raised:
        await browser_window_handoff.request_human_help("Chrome", None, None)

    payload = raised.value.checkpoint_data
    assert "This step needs you." in payload["prompt"]
    assert "the Basil browser window" in payload["prompt"]
    assert payload["metadata"]["window_revealed"] is False


@pytest.mark.asyncio
async def test_browser_tabs_routes_the_three_handoff_actions(monkeypatch, policy):
    browser_pinned_target.pin_browser_target(TARGET)
    script = use_applescript(monkeypatch, [REVEAL_OK, (True, "restored", "")])

    with pytest.raises(CheckpointRequest):
        await browser_tabs_tool._browser_tabs_impl(browser="Chrome", action="request_human_help", reason="Please solve the CAPTCHA")
    released = json.loads(await browser_tabs_tool._browser_tabs_impl(browser="Chrome", action="release_automation_window"))

    assert released["success"] is True
    assert released["released"] is True
    assert released["browser"] == "Chrome"
    assert len(script.scripts) == 2


@pytest.mark.asyncio
async def test_browser_tabs_reveal_uses_the_pinned_window(monkeypatch, policy):
    browser_pinned_target.pin_browser_target(TARGET)
    script = use_applescript(monkeypatch, [REVEAL_OK])

    revealed = json.loads(await browser_tabs_tool._browser_tabs_impl(browser="Chrome", action="reveal_automation_window", reason="Show the page"))

    assert revealed["success"] is True
    assert "window id 77" in script.scripts[0]
    assert policy.calls[0]["purpose"] == "Show the page"


def test_handoff_actions_are_exactly_the_three_new_actions():
    assert browser_window_handoff.HANDOFF_ACTIONS == frozenset({"reveal_automation_window", "release_automation_window", "request_human_help"})
