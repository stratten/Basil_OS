"""Describe a pinned browser window so the client can capture it without bringing it to the front."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .browser_runtime import run_applescript
from .browser_target_runtime import BrowserAutomationTarget, normalize_browser_name

_OWNER_NAMES = {
    "Safari": "Safari",
    "Chrome": "Google Chrome",
    "Edge": "Microsoft Edge",
}


def window_capture_owner_name(browser: str) -> str:
    """Return the process name macOS uses for the browser's windows."""

    return _OWNER_NAMES[normalize_browser_name(browser)]


def build_window_frame_script(browser: str, window_id: int) -> str:
    """Build a script that reads a window's frame and active-tab title without activating the browser.

    The reply is `ok|x|y|width|height|title` with the title last because it may contain the separator.
    """

    owner = window_capture_owner_name(browser)
    title_expression = "name of current tab of window id {id}" if owner == "Safari" else "title of active tab of window id {id}"
    title_line = title_expression.format(id=int(window_id))
    return f'''
tell application "{owner}"
    if not (exists window id {int(window_id)}) then return "error|window_missing"
    set windowBounds to bounds of window id {int(window_id)}
    set tabTitle to ""
    try
        set tabTitle to {title_line}
    end try
    if tabTitle is missing value then set tabTitle to ""
    set leftEdge to item 1 of windowBounds
    set topEdge to item 2 of windowBounds
    set rightEdge to item 3 of windowBounds
    set bottomEdge to item 4 of windowBounds
    return "ok|" & leftEdge & "|" & topEdge & "|" & (rightEdge - leftEdge) & "|" & (bottomEdge - topEdge) & "|" & tabTitle
end tell
'''


def parse_window_frame_reply(browser: str, reply: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Turn the script reply into a `window_target` payload, or an error message."""

    parts = reply.strip().split("|", 5)
    if parts and parts[0] == "error":
        return None, "The Basil automation window no longer exists. Call browser_tabs with action ensure_automation_window to create it again."
    if len(parts) != 6 or parts[0] != "ok":
        return None, f"Unexpected reply while locating the automation window: {reply[:200]}"
    try:
        x, y, width, height = (float(value) for value in parts[1:5])
    except ValueError:
        return None, f"Could not read the automation window's frame from: {reply[:200]}"
    if width <= 0 or height <= 0:
        return None, "The Basil automation window has no visible area. It may be minimized."
    return (
        {
            "owner_name": window_capture_owner_name(browser),
            "bounds": {"x": x, "y": y, "width": width, "height": height},
            "title": parts[5],
        },
        None,
    )


async def resolve_window_capture_target(
    target: BrowserAutomationTarget,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Return `(window_target, None)` for a pinned window, or `(None, error_message)` when it cannot be described."""

    if target.window_id is None:
        return None, "The browser target has no window id."
    script = build_window_frame_script(target.browser, int(target.window_id))
    success, stdout, stderr = await run_applescript(script, timeout_s=10.0)
    if not success:
        detail = stderr or stdout or "no output"
        return None, f"Could not read the automation window's frame: {detail[:300]}"
    return parse_window_frame_reply(target.browser, stdout)
