"""
Browser Automation Tools

Tools for interacting with web browsers (Safari, Chrome, Edge) via AppleScript.
Enables DOM inspection and element interaction using the user's existing browser session.
"""

from .browser_inspect_tool import create_browser_inspect_tool, _get_default_browser
from .browser_interact_tool import create_browser_interact_tool
from .browser_highlight_tool import create_browser_highlight_tool
from .browser_screenshot_tool import create_browser_screenshot_tool
from .browser_tabs_tool import create_browser_tabs_tool
from .browser_session_runtime import BrowserSessionMode
from .basil_automation_browser_runtime import (
    BasilAutomationBrowserProfile,
    BasilAutomationBrowserRuntime,
    ManualAuthPause,
)

__all__ = [
    'create_browser_highlight_tool',
    'create_browser_inspect_tool',
    'create_browser_interact_tool',
    'create_browser_screenshot_tool',
    'create_browser_tabs_tool',
    'BrowserSessionMode',
    'BasilAutomationBrowserProfile',
    'BasilAutomationBrowserRuntime',
    'ManualAuthPause',
    '_get_default_browser',
]
