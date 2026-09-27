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
        description="Structured target returned by browser_tabs.ensure_automation_window. Screenshot capture still uses the active window.",
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

        capture = await request_swift_window_capture("browser_screenshot")
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
    "Capture the active browser window as an image using Basil's Swift window "
    "capture bridge. Returns image_path for analyze_with_vision. Optional "
    "browser only checks whether the active captured app matches."
)

_FULL_DESCRIPTION = """Capture the active browser window and return a local image path.

Use this when DOM inspection cannot see the target or when visual context is required.
Pass the returned image_path to analyze_with_vision for visual reasoning. This captures
the active window through Basil's existing Swift capture bridge, so the user may need
Screen Recording permission enabled.
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
