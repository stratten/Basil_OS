"""
Browser Inspect Tool for Agent

Provides the agent with the ability to inspect web pages in the user's existing browser
(Safari, Chrome, or Edge) and extract structured information about interactive elements.
This enables DOM-aware browser automation using the user's logged-in session.
"""

import json
import logging
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

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

_get_default_browser = resolve_preferred_user_browser


class BrowserInspectInput(BaseModel):
    """Input schema for browser inspect tool."""
    browser: Optional[str] = Field(
        default=None,
        description="Browser to inspect: 'Safari', 'Chrome', 'Edge', or leave empty to auto-detect the user's default browser"
    )
    focus: Literal["buttons", "forms", "links", "text", "content", "all"] = Field(
        default="all",
        description="Element type to focus on. 'content' returns the page's main readable text."
    )
    session_mode: Literal["user_browser", "basil_automation_browser"] = Field(
        default="user_browser",
        description="Browser runtime to use. user_browser uses Safari/Chrome/Edge; basil_automation_browser is the future background runtime.",
    )
    window_index: Optional[int] = Field(default=None, description="Optional 1-based browser window index to inspect.")
    tab_index: Optional[int] = Field(default=None, description="Optional 1-based tab index to inspect.")
    browser_automation_target: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured target returned by browser_tabs.ensure_automation_window.",
    )


# JavaScript code to extract DOM information
_INSPECT_JS_CODE = '''
(function() {
    const info = {
        url: window.location.href,
        title: document.title,
        ready: document.readyState,
        buttons: [],
        inputs: [],
        links: [],
        headings: [],
        skippedFrames: [],
        requires_user_input: false,
        safety_warnings: []
    };

    const seen = new Set();
    const maxPerGroup = 50;

    function cssEscape(value) {
        if (window.CSS && typeof window.CSS.escape === 'function') {
            return window.CSS.escape(value);
        }
        return String(value).replace(/[^a-zA-Z0-9_-]/g, '\\\\$&');
    }

    function localSelector(el) {
        if (!el || !el.tagName) return null;
        const tag = el.tagName.toLowerCase();
        if (el.id) return '#' + cssEscape(el.id);
        if (el.name) return tag + '[name="' + String(el.name).replace(/"/g, '\\\\"') + '"]';
        const aria = el.getAttribute('aria-label');
        if (aria) return tag + '[aria-label="' + aria.replace(/"/g, '\\\\"') + '"]';
        if (typeof el.className === 'string') {
            const firstClass = el.className.trim().split(/\\s+/).find(Boolean);
            if (firstClass) return tag + '.' + cssEscape(firstClass);
        }
        const parent = el.parentElement;
        if (!parent) return tag;
        const siblings = Array.from(parent.children).filter(child => child.tagName === el.tagName);
        if (siblings.length <= 1) return tag;
        return tag + ':nth-of-type(' + (siblings.indexOf(el) + 1) + ')';
    }

    function selectorFor(el, rootPath) {
        const selector = localSelector(el);
        if (!selector) return null;
        return rootPath ? rootPath + ' >>> ' + selector : selector;
    }

    function isVisible(el) {
        if (!el || typeof el.getBoundingClientRect !== 'function') return false;
        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none'
            && style.visibility !== 'hidden'
            && style.opacity !== '0'
            && rect.width > 0
            && rect.height > 0;
    }

    function textOf(el) {
        return (
            el.innerText
            || el.value
            || el.getAttribute('aria-label')
            || el.getAttribute('title')
            || el.getAttribute('placeholder')
            || ''
        ).trim();
    }

    function isClickable(el) {
        const tag = el.tagName ? el.tagName.toLowerCase() : '';
        const role = (el.getAttribute('role') || '').toLowerCase();
        const style = window.getComputedStyle(el);
        return tag === 'button'
            || tag === 'summary'
            || tag === 'a'
            || role === 'button'
            || role === 'menuitem'
            || role === 'tab'
            || role === 'checkbox'
            || role === 'radio'
            || el.hasAttribute('onclick')
            || el.hasAttribute('tabindex')
            || style.cursor === 'pointer'
            || (tag === 'input' && ['button', 'submit', 'reset', 'checkbox', 'radio'].includes((el.type || '').toLowerCase()));
    }

    function isSensitiveInput(el) {
        const attrs = [
            el.type,
            el.name,
            el.id,
            el.getAttribute('autocomplete'),
            el.getAttribute('aria-label'),
            el.getAttribute('placeholder')
        ].filter(Boolean).join(' ').toLowerCase();
        return /password|passcode|token|secret|credential|one-time|otp|2fa|mfa/.test(attrs);
    }

    function markSafetyWarning(message) {
        if (!info.safety_warnings.includes(message)) {
            info.safety_warnings.push(message);
        }
        info.requires_user_input = true;
    }

    function addUnique(group, item) {
        if (!item.selector || info[group].length >= maxPerGroup) return;
        const key = group + ':' + item.selector;
        if (seen.has(key)) return;
        seen.add(key);
        info[group].push(item);
    }

    function addHeading(text) {
        if (!text || info.headings.length >= maxPerGroup) return;
        if (info.headings.includes(text)) return;
        info.headings.push(text);
    }

    function inspectRoot(root, rootPath) {
        const elements = Array.from(root.querySelectorAll('*'));
        for (const el of elements) {
            if (!isVisible(el)) continue;
            const tag = el.tagName.toLowerCase();
            const selector = selectorFor(el, rootPath);
            if (!selector) continue;

            if (isClickable(el)) {
                addUnique('buttons', {
                    selector: selector,
                    text: textOf(el).slice(0, 80),
                    tag: tag,
                    role: el.getAttribute('role') || '',
                    disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true')
                });
            }

            if ((tag === 'input' && (el.type || '').toLowerCase() !== 'hidden') || tag === 'select' || tag === 'textarea') {
                const sensitive = isSensitiveInput(el);
                if (sensitive) {
                    markSafetyWarning('Credential-like field detected; user input is required before filling credentials.');
                }
                addUnique('inputs', {
                    selector: selector,
                    type: el.type || tag,
                    placeholder: el.placeholder || '',
                    required: Boolean(el.required),
                    sensitive: sensitive,
                    value: sensitive ? '[hidden]' : (el.value || '').slice(0, 50)
                });
            }

            if (tag === 'a' && el.href && textOf(el)) {
                addUnique('links', {
                    selector: selector,
                    text: textOf(el).slice(0, 60),
                    href: el.href
                });
            }

            if (/^h[1-3]$/.test(tag) && textOf(el)) {
                addHeading(textOf(el).slice(0, 80));
            }

            const label = textOf(el).toLowerCase();
            if (label.includes('captcha') || label.includes('recaptcha') || label.includes('hcaptcha')) {
                markSafetyWarning('CAPTCHA-like content detected; user input is required.');
            }

            if (el.shadowRoot) {
                inspectRoot(el.shadowRoot, selector);
            }

            if (tag === 'iframe' || tag === 'frame') {
                try {
                    if (el.contentDocument) {
                        inspectRoot(el.contentDocument, selector);
                    } else {
                        info.skippedFrames.push({ selector: selector, reason: 'No accessible contentDocument' });
                    }
                } catch (frameError) {
                    info.skippedFrames.push({ selector: selector, reason: 'Cross-origin or inaccessible frame' });
                }
            }
        }
    }

    function mainReadableText() {
        var main = document.querySelector('main, article, [role="main"]');
        var root = main || document.body;
        if (!root || !root.innerText) {
            info.mainTextMeta = {
                truncated: false,
                original_char_count: 0,
                returned_char_count: 0
            };
            return '';
        }
        var fullText = root.innerText.replace(/\\n{3,}/g, '\\n\\n').trim();
        var clippedText = fullText.slice(0, 12000);
        info.mainTextMeta = {
            truncated: fullText.length > clippedText.length,
            original_char_count: fullText.length,
            returned_char_count: clippedText.length,
            continuation_hint: fullText.length > clippedText.length
                ? 'Page text exceeded browser_inspect mainText cap; use a narrower page section or dedicated page retrieval before claiming full-page coverage.'
                : null
        };
        return clippedText;
    }
    info.mainText = mainReadableText();

    inspectRoot(document, '');
    return JSON.stringify(info);
})();
'''


_build_applescript = build_browser_applescript


async def _browser_inspect_impl(
    browser: Optional[str] = None,
    focus: Optional[str] = "all",
    session_mode: str = "user_browser",
    window_index: Optional[int] = None,
    tab_index: Optional[int] = None,
    browser_automation_target: Optional[Dict[str, Any]] = None,
) -> str:
    """Implementation of browser inspect tool.
    
    Executes JavaScript in the user's browser to extract DOM information
    about interactive elements on the current page.
    
    Args:
        browser: Which browser to inspect ('Safari', 'Chrome', or 'Edge'), or None to auto-detect
        focus: Element type to focus on ('buttons', 'forms', 'links', 'text', 'all')
        
    Returns:
        JSON string containing page information and interactive elements
    """
    try:
        if is_background_browser_session(session_mode):
            return json.dumps(
                background_browser_not_available_result(action="inspect", browser=browser),
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
            logger.info(f"🔍 Browser inspect requested: browser={browser} (auto-detected), focus={focus}")
        else:
            logger.info(f"🔍 Browser inspect requested: browser={browser}, focus={focus}")
        
        success, output, stderr = await run_applescript(
            _build_applescript(
                browser,
                _INSPECT_JS_CODE,
                window_index=window_index,
                tab_index=tab_index,
            ),
            timeout_s=30.0,
        )
        if not success:
            logger.error(f"❌ AppleScript execution failed: {stderr}")
            permission_result = handle_browser_permission_issue(
                stderr,
                browser=browser,
                action="inspect",
            )
            if permission_result:
                return json.dumps(permission_result, ensure_ascii=False)

            if "timed out" in stderr.lower():
                return json.dumps({
                    "success": False,
                    "browser": browser,
                    "action": "inspect",
                    "error": "Browser inspection timed out. The page may be unresponsive."
                }, ensure_ascii=False)

            return json.dumps({
                "success": False,
                "browser": browser,
                "action": "inspect",
                "error": f"AppleScript error: {stderr}"
            }, ensure_ascii=False)

        try:
            page_data = json.loads(output)
        except json.JSONDecodeError:
            logger.warning(f"Could not parse browser output as JSON: {output[:200]}")
            return json.dumps({
                "success": False,
                "browser": browser,
                "action": "inspect",
                "error": f"Invalid response from browser: {output[:200]}"
            }, ensure_ascii=False)

        # Check if it's an error response
        if isinstance(page_data, dict) and page_data.get("success") is False:
            page_data.setdefault("browser", browser)
            page_data.setdefault("action", "inspect")
            return json.dumps(page_data, ensure_ascii=False)

        # Filter by focus if specified
        if focus == "content":
            page_data = {
                "url": page_data.get("url", ""),
                "title": page_data.get("title", ""),
                "ready": page_data.get("ready", ""),
                "mainText": page_data.get("mainText", ""),
            }
        elif focus and focus != "all":
            filtered_data = {
                "url": page_data.get("url", ""),
                "title": page_data.get("title", ""),
                "ready": page_data.get("ready", "")
            }

            if focus == "buttons":
                filtered_data["buttons"] = page_data.get("buttons", [])
            elif focus == "forms":
                filtered_data["inputs"] = page_data.get("inputs", [])
            elif focus == "links":
                filtered_data["links"] = page_data.get("links", [])
            elif focus == "text":
                filtered_data["headings"] = page_data.get("headings", [])

            page_data = filtered_data
        else:
            page_data.pop("mainText", None)

        # Add success flag
        page_data["success"] = True
        page_data["browser"] = browser
        if target is not None:
            page_data["browser_automation_target"] = target.to_result()
        elif window_index is not None or tab_index is not None:
            page_data["browser_automation_target"] = {
                "browser": browser,
                "window_index": window_index or 1,
                "tab_index": tab_index or 1,
                "expected_url": page_data.get("url"),
                "expected_title": page_data.get("title"),
                "created_by_basil": False,
                "agent_task_id": None,
            }
        trace_entry = record_browser_trace(
            action="inspect",
            browser=browser,
            domain=page_data.get("url", ""),
            success=True,
            metadata={
                "button_count": len(page_data.get("buttons", [])),
                "input_count": len(page_data.get("inputs", [])),
                "link_count": len(page_data.get("links", [])),
                "focus": focus,
                "browser_automation_target": page_data.get("browser_automation_target"),
            },
        )
        if trace_entry:
            page_data["browser_trace"] = trace_entry

        logger.info(f"✅ Browser inspection completed: {page_data.get('url', 'unknown URL')}")
        logger.info(f"   Found: {len(page_data.get('buttons', []))} buttons, "
                   f"{len(page_data.get('inputs', []))} inputs, "
                   f"{len(page_data.get('links', []))} links")

        return json.dumps(page_data, ensure_ascii=False, indent=2)
            
    except ValueError as e:
        return json.dumps({
            "success": False,
            "error": str(e)
        }, ensure_ascii=False)
    except CheckpointRequest:
        raise
    except Exception as e:
        logger.error(f"❌ Browser inspect failed: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"Inspection failed: {str(e)}"
        }, ensure_ascii=False)


# Why this slim:
# - KEEPS: the inspect-before-interact pairing rule (the agent often guesses
#   selectors and gets ElementNotFound, costing a wasted round); the
#   inspect-only-when-needed companion rule for the post-interact case (so
#   slim doesn't induce inspect spam); the auto-detect-browser hint because
#   leaving the browser arg empty is the right default.
# - DROPS: the OUTPUT shape (a single result teaches the agent the JSON
#   layout); per-call usage examples (the focus Literal + browser field
#   surface the option space directly); the IMPORTANT bullets ('don't guess
#   at selectors', 'wait and retry on missing element') because they are
#   collapsed into the inspect-before-interact rule and a generic retry
#   instinct that is not browser-specific.
SLIM_DESCRIPTION = (
    "Inspect the current web page in the user's existing browser session "
    "(Safari/Chrome/Edge) and return CSS selectors for buttons, inputs, "
    "links, and headings to feed into browser_interact. Use focus=\"content\" "
    "to read the page's main readable text (for research/reading an open "
    "page's body, not just headings). Always inspect before interacting when "
    "you don't already know the selector; only re-inspect after "
    "browser_interact if the next step depends on the new page state. Use "
    "browser_automation_target from browser_tabs.ensure_automation_window "
    "when available. Leave 'browser' empty to auto-detect the user's preference/default."
)

_FULL_DESCRIPTION = """Inspect the current web page in the user's browser to discover interactive elements.

**CAPABILITIES:**
- Extract buttons, form inputs, links, and text from the visible page.
- Returns CSS selectors you can use with browser_interact.
- With focus="content", returns the page's main readable text (mainText) so you
  can read and synthesize an open page's body, not just its headings.
- Works with Safari, Chrome, and Edge.
- Auto-detects the user's default browser if not specified.
- Uses the user's existing browser session (preserves login state and credentials).
- Accepts browser_automation_target from browser_tabs.ensure_automation_window to inspect
  Basil's dedicated tab instead of whichever browser tab is active.

**WHEN TO USE:**
- Call this BEFORE interacting with a page when you do not already know the element's
  selector with high confidence (i.e., you haven't inspected this page in the current
  session, or the page may have changed since the last inspection).
- Call this AFTER browser_interact only when the next action depends on the new page
  state — e.g., you clicked a button and need to know what appeared, or you need to
  verify a form submission. Do NOT call it after every interact unconditionally.
- When you need to understand what's on the current page for the first time.
- When an element was not found and you need to find an alternative selector.

**ITERATIVE WORKFLOW:**
The general loop is: inspect → interact → (inspect only if next step needs page state).
For multi-step workflows, batch actions that don't require intermediate state checks:

1. Call browser_inspect() to discover selectors on the current page.
2. Execute all browser_interact() calls whose selectors you now know.
3. Call browser_inspect() again only if you need to know the resulting page state
   before deciding the next action.
4. Repeat from step 2 until goal is achieved.

**USAGE EXAMPLES:**
- browser_inspect() - auto-detect default browser and inspect
- browser_inspect(focus="buttons") - only show buttons in default browser
- browser_inspect(browser="Safari") - explicitly use Safari
- browser_inspect(browser="Edge", focus="forms") - inspect Edge forms

**OUTPUT:**
Returns JSON with:
- `url`: Current page URL.
- `title`: Page title.
- `browser`: Which browser was used (helpful when auto-detected).
- `buttons`: List of clickable elements with selectors.
- `inputs`: Form fields with selectors and current values.
- `links`: Anchor tags with href and text.
- `headings`: H1-H3 text for context.
- `mainText`: Page's main readable text (only when focus="content").

**IMPORTANT:**
- Leave browser empty to auto-detect the user's default browser (recommended).
- Always inspect BEFORE interacting - don't guess at selectors.
- If expected element not found, the page may still be loading - wait and retry.
- Use the returned selectors exactly as provided for browser_interact.
"""


def create_browser_inspect_tool(profile=None) -> StructuredTool:
    """Factory for the ``browser_inspect`` tool.

    Under a slim rendering profile the description is swapped to
    ``SLIM_DESCRIPTION`` above; otherwise ``_FULL_DESCRIPTION`` flows
    through unchanged.
    """
    tool_description = select_description_for_profile(
        profile, _FULL_DESCRIPTION, SLIM_DESCRIPTION
    )

    return StructuredTool.from_function(
        func=_browser_inspect_impl,
        name="browser_inspect",
        description=tool_description,
        args_schema=BrowserInspectInput,
        coroutine=_browser_inspect_impl  # Mark as async
    )
