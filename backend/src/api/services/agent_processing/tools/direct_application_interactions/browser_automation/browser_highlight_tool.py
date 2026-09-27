"""Browser highlight tool for visible action previews."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Literal, Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile
from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import CheckpointRequest

from .browser_runtime import (
    build_browser_applescript,
    handle_browser_permission_issue,
    run_applescript,
)
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


class BrowserHighlightInput(BaseModel):
    """Input schema for browser highlight tool."""

    browser: Optional[str] = Field(
        default=None,
        description="Browser to use: 'Safari', 'Chrome', 'Edge', or empty to auto-detect",
    )
    action: Literal["highlight", "clear"] = Field(description="Highlight a selector or clear Basil highlights.")
    selector: Optional[str] = Field(default=None, description="CSS/deep selector to highlight.")
    label: Optional[str] = Field(default=None, description="Short label displayed beside the highlighted target.")
    duration_ms: int = Field(default=2500, ge=250, le=30000, description="How long the highlight should remain.")
    session_mode: Literal["user_browser", "basil_automation_browser"] = Field(
        default="user_browser",
        description="Browser runtime to use. user_browser uses Safari/Chrome/Edge; basil_automation_browser is the future background runtime.",
    )
    window_index: Optional[int] = Field(default=None, description="Optional 1-based browser window index to use.")
    tab_index: Optional[int] = Field(default=None, description="Optional 1-based tab index to use.")
    browser_automation_target: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured target returned by browser_tabs.ensure_automation_window.",
    )


def _build_highlight_js(action: str, selector: Optional[str], label: Optional[str], duration_ms: int) -> str:
    escaped_selector = (selector or "").replace("\\", "\\\\").replace("'", "\\'")
    escaped_label = (label or "Basil target").replace("\\", "\\\\").replace("'", "\\'")
    return f'''
(function() {{
    const action = '{action}';
    const selector = '{escaped_selector}';
    const label = '{escaped_label}';
    const durationMs = {duration_ms};
    const marker = 'data-basil-browser-highlight';

    function clearHighlights() {{
        document.querySelectorAll('[' + marker + ']').forEach(el => el.remove());
    }}

    function queryDeep(deepSelector) {{
        const parts = String(deepSelector).split(/\\s*>>>\\s*/).filter(Boolean);
        let root = document;
        let current = null;
        for (let i = 0; i < parts.length; i++) {{
            current = root.querySelector(parts[i]);
            if (!current) return null;
            if (i === parts.length - 1) return current;
            if (current.shadowRoot) {{
                root = current.shadowRoot;
            }} else if (current.contentDocument) {{
                root = current.contentDocument;
            }} else {{
                return null;
            }}
        }}
        return current;
    }}

    try {{
        clearHighlights();
        if (action === 'clear') {{
            return JSON.stringify({{success: true, action: 'clear', cleared: true}});
        }}

        const target = queryDeep(selector);
        if (!target || typeof target.getBoundingClientRect !== 'function') {{
            return JSON.stringify({{success: false, action: 'highlight', error: 'Element not found: ' + selector}});
        }}

        target.scrollIntoView({{behavior: 'smooth', block: 'center', inline: 'center'}});
        const rect = target.getBoundingClientRect();

        const box = document.createElement('div');
        box.setAttribute(marker, 'box');
        Object.assign(box.style, {{
            position: 'fixed',
            left: Math.max(0, rect.left - 4) + 'px',
            top: Math.max(0, rect.top - 4) + 'px',
            width: Math.max(0, rect.width + 8) + 'px',
            height: Math.max(0, rect.height + 8) + 'px',
            border: '3px solid #0A84FF',
            boxShadow: '0 0 0 4px rgba(10, 132, 255, 0.22)',
            borderRadius: '8px',
            pointerEvents: 'none',
            zIndex: 2147483647
        }});

        const tag = document.createElement('div');
        tag.setAttribute(marker, 'label');
        tag.textContent = label;
        Object.assign(tag.style, {{
            position: 'fixed',
            left: Math.max(0, rect.left - 4) + 'px',
            top: Math.max(0, rect.top - 32) + 'px',
            background: '#0A84FF',
            color: 'white',
            padding: '4px 8px',
            borderRadius: '6px',
            font: '12px -apple-system, BlinkMacSystemFont, sans-serif',
            pointerEvents: 'none',
            zIndex: 2147483647
        }});

        document.body.appendChild(box);
        document.body.appendChild(tag);
        window.setTimeout(clearHighlights, durationMs);
        return JSON.stringify({{
            success: true,
            action: 'highlight',
            selector,
            label,
            durationMs,
            newUrl: window.location.href,
            newTitle: document.title
        }});
    }} catch(e) {{
        return JSON.stringify({{success: false, action, error: 'Highlight failed: ' + e.message}});
    }}
}})();
'''


async def _browser_highlight_impl(
    browser: Optional[str] = None,
    action: str = "highlight",
    selector: Optional[str] = None,
    label: Optional[str] = None,
    duration_ms: int = 2500,
    session_mode: str = "user_browser",
    window_index: Optional[int] = None,
    tab_index: Optional[int] = None,
    browser_automation_target: Optional[Dict[str, Any]] = None,
) -> str:
    try:
        if is_background_browser_session(session_mode):
            return json.dumps(
                background_browser_not_available_result(action=f"highlight.{action}", browser=browser),
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
        if action == "highlight" and not selector:
            return json.dumps({"success": False, "error": "Action 'highlight' requires selector."})

        js_code = _build_highlight_js(action, selector, label, duration_ms)
        success, stdout, stderr = await run_applescript(
            build_browser_applescript(
                browser,
                js_code,
                window_index=window_index,
                tab_index=tab_index,
            )
        )
        if not success:
            permission_result = handle_browser_permission_issue(
                stderr,
                browser=browser,
                action=f"highlight.{action}",
            )
            if permission_result:
                return json.dumps(permission_result, ensure_ascii=False)
            return json.dumps({"success": False, "browser": browser, "error": stderr}, ensure_ascii=False)

        result = json.loads(stdout)
        result["browser"] = browser
        if target is not None:
            result["browser_automation_target"] = target.to_result()
        elif window_index is not None or tab_index is not None:
            result["browser_automation_target"] = {
                "browser": browser,
                "window_index": window_index or 1,
                "tab_index": tab_index or 1,
                "expected_url": result.get("newUrl"),
                "expected_title": result.get("newTitle"),
                "created_by_basil": False,
                "agent_task_id": None,
            }
        trace_entry = record_browser_trace(
            action=f"highlight.{action}",
            browser=browser,
            selector=selector,
            target_text=label,
            success=bool(result.get("success")),
            warning=result.get("error"),
            metadata=result,
        )
        if trace_entry:
            result["browser_trace"] = trace_entry
        logger.info(
            "BROWSER_AUDIT action=highlight.%s browser=%s selector=%s success=%s",
            action,
            browser,
            (selector or "")[:120],
            result.get("success"),
        )
        return json.dumps(result, ensure_ascii=False, indent=2)
    except CheckpointRequest:
        raise
    except Exception as e:
        logger.error("Browser highlight failed: %s", e, exc_info=True)
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


SLIM_DESCRIPTION = (
    "Preview or clear a browser target highlight. Use action=highlight with a selector from "
    "browser_inspect before visible user-impacting actions; pass browser_automation_target when "
    "available; use action=clear to remove Basil overlays."
)

FULL_DESCRIPTION = """Preview a browser automation target by drawing a temporary Basil-owned overlay.

Use this before visible user-impacting actions like click, fill, and select when browser action
highlights are enabled. Supports deep selectors with `>>>` like browser_interact. Use action `clear`
to remove Basil-created overlays.
"""


def create_browser_highlight_tool(profile=None) -> StructuredTool:
    tool_description = select_description_for_profile(profile, FULL_DESCRIPTION, SLIM_DESCRIPTION)
    return StructuredTool.from_function(
        func=_browser_highlight_impl,
        name="browser_highlight",
        description=tool_description,
        args_schema=BrowserHighlightInput,
        coroutine=_browser_highlight_impl,
    )

