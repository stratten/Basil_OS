"""Browser screenshot tool backed by Basil's Swift window capture bridge."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile
from api.services.capture.shared.window_capture_bridge import request_swift_window_capture

from .browser_session_runtime import (
    background_browser_not_available_result,
    is_background_browser_session,
)
from .browser_trace import record_browser_trace
from .browser_target_runtime import (
    resolve_browser_target_inputs,
    resolve_preferred_user_browser,
)
from .browser_window_capture_target import resolve_window_capture_target

logger = logging.getLogger(__name__)


class BrowserScreenshotInput(BaseModel):
    """Input schema for browser screenshot capture."""

    browser: Optional[str] = Field(
        default=None,
        description=(
            "Optional expected browser name ('Safari', 'Chrome', 'Edge'). "
            "The active window is captured; this is used only to warn if the active app differs."
        ),
    )
    session_mode: Literal["user_browser", "basil_automation_browser"] = Field(
        default="user_browser",
        description="Browser runtime to use. user_browser captures the active browser window; basil_automation_browser is the future background runtime.",
    )
    window_index: Optional[int] = Field(default=None, description="Optional expected 1-based browser window index.")
    tab_index: Optional[int] = Field(default=None, description="Optional expected 1-based tab index.")
    browser_automation_target: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured target returned by browser_tabs.ensure_automation_window. When it names a Basil automation window, that exact window is captured in the background without bringing the browser forward. Without one, the active window is captured.",
    )


def _browser_matches_expected(app_name: str, expected_browser: Optional[str]) -> bool:
    if not expected_browser:
        return True
    app = app_name.lower()
    expected = expected_browser.lower()
    if expected == "chrome":
        expected = "google chrome"
    if expected == "edge":
        expected = "microsoft edge"
    return expected in app or app in expected


async def _browser_screenshot_impl(
    browser: Optional[str] = None,
    session_mode: str = "user_browser",
    window_index: Optional[int] = None,
    tab_index: Optional[int] = None,
    browser_automation_target: Optional[Dict[str, Any]] = None,
) -> str:
    try:
        if is_background_browser_session(session_mode):
            return json.dumps(
                background_browser_not_available_result(action="screenshot", browser=browser),
                ensure_ascii=False,
            )

        browser, window_index, tab_index, target = resolve_browser_target_inputs(
            browser=browser,
            window_index=window_index,
            tab_index=tab_index,
            browser_automation_target=browser_automation_target,
        )
        if browser is None or browser.strip() == "":
            browser = await resolve_preferred_user_browser()

        window_target = None
        if target is not None and target.window_id is not None:
            # A pinned Basil window is captured by its own window id, so the browser is never activated and the frontmost app is irrelevant.
            window_target, window_error = await resolve_window_capture_target(target)
            if window_target is None:
                return json.dumps({
                    "success": False,
                    "error": window_error,
                    "browser_automation_target": target.to_result(),
                }, ensure_ascii=False)

        capture = await request_swift_window_capture("browser_screenshot", window_target=window_target)
        logger.info(
            "BROWSER_AUDIT action=screenshot expected_browser=%s success=%s app=%s",
            browser,
            capture.get("success"),
            capture.get("app_name"),
        )
        if not capture.get("success") or not capture.get("image_path"):
            return json.dumps({
                "success": False,
                "error": capture.get("error") or capture.get("message") or "Browser screenshot capture failed.",
                "capture_method": capture.get("capture_method"),
            }, ensure_ascii=False)

        app_name = capture.get("app_name", "Unknown")
        browser_match = _browser_matches_expected(app_name, browser)
        result = {
            "success": True,
            "image_path": capture["image_path"],
            "app_name": app_name,
            "window_title": capture.get("window_title", "Unknown"),
            "capture_method": capture.get("capture_method", "swift_window_service"),
            "browser_match": browser_match,
        }
        if target is not None:
            result["browser_automation_target"] = target.to_result()
            if window_target is not None:
                result["capture_scope"] = "automation_window"
            else:
                result["warning"] = (
                    "Screenshot capture uses the active browser window; verify it matches "
                    "browser_automation_target before relying on visual analysis."
                )
        elif window_index is not None or tab_index is not None:
            result["browser_automation_target"] = {
                "browser": browser,
                "window_index": window_index or 1,
                "tab_index": tab_index or 1,
                "expected_url": None,
                "expected_title": capture.get("window_title"),
                "created_by_basil": False,
                "agent_task_id": None,
            }
        if browser and not browser_match:
            result["warning"] = f"Captured active app '{app_name}', not requested browser '{browser}'."
        trace_entry = record_browser_trace(
            action="screenshot",
            browser=browser or app_name,
            target_text=capture.get("window_title"),
            success=True,
            warning=result.get("warning"),
            metadata={
                "app_name": app_name,
                "capture_method": result.get("capture_method"),
                "browser_match": browser_match,
            },
        )
        if trace_entry:
            result["browser_trace"] = trace_entry
        return json.dumps(result, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error(f"❌ Browser screenshot failed: {e}", exc_info=True)
        return json.dumps({"success": False, "error": f"Browser screenshot failed: {str(e)}"}, ensure_ascii=False)


SLIM_DESCRIPTION = (
    "Capture the Basil automation window (pass browser_automation_target) as an image "
    "without bringing the browser forward, or the active browser window when no target "
    "is given. Returns image_path for analyze_with_vision. Never activate or raise the "
    "browser to take a screenshot."
)

_FULL_DESCRIPTION = """Capture a browser window and return a local image path.

Use this when DOM inspection cannot see the target or when visual context is required.
Pass the returned image_path to analyze_with_vision for visual reasoning. When you pass the
browser_automation_target returned by browser_tabs ensure_automation_window, Basil captures
that exact window in the background, even if another app is frontmost or the window is covered.
Do not run AppleScript to activate, raise, or focus the browser before capturing: that is not
needed and takes over the user's screen. Without a target, the active window is captured.
Basil needs Screen Recording permission enabled.
"""


def create_browser_screenshot_tool(profile=None) -> StructuredTool:
    tool_description = select_description_for_profile(
        profile, _FULL_DESCRIPTION, SLIM_DESCRIPTION
    )
    return StructuredTool.from_function(
        func=_browser_screenshot_impl,
        name="browser_screenshot",
        description=tool_description,
        args_schema=BrowserScreenshotInput,
        coroutine=_browser_screenshot_impl,
    )
