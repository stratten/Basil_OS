"""Browser tab management tool for Safari, Chrome, and Edge."""

from __future__ import annotations

import json
import logging
from typing import Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile
from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import CheckpointRequest

from .browser_runtime import handle_browser_permission_issue, run_applescript
from .browser_session_runtime import (
    background_browser_not_available_result,
    is_background_browser_session,
)
from .browser_target_runtime import (
    BrowserAutomationTarget,
    normalize_browser_name,
    resolve_preferred_user_browser,
)
from .browser_trace import record_browser_trace

logger = logging.getLogger(__name__)


class BrowserTabsInput(BaseModel):
    """Input schema for browser tab management."""

    browser: Optional[str] = Field(
        default=None,
        description="Browser to manage: 'Safari', 'Chrome', 'Edge', or empty to auto-detect.",
    )
    action: Literal["list", "create", "switch", "close", "ensure_automation_window"] = Field(
        description="Tab action to perform.",
    )
    url: Optional[str] = Field(
        default=None,
        description="Optional URL for create. If omitted, creates a blank tab where supported.",
    )
    window_index: int = Field(
        default=1,
        description="1-based browser window index for switch/close/create.",
    )
    tab_index: Optional[int] = Field(
        default=None,
        description="1-based tab index for switch/close.",
    )
    session_mode: Literal["user_browser", "basil_automation_browser"] = Field(
        default="user_browser",
        description="Browser runtime to use. user_browser uses Safari/Chrome/Edge; basil_automation_browser is the future background runtime.",
    )


def _escape_applescript_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _browser_app_name(browser: str) -> str:
    normalized = normalize_browser_name(browser)
    if normalized == "Safari":
        return "Safari"
    if normalized == "Chrome":
        return "Google Chrome"
    if normalized == "Edge":
        return "Microsoft Edge"
    raise ValueError(f"Unsupported browser: {browser}. Use 'Safari', 'Chrome', or 'Edge'.")


def _list_tabs_script(browser: str) -> str:
    app_name = _browser_app_name(browser)
    if app_name == "Safari":
        active_expr = "current tab of window w"
        return f'''
tell application "{app_name}"
    if (count of windows) = 0 then return ""
    set outputRows to {{}}
    repeat with w from 1 to count of windows
        set activeTab to {active_expr}
        repeat with t from 1 to count of tabs of window w
            set tabRef to tab t of window w
            set isActive to tabRef is activeTab
            set tabTitle to name of tabRef
            set tabUrl to URL of tabRef
            set AppleScript's text item delimiters to "|"
            set tabTitleParts to every text item of tabTitle
            set tabUrlParts to every text item of tabUrl
            set AppleScript's text item delimiters to "⎮"
            set tabTitle to tabTitleParts as string
            set tabUrl to tabUrlParts as string
            set AppleScript's text item delimiters to ""
            set end of outputRows to (w as text) & "|" & (t as text) & "|" & (isActive as text) & "|" & tabTitle & "|" & tabUrl
        end repeat
    end repeat
    set AppleScript's text item delimiters to linefeed
    set outputText to outputRows as text
    set AppleScript's text item delimiters to ""
    return outputText
end tell
'''

    return f'''
tell application "{app_name}"
    if (count of windows) = 0 then return ""
    set outputRows to {{}}
    repeat with w from 1 to count of windows
        set activeIndex to active tab index of window w
        repeat with t from 1 to count of tabs of window w
            set tabRef to tab t of window w
            set isActive to t is activeIndex
            set tabTitle to title of tabRef
            set tabUrl to URL of tabRef
            set AppleScript's text item delimiters to "|"
            set tabTitleParts to every text item of tabTitle
            set tabUrlParts to every text item of tabUrl
            set AppleScript's text item delimiters to "⎮"
            set tabTitle to tabTitleParts as string
            set tabUrl to tabUrlParts as string
            set AppleScript's text item delimiters to ""
            set end of outputRows to (w as text) & "|" & (t as text) & "|" & (isActive as text) & "|" & tabTitle & "|" & tabUrl
        end repeat
    end repeat
    set AppleScript's text item delimiters to linefeed
    set outputText to outputRows as text
    set AppleScript's text item delimiters to ""
    return outputText
end tell
'''


def _create_tab_script(browser: str, url: Optional[str], window_index: int) -> str:
    app_name = _browser_app_name(browser)
    safe_url = _escape_applescript_string(url or "about:blank")
    if app_name == "Safari":
        return f'''
tell application "{app_name}"
    if (count of windows) = 0 then
        make new document with properties {{URL:"{safe_url}"}}
    else
        tell window {window_index}
            set newTab to make new tab at end of tabs with properties {{URL:"{safe_url}"}}
            set current tab to newTab
        end tell
    end if
    return "created|{window_index}|{safe_url}"
end tell
'''
    return f'''
tell application "{app_name}"
    if (count of windows) = 0 then make new window
    tell window {window_index}
        set newTab to make new tab at end of tabs with properties {{URL:"{safe_url}"}}
        set active tab index to (count of tabs)
    end tell
    return "created|{window_index}|{safe_url}"
end tell
'''


def _create_automation_window_script(browser: str, url: Optional[str]) -> str:
    app_name = _browser_app_name(browser)
    safe_url = _escape_applescript_string(url or "about:blank")
    if app_name == "Safari":
        return f'''
tell application "{app_name}"
    set newDoc to make new document with properties {{URL:"{safe_url}"}}
    return "created_window|1|1|{safe_url}"
end tell
'''
    return f'''
tell application "{app_name}"
    set newWindow to make new window
    set URL of active tab of newWindow to "{safe_url}"
    set active tab index of newWindow to 1
    set index of newWindow to 1
    return "created_window|1|1|{safe_url}"
end tell
'''


def _switch_tab_script(browser: str, window_index: int, tab_index: int) -> str:
    app_name = _browser_app_name(browser)
    if app_name == "Safari":
        return f'''
tell application "{app_name}"
    if (count of windows) < {window_index} then return "error|Window not found"
    if (count of tabs of window {window_index}) < {tab_index} then return "error|Tab not found"
    set current tab of window {window_index} to tab {tab_index} of window {window_index}
    return "switched|{window_index}|{tab_index}"
end tell
'''
    return f'''
tell application "{app_name}"
    if (count of windows) < {window_index} then return "error|Window not found"
    if (count of tabs of window {window_index}) < {tab_index} then return "error|Tab not found"
    set active tab index of window {window_index} to {tab_index}
    return "switched|{window_index}|{tab_index}"
end tell
'''


def _close_tab_script(browser: str, window_index: int, tab_index: int) -> str:
    app_name = _browser_app_name(browser)
    return f'''
tell application "{app_name}"
    if (count of windows) < {window_index} then return "error|Window not found"
    if (count of tabs of window {window_index}) < {tab_index} then return "error|Tab not found"
    if (count of tabs of window {window_index}) <= 1 then return "error|Refusing to close the last tab in a window"
    close tab {tab_index} of window {window_index}
    return "closed|{window_index}|{tab_index}"
end tell
'''


def _parse_tab_rows(output: str) -> list[dict]:
    tabs = []
    for row in output.splitlines():
        parts = row.split("|", 4)
        if len(parts) != 5:
            continue
        window_index, tab_index, active, title, url = parts
        tabs.append({
            "window_index": int(window_index),
            "tab_index": int(tab_index),
            "active": active.lower() == "true",
            "title": title.replace("⎮", "|"),
            "url": url.replace("⎮", "|"),
        })
    return tabs


def _find_automation_target(browser: str, tabs: list[dict], url: Optional[str]) -> BrowserAutomationTarget:
    expected_url = url or "about:blank"
    matching_tabs = [
        tab for tab in tabs
        if str(tab.get("url") or "").rstrip("/") == expected_url.rstrip("/")
    ]
    selected = matching_tabs[0] if matching_tabs else (tabs[0] if tabs else {})
    return BrowserAutomationTarget(
        browser=normalize_browser_name(browser),
        window_index=int(selected.get("window_index") or 1),
        tab_index=int(selected.get("tab_index") or 1),
        expected_url=str(selected.get("url") or expected_url),
        expected_title=str(selected.get("title") or ""),
        created_by_basil=True,
    )


async def _browser_tabs_impl(
    browser: Optional[str] = None,
    action: str = "list",
    url: Optional[str] = None,
    window_index: int = 1,
    tab_index: Optional[int] = None,
    session_mode: str = "user_browser",
) -> str:
    try:
        if is_background_browser_session(session_mode):
            return json.dumps(
                background_browser_not_available_result(action=f"tabs.{action}", browser=browser),
                ensure_ascii=False,
            )

        if browser is None or browser.strip() == "":
            browser = await resolve_preferred_user_browser()
        else:
            browser = normalize_browser_name(browser)

        if action == "list":
            script = _list_tabs_script(browser)
        elif action == "create":
            script = _create_tab_script(browser, url, window_index)
        elif action == "switch":
            if tab_index is None:
                return json.dumps({"success": False, "error": "Action 'switch' requires tab_index."})
            script = _switch_tab_script(browser, window_index, tab_index)
        elif action == "close":
            if tab_index is None:
                return json.dumps({"success": False, "error": "Action 'close' requires tab_index."})
            script = _close_tab_script(browser, window_index, tab_index)
        elif action == "ensure_automation_window":
            script = _create_automation_window_script(browser, url)
        else:
            return json.dumps({"success": False, "error": f"Unsupported action: {action}"})

        ok, stdout, stderr = await run_applescript(script, timeout_s=20.0)
        logger.info(
            "BROWSER_AUDIT action=tabs.%s browser=%s window=%s tab=%s success=%s",
            action,
            browser,
            window_index,
            tab_index,
            ok and not stdout.startswith("error|"),
        )
        if not ok:
            permission_result = handle_browser_permission_issue(
                stderr,
                browser=browser,
                action=f"tabs.{action}",
            )
            if permission_result:
                return json.dumps(permission_result, ensure_ascii=False)
            return json.dumps({
                "success": False,
                "browser": browser,
                "action": action,
                "error": stderr or "AppleScript execution failed.",
            }, ensure_ascii=False)

        if action == "list":
            result = {
                "success": True,
                "browser": browser,
                "action": action,
                "tabs": _parse_tab_rows(stdout),
            }
            trace_entry = record_browser_trace(
                action=f"tabs.{action}",
                browser=browser,
                success=True,
                metadata={"tab_count": len(result["tabs"])},
            )
            if trace_entry:
                result["browser_trace"] = trace_entry
            return json.dumps(result, ensure_ascii=False, indent=2)

        if action == "ensure_automation_window":
            list_ok, list_stdout, list_stderr = await run_applescript(
                _list_tabs_script(browser),
                timeout_s=20.0,
            )
            if not list_ok:
                return json.dumps({
                    "success": False,
                    "browser": browser,
                    "action": action,
                    "error": list_stderr or "Could not verify automation window after creation.",
                }, ensure_ascii=False)

            target = _find_automation_target(browser, _parse_tab_rows(list_stdout), url)
            result = {
                "success": True,
                "browser": browser,
                "action": action,
                "result": stdout,
                "browser_automation_target": target.to_result(),
            }
            trace_entry = record_browser_trace(
                action=f"tabs.{action}",
                browser=browser,
                success=True,
                metadata={"browser_automation_target": target.to_result()},
            )
            if trace_entry:
                result["browser_trace"] = trace_entry
            return json.dumps(result, ensure_ascii=False, indent=2)

        if stdout.startswith("error|"):
            return json.dumps({
                "success": False,
                "browser": browser,
                "action": action,
                "error": stdout.split("|", 1)[1],
            }, ensure_ascii=False)

        result = {
            "success": True,
            "browser": browser,
            "action": action,
            "result": stdout,
        }
        trace_entry = record_browser_trace(
            action=f"tabs.{action}",
            browser=browser,
            success=True,
            metadata={"window_index": window_index, "tab_index": tab_index},
        )
        if trace_entry:
            result["browser_trace"] = trace_entry
        return json.dumps(result, ensure_ascii=False, indent=2)

    except ValueError as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)
    except CheckpointRequest:
        raise
    except Exception as e:
        logger.error(f"❌ Browser tabs failed: {e}", exc_info=True)
        return json.dumps({"success": False, "error": f"Browser tabs failed: {str(e)}"}, ensure_ascii=False)


SLIM_DESCRIPTION = (
    "Manage browser tabs in the user's existing Safari/Chrome/Edge session. "
    "Actions: list, ensure_automation_window (preferred for new browser tasks; returns "
    "browser_automation_target), create (optional url), switch (window_index + tab_index), "
    "close (requires tab_index; refuses to close the last tab). Leave browser "
    "empty to auto-detect. If multiple tabs plausibly match the task, ask the "
    "user to pick with request_user_input selection options before switching."
)

_FULL_DESCRIPTION = """List, create, switch, or conservatively close tabs in the user's browser.

Use this for browser UI state, not page content. For new browser tasks, prefer
action="ensure_automation_window" so Basil works in a dedicated browser window and returns
browser_automation_target for browser_inspect/browser_interact/browser_highlight. For page
content use browser_inspect and browser_interact. The close action refuses to close the final
tab in a window.

If more than one plausible tab matches the user's target, call request_user_input with
selection options built from the listed tabs before switching or interacting.
"""


def create_browser_tabs_tool(profile=None) -> StructuredTool:
    tool_description = select_description_for_profile(
        profile, _FULL_DESCRIPTION, SLIM_DESCRIPTION
    )
    return StructuredTool.from_function(
        func=_browser_tabs_impl,
        name="browser_tabs",
        description=tool_description,
        args_schema=BrowserTabsInput,
        coroutine=_browser_tabs_impl,
    )
