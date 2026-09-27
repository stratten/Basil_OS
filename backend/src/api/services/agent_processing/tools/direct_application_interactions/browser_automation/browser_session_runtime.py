"""Session-mode routing primitives for browser automation tools."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


class BrowserSessionMode(str, Enum):
    """Browser runtime mode for automation tools."""

    USER_BROWSER = "user_browser"
    BASIL_AUTOMATION_BROWSER = "basil_automation_browser"


def normalize_browser_session_mode(session_mode: Optional[str]) -> BrowserSessionMode:
    """Return a supported browser session mode, defaulting to the user's browser."""
    if not session_mode:
        return BrowserSessionMode.USER_BROWSER
    try:
        return BrowserSessionMode(session_mode)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in BrowserSessionMode)
        raise ValueError(f"Unsupported browser session_mode: {session_mode}. Use one of: {allowed}.") from exc


def background_browser_not_available_result(
    *,
    action: str,
    browser: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a stable result for the not-yet-enabled background runtime."""
    return {
        "success": False,
        "session_mode": BrowserSessionMode.BASIL_AUTOMATION_BROWSER.value,
        "browser": browser,
        "action": action,
        "requires_user_input": True,
        "error": (
            "Basil Automation Browser is not enabled yet. Use session_mode='user_browser' "
            "for the current browser tools, or enable the future background browser runtime."
        ),
    }


def is_background_browser_session(session_mode: Optional[str]) -> bool:
    """Return whether the requested session mode is the Basil automation browser."""
    return normalize_browser_session_mode(session_mode) == BrowserSessionMode.BASIL_AUTOMATION_BROWSER
