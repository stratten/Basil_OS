"""Unit coverage for Basil browser automation tools."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.services.agent_processing.lifecycle.execution_graph.service_tooling.optional_tool_registry import (
    register_optional_tools,
)
from api.services.agent_processing.shared.agent_runtime_context import (
    reset_current_agent_context,
    set_current_agent_context,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_runtime,
    browser_inspect_tool,
    browser_interact_tool,
    browser_tabs_tool,
)
from api.services.agent_processing.tools.direct_application_interactions.browser_automation import (
    browser_target_runtime,
)
from api.core.models.preferences import BrowserPreferredUserBrowser, Preferences
from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import CheckpointRequest


class _FakeProcess:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode

    async def communicate(self):
        return self._stdout, self._stderr


class _HangingProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False
        self.killed = False
        self._done = browser_runtime.asyncio.Event()

    async def communicate(self):
        await self._done.wait()
        return b"", b""

    def terminate(self):
        self.terminated = True
        self.returncode = -15
        self._done.set()

    def kill(self):
        self.killed = True
        self.returncode = -9
        self._done.set()

    async def wait(self):
        await self._done.wait()
        return self.returncode


class _FakeLogger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass


@pytest.mark.asyncio
async def test_default_browser_firefox_falls_back_to_safari(monkeypatch):
    preferences = Preferences()

    from api.core.preferences import preferences_io

    monkeypatch.setattr(preferences_io, "load_preferences", lambda: preferences)

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return _FakeProcess(b'LSHandlerRoleAll = "org.mozilla.firefox";')

    monkeypatch.setattr(
        browser_runtime.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    assert await browser_inspect_tool._get_default_browser() == "Safari"


def test_browser_optional_tools_are_registered():
    tools = []
    tool_map = {}
    optional_warnings = []
    factory = SimpleNamespace(logger=_FakeLogger(), profile=None)

    register_optional_tools(factory, tools, tool_map, optional_warnings)

    assert "browser.inspect" in tool_map
    assert "browser.interact" in tool_map
    assert "browser.highlight" in tool_map
    assert "browser.tabs" in tool_map
    assert "browser.screenshot" in tool_map
    assert tool_map["browser.inspect"].name == "browser_inspect"
    assert tool_map["browser.interact"].name == "browser_interact"
    assert tool_map["browser.highlight"].name == "browser_highlight"
    assert tool_map["browser.tabs"].name == "browser_tabs"
    assert tool_map["browser.screenshot"].name == "browser_screenshot"


def test_inspect_javascript_supports_modern_dom_surfaces():
    inspect_js = browser_inspect_tool._INSPECT_JS_CODE

    assert "shadowRoot" in inspect_js
    assert "contentDocument" in inspect_js
    assert "skippedFrames" in inspect_js
    assert "requires_user_input" in inspect_js


def test_inspect_javascript_captures_capped_main_text():
    inspect_js = browser_inspect_tool._INSPECT_JS_CODE

    assert "mainReadableText" in inspect_js
    assert "info.mainText" in inspect_js
    # The readable-text cap must not be silently removed.
    assert "12000" in inspect_js


def _fake_inspect_page_json(*, main_text: str) -> str:
    return browser_runtime.json.dumps({
        "url": "https://example.com",
        "title": "Example",
        "ready": "complete",
        "buttons": [{"selector": "#buy", "text": "Buy"}],
        "inputs": [],
        "links": [{"selector": "a#first", "text": "Result", "href": "https://r.com"}],
        "headings": ["Example Heading"],
        "skippedFrames": [],
        "requires_user_input": False,
        "safety_warnings": [],
        "mainText": main_text,
    })


@pytest.mark.asyncio
async def test_inspect_focus_content_returns_main_text(monkeypatch):
    async def fake_run_applescript(script: str, timeout_s: float = 30.0):
        return True, _fake_inspect_page_json(main_text="Hello world body text."), ""

    monkeypatch.setattr(browser_inspect_tool, "run_applescript", fake_run_applescript)

    result = await browser_inspect_tool._browser_inspect_impl(
        browser="Chrome",
        focus="content",
    )
    parsed = browser_runtime.json.loads(result)

    assert parsed["success"] is True
    assert parsed["mainText"] == "Hello world body text."
    # Content focus must not carry interaction surfaces.
    assert "buttons" not in parsed
    assert "links" not in parsed
    assert "headings" not in parsed


@pytest.mark.asyncio
async def test_inspect_focus_all_strips_main_text(monkeypatch):
    async def fake_run_applescript(script: str, timeout_s: float = 30.0):
        return True, _fake_inspect_page_json(main_text="Body text that must not leak."), ""

    monkeypatch.setattr(browser_inspect_tool, "run_applescript", fake_run_applescript)

    result = await browser_inspect_tool._browser_inspect_impl(
        browser="Chrome",
        focus="all",
    )
    parsed = browser_runtime.json.loads(result)

    assert parsed["success"] is True
    # Backward compatibility: the default 'all' payload stays lean.
    assert "mainText" not in parsed
    assert "buttons" in parsed
    assert "links" in parsed


@pytest.mark.asyncio
async def test_inspect_focus_content_preserves_quotes_and_newlines(monkeypatch):
    tricky = 'Line one with "quotes"\nLine two\twith tab\nLine three.'

    async def fake_run_applescript(script: str, timeout_s: float = 30.0):
        return True, _fake_inspect_page_json(main_text=tricky), ""

    monkeypatch.setattr(browser_inspect_tool, "run_applescript", fake_run_applescript)

    result = await browser_inspect_tool._browser_inspect_impl(
        browser="Chrome",
        focus="content",
    )
    parsed = browser_runtime.json.loads(result)

    # The page text must survive JSON parse/filter/re-serialize unchanged.
    assert parsed["mainText"] == tricky


@pytest.mark.asyncio
async def test_inspect_focus_content_handles_empty_body(monkeypatch):
    async def fake_run_applescript(script: str, timeout_s: float = 30.0):
        return True, _fake_inspect_page_json(main_text=""), ""

    monkeypatch.setattr(browser_inspect_tool, "run_applescript", fake_run_applescript)

    result = await browser_inspect_tool._browser_inspect_impl(
        browser="Chrome",
        focus="content",
    )
    parsed = browser_runtime.json.loads(result)

    assert parsed["success"] is True
    assert parsed["mainText"] == ""


def test_interact_wait_uses_non_blocking_polling():
    wait_js = browser_interact_tool._build_action_js("wait", "#ready", None)

    assert "setTimeout" in wait_js
    assert "while (Date.now()" not in wait_js
    assert "attempts" in wait_js
    assert "queryDeep(selector)" in wait_js


def test_interact_schema_accepts_selectorless_wait():
    parsed = browser_interact_tool.BrowserInteractInput(action="wait")

    assert parsed.action == "wait"
    assert parsed.selector is None


def test_interact_selectorless_wait_uses_page_ready_path():
    wait_js = browser_interact_tool._build_action_js("wait", "", None)

    assert "wait_type: 'page_ready'" in wait_js
    assert "document.readyState" in wait_js
    assert "queryDeep(selector)" not in wait_js


def test_interact_wait_with_selector_preserves_element_polling_path():
    wait_js = browser_interact_tool._build_action_js("wait", "input[name='q']", None)

    assert "queryDeep(selector)" in wait_js
    assert "wait_type: 'page_ready'" not in wait_js


@pytest.mark.asyncio
async def test_interact_selectorless_wait_returns_page_ready_result(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_run_browser_js(
        browser: str,
        js_code: str,
        timeout: float = 30.0,
        *,
        window_index=None,
        tab_index=None,
    ):
        captured["browser"] = browser
        captured["js_code"] = js_code
        captured["timeout"] = timeout
        captured["window_index"] = window_index
        captured["tab_index"] = tab_index
        return {
            "success": True,
            "action": "wait",
            "wait_type": "page_ready",
            "ready": "complete",
            "url": "https://example.com",
            "title": "Example",
            "attempts": 1,
        }

    monkeypatch.setattr(browser_interact_tool, "_run_browser_js", fake_run_browser_js)

    result = await browser_interact_tool._browser_interact_impl(
        browser="Chrome",
        action="wait",
    )
    parsed = browser_runtime.json.loads(result)

    assert parsed["success"] is True
    assert parsed["wait_type"] == "page_ready"
    assert "queryDeep(selector)" not in str(captured["js_code"])
    assert captured["timeout"] == 45.0


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["click", "fill", "select", "scroll", "navigate"])
async def test_interact_missing_selector_returns_structured_error(action):
    result = await browser_interact_tool._browser_interact_impl(
        browser="Chrome",
        action=action,
        value="x" if action in {"fill", "select"} else None,
    )
    parsed = browser_runtime.json.loads(result)

    assert parsed["success"] is False
    assert parsed["action"] == action
    assert "requires" in parsed["error"]
    assert "selector" in parsed["error"] or "URL" in parsed["error"]


def test_interact_fill_refuses_password_like_selectors():
    fill_js = browser_interact_tool._build_action_js("fill", "input[type=password]", "secret")

    assert "Refusing to fill credential-like field" in fill_js
    assert "password" in fill_js.lower()


def test_browser_applescript_can_target_specific_tab():
    script = browser_runtime.build_browser_applescript(
        "Chrome",
        "return JSON.stringify({success:true})",
        window_index=3,
        tab_index=2,
    )

    assert "window 3" in script
    assert "execute tab 2 of window 3 javascript" in script
    assert "active tab of window 1" not in script


@pytest.mark.asyncio
async def test_preferred_user_browser_overrides_system_default(monkeypatch):
    preferences = Preferences()
    preferences.browser_automation.preferred_user_browser = BrowserPreferredUserBrowser.EDGE

    from api.core.preferences import preferences_io

    monkeypatch.setattr(preferences_io, "load_preferences", lambda: preferences)

    assert await browser_target_runtime.resolve_preferred_user_browser() == "Edge"


@pytest.mark.asyncio
async def test_browser_tabs_ensure_automation_window_returns_target(monkeypatch):
    calls: list[str] = []

    async def fake_run_applescript(script: str, timeout_s: float = 30.0):
        calls.append(script)
        if "make new window" in script:
            return True, "created_window|1|1|https://example.com", ""
        return True, "1|1|true|Example|https://example.com", ""

    monkeypatch.setattr(browser_tabs_tool, "run_applescript", fake_run_applescript)

    result = await browser_tabs_tool._browser_tabs_impl(
        browser="Chrome",
        action="ensure_automation_window",
        url="https://example.com",
    )
    parsed = browser_runtime.json.loads(result)

    assert parsed["success"] is True
    assert parsed["browser"] == "Chrome"
    assert parsed["browser_automation_target"] == {
        "browser": "Chrome",
        "window_index": 1,
        "tab_index": 1,
        "expected_url": "https://example.com",
        "expected_title": "Example",
        "created_by_basil": True,
        "agent_task_id": None,
    }
    assert len(calls) == 2


def test_browser_permission_classifier_detects_javascript_automation_blocker():
    issue = browser_runtime.classify_browser_automation_permission_issue(
        "Executing JavaScript through AppleScript is turned off. "
        "To turn it on, choose Develop > Allow JavaScript from Apple Events.",
        browser="Safari",
    )

    assert issue is not None
    assert issue.permission_kind == "browser_javascript_from_apple_events"
    assert issue.browser == "Safari"
    assert issue.hard_blocker is True
    assert "Allow JavaScript from Apple Events" in issue.user_message


@pytest.mark.parametrize(
    ("browser", "expected_step"),
    [
        ("Safari", "Safari: Develop menu > Allow JavaScript from Apple Events."),
        ("Chrome", "Chrome: View > Developer > Allow JavaScript from Apple Events."),
        ("Edge", "Edge: View > Developer > Allow JavaScript from Apple Events."),
    ],
)
def test_browser_permission_classifier_uses_browser_specific_javascript_steps(
    browser,
    expected_step,
):
    issue = browser_runtime.classify_browser_automation_permission_issue(
        "Executing JavaScript through AppleScript is turned off.",
        browser=browser,
    )

    assert issue is not None
    assert issue.next_actions == [
        expected_step,
        "Retry the browser task after the permission is enabled.",
    ]


def test_browser_permission_issue_returns_json_blocker_without_agent_context():
    result = browser_runtime.handle_browser_permission_issue(
        "Executing JavaScript through AppleScript is turned off.",
        browser="Safari",
        action="inspect",
    )

    assert result is not None
    assert result["permission_blocked"] is True
    assert result["permission_kind"] == "browser_javascript_from_apple_events"
    assert result["action"] == "inspect"


def test_browser_permission_issue_raises_repair_checkpoint_with_agent_context():
    token = set_current_agent_context({"agent_task_id": "agent-123"})
    try:
        with pytest.raises(CheckpointRequest) as exc_info:
            browser_runtime.handle_browser_permission_issue(
                "Executing JavaScript through AppleScript is turned off.",
                browser="Safari",
                action="inspect",
            )
    finally:
        reset_current_agent_context(token)

    checkpoint = exc_info.value.checkpoint_data
    assert checkpoint["input_type"] == "choice"
    assert checkpoint["metadata"]["source"] == "browser_permission_repair"
    assert checkpoint["metadata"]["browser"] == "Safari"
    assert checkpoint["metadata"]["next_actions"] == [
        "Safari: Develop menu > Allow JavaScript from Apple Events.",
        "Retry the browser task after the permission is enabled.",
    ]
    assert [option["value"] for option in checkpoint["options"]] == [
        "browser_permission_retry",
        "browser_permission_use_foreground_once",
        "browser_permission_cancel",
    ]


@pytest.mark.asyncio
async def test_browser_interact_background_session_reports_unavailable_runtime():
    result = await browser_interact_tool._browser_interact_impl(
        action="click",
        selector="#buy-now",
        session_mode="basil_automation_browser",
    )
    parsed = browser_runtime.json.loads(result)

    assert parsed["success"] is False
    assert parsed["session_mode"] == "basil_automation_browser"
    assert parsed["requires_user_input"] is True


@pytest.mark.asyncio
async def test_run_applescript_terminates_subprocess_on_cancellation(monkeypatch):
    process = _HangingProcess()

    async def fake_create_subprocess_exec(*_args, **_kwargs):
        return process

    monkeypatch.setattr(
        browser_runtime.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    task = browser_runtime.asyncio.create_task(browser_runtime.run_applescript("return 1"))
    await browser_runtime.asyncio.sleep(0)
    task.cancel()

    with pytest.raises(browser_runtime.asyncio.CancelledError):
        await task

    assert process.terminated is True
    assert process.killed is False
