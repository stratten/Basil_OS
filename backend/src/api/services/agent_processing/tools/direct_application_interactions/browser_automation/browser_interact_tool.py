"""
Browser Interact Tool for Agent

Provides the agent with the ability to interact with web page elements in the user's
existing browser (Safari, Chrome, or Edge). Supports clicking, filling forms, selecting options,
navigating, and scrolling. Uses the user's logged-in session.
"""

import asyncio
import json
import logging
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

from api.core.models.reasoning.model_runtime_profile import select_description_for_profile
from api.services.agent_processing.tools.internal_basil_tools.checkpoint_tool import CheckpointRequest

from .browser_interact_descriptions import FULL_DESCRIPTION, SLIM_DESCRIPTION
from .browser_runtime import (
    build_browser_applescript,
    handle_browser_permission_issue,
    run_applescript,
)
from .browser_safety import is_sensitive_field_metadata
from .browser_session_runtime import (
    background_browser_not_available_result,
    is_background_browser_session,
)
from .browser_sensitive_approval import (
    BrowserSensitiveFillRequest,
    get_browser_sensitive_approval_manager,
)
from .browser_sensitive_value_store import get_browser_sensitive_value_store
from .browser_trace import record_browser_trace
from .browser_target_runtime import (
    resolve_browser_target_inputs,
    resolve_preferred_user_browser,
)

logger = logging.getLogger(__name__)

_get_default_browser = resolve_preferred_user_browser


class BrowserInteractInput(BaseModel):
    """Input schema for browser interact tool."""
    browser: Optional[str] = Field(
        default=None,
        description="Browser to interact with: 'Safari', 'Chrome', 'Edge', or leave empty to auto-detect the user's default browser"
    )
    action: Optional[Literal["click", "fill", "select", "navigate", "scroll", "wait"]] = Field(
        default=None,
        description="Required browser action to perform."
    )
    selector: Optional[str] = Field(
        default=None,
        description=(
            "CSS selector from browser_inspect (e.g., '#button-id', '.class-name'), "
            "URL for navigate, or empty for wait to wait for page readiness."
        )
    )
    value: Optional[str] = Field(
        default=None,
        description="Value for 'fill' or 'select' actions"
    )
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


def _build_action_js(
    action: str,
    selector: str,
    value: Optional[str],
    allow_sensitive_fill: bool = False,
    redact_value: bool = False,
) -> str:
    """Build JavaScript code for the specified action."""
    selector = selector or ""

    if action == "wait" and not selector.strip():
        return '''
(function() {
    function currentState() {
        return {
            ready: document.readyState,
            url: window.location.href,
            title: document.title
        };
    }
    return JSON.stringify(Object.assign({
        success: document.readyState === 'complete' || document.readyState === 'interactive',
        action: 'wait',
        wait_type: 'page_ready',
        attempts: 1,
        settle_ms: 500,
        error: (
            document.readyState === 'complete' || document.readyState === 'interactive'
                ? null
                : 'Page is not ready: ' + document.readyState
        )
    }, currentState()));
})();
'''

    # Escape values for JavaScript
    escaped_selector = selector.replace('\\', '\\\\').replace("'", "\\'")
    escaped_value = (value or '').replace('\\', '\\\\').replace("'", "\\'") if value else ''
    common_helpers = f'''
const selector = '{escaped_selector}';
const value = '{escaped_value}';
const allowSensitiveFill = {str(allow_sensitive_fill).lower()};
const redactValue = {str(redact_value).lower()};

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

function isVisible(el) {{
    if (!el || typeof el.getBoundingClientRect !== 'function') return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none'
        && style.visibility !== 'hidden'
        && style.opacity !== '0'
        && rect.width > 0
        && rect.height > 0;
}}

function elementInfo(el) {{
    return {{
        found: Boolean(el),
        visible: Boolean(el && isVisible(el)),
        disabled: Boolean(el && (el.disabled || el.getAttribute('aria-disabled') === 'true')),
        tag: el && el.tagName ? el.tagName.toLowerCase() : null,
        type: el && el.type ? el.type : null,
        newUrl: window.location.href,
        newTitle: document.title
    }};
}}

function isCredentialLike(el, selectorText) {{
    if (!el) return false;
    const attrs = [
        selectorText,
        el.type,
        el.name,
        el.id,
        el.getAttribute('autocomplete'),
        el.getAttribute('aria-label'),
        el.getAttribute('placeholder')
    ].filter(Boolean).join(' ').toLowerCase();
    return /password|passcode|token|secret|credential|one-time|otp|2fa|mfa/.test(attrs);
}}

function dispatchClick(el) {{
    el.scrollIntoView({{behavior: 'instant', block: 'center', inline: 'center'}});
    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {{
        el.dispatchEvent(new MouseEvent(type, {{bubbles: true, cancelable: true, view: window}}));
    }}
}}
'''
    
    if action == "navigate":
        # For navigate, selector is the URL
        return f'''
(function() {{
    try {{
        window.location.href = '{escaped_selector}';
        return JSON.stringify({{
            success: true,
            action: 'navigate',
            navigatingTo: '{escaped_selector}'
        }});
    }} catch(e) {{
        return JSON.stringify({{success: false, error: 'Navigation failed: ' + e.message}});
    }}
}})();
'''
    
    elif action == "click":
        return f'''
(function() {{
    {common_helpers}
    try {{
        const el = queryDeep(selector);
        if (!el) {{
            return JSON.stringify(Object.assign({{
                success: false,
                error: 'Element not found: {escaped_selector}'
            }}, elementInfo(el)));
        }}
        dispatchClick(el);
        return JSON.stringify(Object.assign({{
            success: true,
            action: 'click',
            selector: selector
        }}, elementInfo(el)));
    }} catch(e) {{
        return JSON.stringify({{success: false, error: 'Click failed: ' + e.message}});
    }}
}})();
'''
    
    elif action == "fill":
        return f'''
(function() {{
    {common_helpers}
    try {{
        const el = queryDeep(selector);
        if (!el) {{
            return JSON.stringify(Object.assign({{
                success: false,
                error: 'Element not found: {escaped_selector}'
            }}, elementInfo(el)));
        }}
        if (isCredentialLike(el, selector) && !allowSensitiveFill) {{
            return JSON.stringify(Object.assign({{
                success: false,
                requires_user_input: true,
                error: 'Refusing to fill credential-like field. Ask the user to complete authentication manually.'
            }}, elementInfo(el)));
        }}
        el.focus();
        el.value = value;
        el.dispatchEvent(new Event('input', {{bubbles: true}}));
        el.dispatchEvent(new Event('change', {{bubbles: true}}));
        return JSON.stringify(Object.assign({{
            success: true,
            action: 'fill',
            selector: selector,
            valueFilled: redactValue ? '[redacted]' : value.slice(0, 50),
            valueRedacted: redactValue
        }}, elementInfo(el)));
    }} catch(e) {{
        return JSON.stringify({{success: false, error: 'Fill failed: ' + e.message}});
    }}
}})();
'''
    
    elif action == "select":
        return f'''
(function() {{
    {common_helpers}
    try {{
        const el = queryDeep(selector);
        if (!el) {{
            return JSON.stringify(Object.assign({{
                success: false,
                error: 'Element not found: {escaped_selector}'
            }}, elementInfo(el)));
        }}
        el.value = value;
        el.dispatchEvent(new Event('change', {{bubbles: true}}));
        return JSON.stringify(Object.assign({{
            success: true,
            action: 'select',
            selector: selector,
            valueSelected: value
        }}, elementInfo(el)));
    }} catch(e) {{
        return JSON.stringify({{success: false, error: 'Select failed: ' + e.message}});
    }}
}})();
'''
    
    elif action == "scroll":
        return f'''
(function() {{
    {common_helpers}
    try {{
        const el = queryDeep(selector);
        if (!el) {{
            return JSON.stringify(Object.assign({{
                success: false,
                error: 'Element not found: {escaped_selector}'
            }}, elementInfo(el)));
        }}
        el.scrollIntoView({{behavior: 'smooth', block: 'center'}});
        return JSON.stringify(Object.assign({{
            success: true,
            action: 'scroll',
            selector: selector
        }}, elementInfo(el)));
    }} catch(e) {{
        return JSON.stringify({{success: false, error: 'Scroll failed: ' + e.message}});
    }}
}})();
'''
    
    elif action == "wait":
        return f'''
(async function() {{
    {common_helpers}
    const maxAttempts = 10;
    const interval = 500;
    for (let attempts = 1; attempts <= maxAttempts; attempts++) {{
        const el = queryDeep(selector);
        if (el && isVisible(el)) {{
            return JSON.stringify(Object.assign({{
                success: true,
                action: 'wait',
                selector: selector,
                found: true,
                attempts: attempts
            }}, elementInfo(el)));
        }}
        await new Promise(resolve => setTimeout(resolve, interval));
    }}
    return JSON.stringify(Object.assign({{
        success: false,
        found: false,
        attempts: maxAttempts,
        error: 'Element not found after ' + (maxAttempts * interval / 1000) + 's: {escaped_selector}'
    }}, elementInfo(null)));
}})();
'''
    
    else:
        return f'''
(function() {{
    return JSON.stringify({{
        success: false,
        error: "Unknown action: {action}. Use 'click', 'fill', 'select', 'navigate', 'scroll', or 'wait'."
    }});
}})();
'''


_build_applescript = build_browser_applescript


def _build_element_metadata_js(selector: str) -> str:
    """Build JavaScript that inspects an element without injecting a value."""
    escaped_selector = selector.replace('\\', '\\\\').replace("'", "\\'")
    return f'''
(function() {{
    const selector = '{escaped_selector}';
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
    function isCredentialLike(el, selectorText) {{
        if (!el) return false;
        const attrs = [
            selectorText,
            el.type,
            el.name,
            el.id,
            el.getAttribute('autocomplete'),
            el.getAttribute('aria-label'),
            el.getAttribute('placeholder')
        ].filter(Boolean).join(' ').toLowerCase();
        return /password|passcode|token|secret|credential|one-time|otp|2fa|mfa/.test(attrs);
    }}
    try {{
        const el = queryDeep(selector);
        return JSON.stringify({{
            success: Boolean(el),
            found: Boolean(el),
            url: window.location.href,
            title: document.title,
            selector: selector,
            tag: el && el.tagName ? el.tagName.toLowerCase() : null,
            type: el && el.type ? el.type : null,
            name: el && el.name ? el.name : null,
            id: el && el.id ? el.id : null,
            autocomplete: el ? el.getAttribute('autocomplete') : null,
            ariaLabel: el ? el.getAttribute('aria-label') : null,
            placeholder: el ? el.getAttribute('placeholder') : null,
            credentialLike: Boolean(el && isCredentialLike(el, selector))
        }});
    }} catch(e) {{
        return JSON.stringify({{success: false, found: false, error: 'Metadata inspect failed: ' + e.message}});
    }}
}})();
'''


async def _run_browser_js(
    browser: str,
    js_code: str,
    timeout: float = 30.0,
    *,
    window_index: Optional[int] = None,
    tab_index: Optional[int] = None,
) -> dict:
    """Execute browser JavaScript and parse its JSON result."""
    applescript = _build_applescript(
        browser,
        js_code,
        window_index=window_index,
        tab_index=tab_index,
    )
    success, stdout, stderr = await run_applescript(applescript, timeout_s=timeout)
    if not success:
        permission_result = handle_browser_permission_issue(stderr, browser=browser)
        if permission_result:
            return permission_result
        return {"success": False, "error": f"AppleScript error: {stderr}"}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        logger.warning(f"Could not parse browser output as JSON: {stdout[:200]}")
        return {"success": False, "error": f"Invalid response from browser: {stdout[:200]}"}


async def _browser_interact_impl(
    browser: Optional[str] = None,
    action: Optional[str] = None,
    selector: str = "",
    value: Optional[str] = None,
    session_mode: str = "user_browser",
    window_index: Optional[int] = None,
    tab_index: Optional[int] = None,
    browser_automation_target: Optional[Dict[str, Any]] = None,
) -> str:
    """Implementation of browser interact tool.
    
    Executes an action on a web page element in the user's browser.
    
    Args:
        browser: Which browser to interact with ('Safari', 'Chrome', or 'Edge'), or None to auto-detect
        action: Action to perform ('click', 'fill', 'select', 'navigate', 'scroll', 'wait')
        selector: CSS selector for the element, or URL for navigate
        value: Value to fill or select (required for 'fill' and 'select' actions)
        
    Returns:
        JSON string containing the result of the action
    """
    try:
        action = (action or "").strip()
        selector = selector or ""
        if is_background_browser_session(session_mode):
            return json.dumps(
                background_browser_not_available_result(action=f"interact.{action}", browser=browser),
                ensure_ascii=False,
            )

        browser, window_index, tab_index, target = resolve_browser_target_inputs(
            browser=browser,
            window_index=window_index,
            tab_index=tab_index,
            browser_automation_target=browser_automation_target,
        )

        # Auto-detect browser if not specified
        if browser is None or browser.strip() == "":
            browser = await _get_default_browser()
            logger.info(f"🖱️ Browser interact requested: browser={browser} (auto-detected), action={action}, selector={selector[:50]}")
        else:
            logger.info(f"🖱️ Browser interact requested: browser={browser}, action={action}, selector={selector[:50]}")
        
        # Validate action
        valid_actions = ['click', 'fill', 'select', 'navigate', 'scroll', 'wait']
        if not action:
            return json.dumps({
                "success": False,
                "error": "browser_interact requires an action.",
                "valid_actions": valid_actions,
            }, ensure_ascii=False)
        if action not in valid_actions:
            return json.dumps({
                "success": False,
                "action": action,
                "error": f"Invalid action: '{action}'. Must be one of: {', '.join(valid_actions)}"
            }, ensure_ascii=False)

        actions_requiring_selector = {"click", "fill", "select", "navigate", "scroll"}
        if action in actions_requiring_selector and not selector.strip():
            required_name = "URL in the 'selector' parameter" if action == "navigate" else "'selector'"
            return json.dumps({
                "success": False,
                "action": action,
                "error": f"Action '{action}' requires {required_name}.",
            }, ensure_ascii=False)
        
        # Validate value for actions that require it
        if action in ['fill', 'select'] and not value:
            return json.dumps({
                "success": False,
                "action": action,
                "error": f"Action '{action}' requires a 'value' parameter."
            }, ensure_ascii=False)
        
        allow_sensitive_fill = False
        redact_value = False
        sensitive_domain = None
        action_value = value

        if action == "fill":
            metadata = await _run_browser_js(
                browser,
                _build_element_metadata_js(selector),
                window_index=window_index,
                tab_index=tab_index,
            )
            if metadata.get("success") and is_sensitive_field_metadata(metadata, selector):
                approval_manager = get_browser_sensitive_approval_manager()
                decision = await approval_manager.evaluate_sensitive_fill_request(
                    BrowserSensitiveFillRequest(
                        browser=browser,
                        selector=selector,
                        url=str(metadata.get("url") or ""),
                        field_metadata=metadata,
                    )
                )
                if not decision.allowed:
                    return json.dumps({
                        "success": False,
                        "requires_user_input": decision.requires_user_input,
                        "approval_denied": decision.approval_denied,
                        "sensitive_fill": True,
                        "domain": decision.domain,
                        "error": decision.reason,
                    }, ensure_ascii=False)

                if decision.sensitive_value_token:
                    token_value = get_browser_sensitive_value_store().consume_sensitive_value(
                        decision.sensitive_value_token
                    )
                    if token_value is None:
                        return json.dumps({
                            "success": False,
                            "sensitive_fill": True,
                            "domain": decision.domain,
                            "error": "Approved sensitive value expired or was already used.",
                        }, ensure_ascii=False)
                    action_value = token_value

                allow_sensitive_fill = True
                redact_value = True
                sensitive_domain = decision.domain

        if action == "wait" and not selector.strip():
            await asyncio.sleep(0.5)

        # Build and execute the JavaScript action
        js_code = _build_action_js(
            action,
            selector,
            action_value,
            allow_sensitive_fill=allow_sensitive_fill,
            redact_value=redact_value,
        )
        timeout = 45.0 if action == 'wait' else 30.0
        result = await _run_browser_js(
            browser,
            js_code,
            timeout=timeout,
            window_index=window_index,
            tab_index=tab_index,
        )

        # Add browser info to result
        if isinstance(result, dict):
            result["browser"] = browser
            if target is not None:
                result["browser_automation_target"] = target.to_result()
            elif window_index is not None or tab_index is not None:
                result["browser_automation_target"] = {
                    "browser": browser,
                    "window_index": window_index or 1,
                    "tab_index": tab_index or 1,
                    "expected_url": result.get("newUrl") or result.get("url"),
                    "expected_title": result.get("title"),
                    "created_by_basil": False,
                    "agent_task_id": None,
                }
            if redact_value:
                result["sensitive_fill"] = True
                result["value_redacted"] = True
                result["domain"] = sensitive_domain
                if "valueFilled" in result:
                    result["valueFilled"] = "[redacted]"
            trace_entry = record_browser_trace(
                action=f"interact.{action}",
                browser=browser,
                domain=sensitive_domain,
                selector=selector,
                success=bool(result.get("success")),
                warning=result.get("error"),
                metadata=result,
            )
            if trace_entry:
                result["browser_trace"] = trace_entry
            logger.info(
                "BROWSER_AUDIT action=%s browser=%s selector=%s success=%s url=%s",
                action,
                browser,
                selector[:120],
                result.get("success"),
                result.get("newUrl"),
            )

        if result.get("success"):
            logger.info(f"✅ Browser interaction completed: {action} on {selector[:50]}")
        else:
            logger.warning(f"⚠️ Browser interaction failed: {result.get('error', 'unknown error')}")

        return json.dumps(result, ensure_ascii=False, indent=2)
            
    except ValueError as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)
    except CheckpointRequest:
        raise
    except Exception as e:
        logger.error(f"❌ Browser interact failed: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"Interaction failed: {str(e)}"
        }, ensure_ascii=False)


def create_browser_interact_tool(profile=None) -> StructuredTool:
    """Factory for the ``browser_interact`` tool.

    Under a slim rendering profile the description is swapped to
    ``SLIM_DESCRIPTION`` above; otherwise ``_FULL_DESCRIPTION`` flows
    through unchanged.
    """
    tool_description = select_description_for_profile(
        profile, FULL_DESCRIPTION, SLIM_DESCRIPTION
    )

    return StructuredTool.from_function(
        func=_browser_interact_impl,
        name="browser_interact",
        description=tool_description,
        args_schema=BrowserInteractInput,
        coroutine=_browser_interact_impl  # Mark as async
    )
