"""Coverage for ``GenericAppleScriptService._detect_browser_foreground_control``.

The detector must recognize a script that takes over the screen however it names the browser, and must leave ordinary background browser scripts alone.
"""

from __future__ import annotations

import pytest

from api.services.agent_processing.tools.direct_application_interactions.applescript_automation import (
    generic_applescript_service as svc,
)


@pytest.fixture
def service() -> svc.GenericAppleScriptService:
    return svc.GenericAppleScriptService()


@pytest.mark.parametrize(
    "script",
    [
        'tell application "Google Chrome" to activate',
        'tell application "Safari"\n    activate\nend tell',
        'tell application "System Events" to set frontmost of process "Google Chrome" to true',
        'tell application "System Events"\n    tell process "Google Chrome"\n        click menu item "Reload" of menu 1 of menu bar item "View" of menu bar 1\n    end tell\nend tell',
        'do shell script "open -a \\"Google Chrome\\""',
        'do shell script "open -b com.google.Chrome"',
        'tell application id "com.google.Chrome" to activate',
        'tell application "Google Chrome" to set index of window id 12 to 1',
        'tell application "Google Chrome" to make new window',
        'tell application "Google Chrome" to open location "https://example.com"',
        'tell application "Microsoft Edge" to reopen',
        'tell application "Chrome" to activate',
        'TELL APPLICATION "GOOGLE CHROME" TO ACTIVATE',
    ],
)
def test_detects_foreground_control(service, script):
    assert service._detect_browser_foreground_control(script) is True


@pytest.mark.parametrize(
    "script",
    [
        'tell application "Google Chrome" to return URL of active tab of window 1',
        'tell application "Safari" to return name of current tab of window 1',
        'tell application "Google Chrome" to return title of active tab of window id 12',
        'tell application "Mail" to activate',
        'tell application "System Events" to keystroke "a"',
        'return "hello"',
        '',
    ],
)
def test_leaves_background_and_unrelated_scripts_alone(service, script):
    assert service._detect_browser_foreground_control(script) is False
