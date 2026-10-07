"""Shared runtime helpers for browser automation tools."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Optional

from .browser_pinned_target import pinned_browser_target

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrowserAutomationPermissionIssue:
    """Structured browser automation permission blocker."""

    permission_kind: str
    browser: Optional[str]
    user_message: str
    next_actions: list[str]
    hard_blocker: bool = True

    def to_result(self, *, action: Optional[str] = None, error: Optional[str] = None) -> dict:
        result = {
            "success": False,
            "requires_user_input": True,
            "permission_blocked": True,
            "permission_kind": self.permission_kind,
            "browser": self.browser,
            "error": self.user_message,
            "user_message": self.user_message,
            "next_actions": self.next_actions,
            "hard_blocker": self.hard_blocker,
        }
        if action:
            result["action"] = action
        if error:
            result["raw_error"] = error
        return result


def browser_javascript_permission_next_actions(browser: Optional[str]) -> list[str]:
    """Return current per-browser steps for enabling Apple Events JavaScript."""
    browser_name = (browser or "").strip().lower()
    if browser_name in {"safari"}:
        menu_path = "Safari: Develop menu > Allow JavaScript from Apple Events."
    elif browser_name in {"chrome", "google chrome"}:
        menu_path = "Chrome: View > Developer > Allow JavaScript from Apple Events."
    elif browser_name in {"edge", "microsoft edge"}:
        menu_path = "Edge: View > Developer > Allow JavaScript from Apple Events."
    else:
        menu_path = "Open the browser's developer menu and enable Allow JavaScript from Apple Events."

    return [
        menu_path,
        "Retry the browser task after the permission is enabled.",
    ]


def classify_browser_automation_permission_issue(
    error_text: str,
    *,
    browser: Optional[str] = None,
) -> Optional[BrowserAutomationPermissionIssue]:
    """Classify known browser automation permission failures."""
    normalized = (error_text or "").lower()
    if not normalized:
        return None

    browser_name = browser or _browser_name_from_error_text(error_text)
    if (
        "javascript from apple events" in normalized
        or "executing javascript through applescript is turned off" in normalized
        or "must enable 'allow javascript from apple events'" in normalized
    ):
        return BrowserAutomationPermissionIssue(
            permission_kind="browser_javascript_from_apple_events",
            browser=browser_name,
            user_message=(
                f"{browser_name or 'The browser'} is blocking JavaScript automation. "
                "Enable 'Allow JavaScript from Apple Events' for that browser, then retry. "
                "Basil should not fall back to foreground keyboard or mouse automation until you approve that."
            ),
            next_actions=browser_javascript_permission_next_actions(browser_name),
        )

    if "access not allowed" in normalized or "-10003" in normalized:
        return BrowserAutomationPermissionIssue(
            permission_kind="macos_automation",
            browser=browser_name,
            user_message=(
                "macOS denied browser automation. Enable Automation permission for Basil "
                "in System Settings > Privacy & Security > Automation, then retry."
            ),
            next_actions=[
                "Open System Settings > Privacy & Security > Automation.",
                "Allow Basil to control the target browser.",
                "Retry the browser task after permission is granted.",
            ],
        )

    return None


def browser_permission_issue_result(
    error_text: str,
    *,
    browser: Optional[str] = None,
    action: Optional[str] = None,
) -> Optional[dict]:
    """Return a JSON-ready permission blocker result if the error is recognized."""
    issue = classify_browser_automation_permission_issue(error_text, browser=browser)
    if issue is None:
        return None
    return issue.to_result(action=action, error=error_text)


def handle_browser_permission_issue(
    error_text: str,
    *,
    browser: Optional[str] = None,
    action: Optional[str] = None,
) -> Optional[dict]:
    """Raise an in-task repair checkpoint or return a structured blocker."""
    issue = classify_browser_automation_permission_issue(error_text, browser=browser)
    if issue is None:
        return None

    result = issue.to_result(action=action, error=error_text)
    if _should_raise_browser_permission_checkpoint():
        _raise_browser_permission_checkpoint(issue, action=action, error_text=error_text)
    return result


def _should_raise_browser_permission_checkpoint() -> bool:
    try:
        from api.services.agent_processing.shared.agent_runtime_context import (
            get_current_agent_context,
        )

        context = get_current_agent_context()
        return bool(context.get("agent_task_id"))
    except Exception:
        return False


def _raise_browser_permission_checkpoint(
    issue: BrowserAutomationPermissionIssue,
    *,
    action: Optional[str],
    error_text: str,
) -> None:
    from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import (
        CheckpointRequest,
    )

    browser_label = issue.browser or "the browser"
    option_values = {
        "retry": "browser_permission_retry",
        "foreground": "browser_permission_use_foreground_once",
        "cancel": "browser_permission_cancel",
    }
    raise CheckpointRequest({
        "prompt": (
            f"{browser_label} needs browser automation setup before Basil can continue.\n\n"
            f"{issue.user_message}\n\n"
            "Choose **I've enabled it, retry** after updating the permission. Choose "
            "**Use foreground control this time** only if you want Basil to request approval "
            "before controlling the visible desktop."
        ),
        "input_type": "choice",
        "options": [
            {
                "id": "retry",
                "label": "I've enabled it, retry",
                "value": option_values["retry"],
                "description": "Retry the DOM browser action after you update permissions.",
                "variant": "primary",
            },
            {
                "id": "foreground",
                "label": "Use foreground control this time",
                "value": option_values["foreground"],
                "description": "Ask before using visible browser keyboard or mouse control.",
                "variant": "warning",
            },
            {
                "id": "cancel",
                "label": "Cancel browser task",
                "value": option_values["cancel"],
                "description": "Stop this browser automation attempt.",
                "variant": "danger",
            },
        ],
        "context_summary": issue.user_message,
        "metadata": {
            "source": "browser_permission_repair",
            "permission_kind": issue.permission_kind,
            "browser": issue.browser,
            "action": action,
            "next_actions": issue.next_actions,
            "allow_foreground_option": True,
            "raw_error": error_text,
        },
    })


def _browser_name_from_error_text(error_text: str) -> Optional[str]:
    text = error_text or ""
    for browser_name in ("Microsoft Edge", "Google Chrome", "Safari"):
        if browser_name in text:
            return browser_name
    return None


async def _terminate_process_for_cancellation(process: asyncio.subprocess.Process) -> None:
    """Terminate a child process when its parent agent task is canceled."""
    if process.returncode is not None:
        return
    try:
        process.terminate()
        await asyncio.wait_for(process.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
    except ProcessLookupError:
        return


async def get_default_browser() -> str:
    """Return the user's default AppleScript-controllable browser."""
    try:
        plist_path = os.path.expanduser(
            "~/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist"
        )
        process = await asyncio.create_subprocess_exec(
            "defaults",
            "read",
            plist_path,
            "LSHandlers",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5.0)
        except asyncio.CancelledError:
            await _terminate_process_for_cancellation(process)
            raise
        output = stdout.decode("utf-8").lower()

        if "com.google.chrome" in output:
            logger.info("🌐 Detected default browser: Chrome")
            return "Chrome"
        if "com.microsoft.edgemac" in output:
            logger.info("🌐 Detected default browser: Edge")
            return "Edge"
        if "com.apple.safari" in output:
            logger.info("🌐 Detected default browser: Safari")
            return "Safari"
        if "org.mozilla.firefox" in output:
            logger.info("🌐 Detected default browser: Firefox (using Safari for better automation support)")
            return "Safari"

        logger.info("🌐 Could not detect default browser, using Safari")
        return "Safari"

    except asyncio.TimeoutError:
        logger.warning("⚠️ Timeout detecting default browser, using Safari")
        return "Safari"
    except Exception as e:
        logger.warning(f"⚠️ Could not detect default browser ({e}), using Safari")
        return "Safari"


_CLOSED_PINNED_WINDOW_ERROR = (
    "Basil's browser window for this task was closed. Call browser_tabs with "
    "action=\"ensure_automation_window\" to open a new one, then continue there."
)


def _applescript_string_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _pinned_window_id(browser: str, window_index: Optional[int], tab_index: Optional[int]) -> Optional[int]:
    pinned = pinned_browser_target(browser)
    if pinned is None or pinned.window_id is None:
        return None
    if window_index is not None and int(window_index) != pinned.window_index:
        return None
    if tab_index is not None and int(tab_index) != pinned.tab_index:
        return None
    return pinned.window_id


def _window_id_applescript(browser: str, escaped_js: str, window_id: int) -> str:
    closed_result = _applescript_string_literal(json.dumps({
        "success": False,
        "browser_window_closed": True,
        "error": _CLOSED_PINNED_WINDOW_ERROR,
    }))
    normalized = browser.lower()
    if normalized == "safari":
        app_name = "Safari"
        run_line = f'set pageData to do JavaScript "{escaped_js}" in current tab of window id {window_id}'
    elif normalized in {"chrome", "google chrome"}:
        app_name = "Google Chrome"
        run_line = f'set pageData to execute active tab of window id {window_id} javascript "{escaped_js}"'
    elif normalized in {"edge", "microsoft edge"}:
        app_name = "Microsoft Edge"
        run_line = f'set pageData to execute active tab of window id {window_id} javascript "{escaped_js}"'
    else:
        raise ValueError(f"Unsupported browser: {browser}. Use 'Safari', 'Chrome', or 'Edge'.")
    return f'''
tell application "{app_name}"
    if not (exists window id {window_id}) then
        return "{closed_result}"
    end if
    {run_line}
    return pageData
end tell
'''


def build_browser_applescript(
    browser: str,
    js_code: str,
    *,
    window_index: Optional[int] = None,
    tab_index: Optional[int] = None,
    window_id: Optional[int] = None,
) -> str:
    """Build AppleScript to execute JavaScript in the specified browser, preferring the task's pinned window."""
    escaped_js = js_code.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    target_window_id = window_id if window_id is not None else _pinned_window_id(browser, window_index, tab_index)
    if target_window_id is not None:
        return _window_id_applescript(browser, escaped_js, int(target_window_id))
    window_ref = int(window_index or 1)
    tab_ref = int(tab_index or 1)
    target_supplied = window_index is not None or tab_index is not None

    if browser.lower() == "safari":
        tab_check = (
            f"if (count of tabs of window {window_ref}) < {tab_ref} then"
            if target_supplied
            else "if (count of tabs of window 1) = 0 then"
        )
        js_target = (
            f'tab {tab_ref} of window {window_ref}'
            if target_supplied
            else "current tab of window 1"
        )
        return f'''
tell application "Safari"
    if (count of windows) < {window_ref} then
        return "{{\\"success\\": false, \\"error\\": \\"No Safari windows open. Please open Safari with a web page first.\\"}}"
    end if
    {tab_check}
        return "{{\\"success\\": false, \\"error\\": \\"No tabs open in Safari.\\"}}"
    end if
    set pageData to do JavaScript "{escaped_js}" in {js_target}
    return pageData
end tell
'''
    if browser.lower() == "chrome" or browser.lower() == "google chrome":
        tab_check = (
            f"if (count of tabs of window {window_ref}) < {tab_ref} then"
            if target_supplied
            else "if (count of tabs of window 1) = 0 then"
        )
        js_target = (
            f"tab {tab_ref} of window {window_ref}"
            if target_supplied
            else "active tab of window 1"
        )
        return f'''
tell application "Google Chrome"
    if (count of windows) < {window_ref} then
        return "{{\\"success\\": false, \\"error\\": \\"No Chrome windows open. Please open Chrome with a web page first.\\"}}"
    end if
    {tab_check}
        return "{{\\"success\\": false, \\"error\\": \\"No tabs open in Chrome.\\"}}"
    end if
    set pageData to execute {js_target} javascript "{escaped_js}"
    return pageData
end tell
'''
    if browser.lower() == "edge" or browser.lower() == "microsoft edge":
        tab_check = (
            f"if (count of tabs of window {window_ref}) < {tab_ref} then"
            if target_supplied
            else "if (count of tabs of window 1) = 0 then"
        )
        js_target = (
            f"tab {tab_ref} of window {window_ref}"
            if target_supplied
            else "active tab of window 1"
        )
        return f'''
tell application "Microsoft Edge"
    if (count of windows) < {window_ref} then
        return "{{\\"success\\": false, \\"error\\": \\"No Edge windows open. Please open Microsoft Edge with a web page first.\\"}}"
    end if
    {tab_check}
        return "{{\\"success\\": false, \\"error\\": \\"No tabs open in Edge.\\"}}"
    end if
    set pageData to execute {js_target} javascript "{escaped_js}"
    return pageData
end tell
'''
    raise ValueError(f"Unsupported browser: {browser}. Use 'Safari', 'Chrome', or 'Edge'.")


async def run_applescript(applescript: str, timeout_s: float = 30.0) -> tuple[bool, str, str]:
    """Execute AppleScript from a temporary file and return success/stdout/stderr."""
    temp_file_path = ""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".scpt", delete=False) as temp_file:
        temp_file.write(applescript)
        temp_file_path = temp_file.name

    try:
        process = await asyncio.create_subprocess_exec(
            "osascript",
            temp_file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return False, "", f"AppleScript timed out after {timeout_s}s"
        except asyncio.CancelledError:
            await _terminate_process_for_cancellation(process)
            raise

        return (
            process.returncode == 0,
            stdout.decode("utf-8").strip(),
            stderr.decode("utf-8").strip(),
        )
    finally:
        if temp_file_path:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temp_file_path)


def dumps_permission_or_error(
    *,
    browser: Optional[str],
    error_text: str,
    action: Optional[str] = None,
    fallback_prefix: str = "AppleScript error",
) -> str:
    """Serialize a structured permission blocker or generic AppleScript error."""
    permission_result = browser_permission_issue_result(error_text, browser=browser, action=action)
    if permission_result:
        return json.dumps(permission_result, ensure_ascii=False)
    return json.dumps({
        "success": False,
        "browser": browser,
        "action": action,
        "error": f"{fallback_prefix}: {error_text}",
    }, ensure_ascii=False)
