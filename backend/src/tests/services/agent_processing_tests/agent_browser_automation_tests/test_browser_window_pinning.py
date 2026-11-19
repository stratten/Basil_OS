"""One dedicated, pinned browser window per task chain."""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest

from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_pinned_target,
    browser_runtime,
    browser_tabs_tool,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation.browser_target_runtime import (
    BrowserAutomationTarget,
    parse_browser_automation_target,
    resolve_browser_target_inputs,
)

JS = "return JSON.stringify({success:true})"


@pytest.fixture(autouse=True)
def _clear_pins():
    browser_pinned_target.clear_pinned_browser_targets()
    yield
    browser_pinned_target.clear_pinned_browser_targets()


@contextmanager
def agent_context(agent_task_id: str = "turn-1", root_task_id: str | None = "root-1"):
    token = set_current_agent_context({"agent_task_id": agent_task_id, "root_task_id": root_task_id})
    try:
        yield
    finally:
        reset_current_agent_context(token)


def pin_chrome_window(window_id: int = 4242) -> BrowserAutomationTarget:
    target = BrowserAutomationTarget(browser="Chrome", created_by_basil=True, window_id=window_id)
    browser_pinned_target.pin_browser_target(target)
    return target


def scripted(outputs: list[str], calls: list[str]):
    async def fake_run_applescript(script: str, timeout_s: float = 30.0):
        calls.append(script)
        return True, outputs.pop(0), ""

    return fake_run_applescript


@pytest.mark.asyncio
async def test_follow_up_in_the_same_chain_reuses_the_window(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        browser_tabs_tool,
        "run_applescript",
        scripted(["created_window|4242|https://example.com", "reused_window|4242|https://example.com/next"], calls),
    )

    with agent_context("turn-1", "root-1"):
        first = json.loads(await browser_tabs_tool._browser_tabs_impl(
            browser="Chrome", action="ensure_automation_window", url="https://example.com",
        ))
    with agent_context("turn-2", "root-1"):
        second = json.loads(await browser_tabs_tool._browser_tabs_impl(
            browser="Chrome", action="ensure_automation_window", url="https://example.com/next",
        ))

    assert first["reused_window"] is False
    assert first["browser_automation_target"]["window_id"] == 4242
    assert first["browser_automation_target"]["agent_task_id"] == "turn-1"
    assert "exists window id" not in calls[0]
    assert "if exists window id 4242 then" in calls[1]
    assert 'set URL of active tab of targetWindow to "https://example.com/next"' in calls[1]
    assert second["reused_window"] is True
    assert second["browser_automation_target"]["window_id"] == 4242
    assert second["browser_automation_target"]["agent_task_id"] == "turn-2"


@pytest.mark.asyncio
async def test_reuse_without_a_url_keeps_the_current_page(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(browser_tabs_tool, "run_applescript", scripted(["reused_window|77|https://kept.example"], calls))

    with agent_context():
        browser_pinned_target.pin_browser_target(BrowserAutomationTarget(browser="Safari", window_id=77))
        result = json.loads(await browser_tabs_tool._browser_tabs_impl(browser="Safari", action="ensure_automation_window"))

    assert "set URL of current tab of targetWindow" not in calls[0]
    assert "set currentUrl to URL of current tab of targetWindow" in calls[0]
    assert result["browser_automation_target"]["expected_url"] == "https://kept.example"


@pytest.mark.asyncio
async def test_a_different_chain_gets_its_own_window(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(browser_tabs_tool, "run_applescript", scripted(["created_window|5|about:blank"], calls))

    with agent_context("turn-1", "root-1"):
        pin_chrome_window(4242)
    with agent_context("other-turn", "other-root"):
        await browser_tabs_tool._browser_tabs_impl(browser="Chrome", action="ensure_automation_window")

    assert "exists window id" not in calls[0]


@pytest.mark.asyncio
async def test_unreadable_ensure_output_is_reported_and_not_pinned(monkeypatch):
    monkeypatch.setattr(browser_tabs_tool, "run_applescript", scripted(["created_window|not-a-number|x"], []))

    with agent_context():
        result = json.loads(await browser_tabs_tool._browser_tabs_impl(browser="Chrome", action="ensure_automation_window"))
        assert browser_pinned_target.pinned_browser_target("Chrome") is None

    assert result["success"] is False
    assert "Could not identify Basil's browser window" in result["error"]


@pytest.mark.asyncio
async def test_list_marks_the_tabs_in_basils_window(monkeypatch):
    rows = "\n".join([
        "1|1|true|4242|Basil ⎮ search|https://a.example",
        "2|1|true|99|Mine|https://b.example",
    ])
    monkeypatch.setattr(browser_tabs_tool, "run_applescript", scripted([rows], []))

    with agent_context():
        pin_chrome_window(4242)
        result = json.loads(await browser_tabs_tool._browser_tabs_impl(browser="Chrome", action="list"))

    assert [(tab["window_id"], tab["basil_window"]) for tab in result["tabs"]] == [(4242, True), (99, False)]
    assert result["tabs"][0]["title"] == "Basil | search"


def test_scripts_target_the_pinned_window_when_no_other_tab_is_named():
    with agent_context():
        pin_chrome_window(4242)
        chrome = browser_runtime.build_browser_applescript("Chrome", JS)
        chrome_same_target = browser_runtime.build_browser_applescript("Chrome", JS, window_index=1, tab_index=1)

    for script in (chrome, chrome_same_target):
        assert "if not (exists window id 4242) then" in script
        assert "execute active tab of window id 4242 javascript" in script
        assert "active tab of window 1" not in script


def test_safari_and_edge_scripts_use_the_window_id():
    with agent_context():
        browser_pinned_target.pin_browser_target(BrowserAutomationTarget(browser="Safari", window_id=12))
        safari = browser_runtime.build_browser_applescript("Safari", JS)
    with agent_context("turn-9", "root-9"):
        browser_pinned_target.pin_browser_target(BrowserAutomationTarget(browser="Edge", window_id=13))
        edge = browser_runtime.build_browser_applescript("Microsoft Edge", JS)

    assert "in current tab of window id 12" in safari
    assert 'tell application "Microsoft Edge"' in edge
    assert "execute active tab of window id 13 javascript" in edge


def test_explicit_other_tabs_and_other_browsers_keep_index_addressing():
    with agent_context():
        pin_chrome_window(4242)
        other_tab = browser_runtime.build_browser_applescript("Chrome", JS, window_index=2, tab_index=3)
        other_browser = browser_runtime.build_browser_applescript("Safari", JS)

    assert "execute tab 3 of window 2 javascript" in other_tab
    assert "window id" not in other_tab
    assert "window id" not in other_browser


def test_scripts_outside_an_agent_run_never_use_a_pin():
    with agent_context():
        pin_chrome_window(4242)
    script = browser_runtime.build_browser_applescript("Chrome", JS)

    assert "window id" not in script


def test_closed_window_returns_a_parseable_instruction():
    script = browser_runtime.build_browser_applescript("Chrome", JS, window_id=4242)
    literal = script.split('return "', 1)[1].split('"\n    end if', 1)[0]
    payload = json.loads(literal.replace('\\"', '"').replace("\\\\", "\\"))

    assert payload["success"] is False
    assert payload["browser_window_closed"] is True
    assert "ensure_automation_window" in payload["error"]


def test_tools_fall_back_to_the_pinned_target():
    with agent_context():
        pinned = pin_chrome_window(4242)
        resolved = resolve_browser_target_inputs(browser=None)
        explicit = resolve_browser_target_inputs(browser=None, window_index=2, tab_index=1)

    assert resolved == ("Chrome", 1, 1, pinned)
    assert explicit == (None, 2, 1, None)


def test_a_target_passed_back_with_a_window_id_is_pinned_for_the_chain():
    returned = {"browser": "Chrome", "window_index": 1, "tab_index": 1, "window_id": 555, "created_by_basil": True}

    with agent_context("turn-3", "root-3"):
        resolve_browser_target_inputs(browser=None, browser_automation_target=returned)
        pinned = browser_pinned_target.pinned_browser_target("Google Chrome")

    assert pinned == parse_browser_automation_target(returned)
    assert pinned is not None and pinned.window_id == 555


def test_root_task_falls_back_to_its_own_id_as_the_chain_key():
    with agent_context("root-only", None):
        assert browser_pinned_target.browser_pin_key() == "root-only"
