"""Explain a failed selector lookup so the agent can tell a changed page from a wrong selector."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from .browser_challenge_js import CHALLENGE_DETECTION_FUNCTION_JS
from .browser_page_settle import RunJs

logger = logging.getLogger(__name__)

_NOT_FOUND_JS_TEMPLATE = "// basil:not_found_diagnostics\n(function() {\n    var token = __TOKEN__;\n" + CHALLENGE_DETECTION_FUNCTION_JS + r'''
    function diagnosticVisible(el) {
        if (!el || typeof el.getBoundingClientRect !== 'function') return false;
        var style = window.getComputedStyle(el);
        var rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    }
    function pickSelector(el) {
        var tag = el.tagName.toLowerCase();
        if (el.id) return '#' + el.id;
        var name = el.getAttribute('name');
        if (name) return tag + '[name="' + String(name).replace(/"/g, '\\"') + '"]';
        return null;
    }
    var similar = [];
    var seen = {};
    if (token) {
        var nodes = document.querySelectorAll('input, select, textarea, button, a[href], [id]');
        for (var i = 0; i < nodes.length && similar.length < 6; i++) {
            var el = nodes[i];
            var haystack = ((el.id || '') + ' ' + (el.getAttribute('name') || '') + ' ' + (el.getAttribute('aria-label') || '') + ' ' + String(el.textContent || '').slice(0, 60)).toLowerCase();
            if (haystack.indexOf(token) === -1) continue;
            var selector = pickSelector(el);
            if (!selector || seen[selector]) continue;
            seen[selector] = true;
            similar.push({selector: selector, tag: el.tagName.toLowerCase(), visible: diagnosticVisible(el)});
        }
    }
    var text = (document.body && document.body.innerText) ? document.body.innerText : '';
    return JSON.stringify({
        success: true,
        url: window.location.href,
        title: document.title,
        ready: document.readyState,
        text_head: text.replace(/\s+/g, ' ').trim().slice(0, 240),
        similar: similar,
        challenge: basilDetectChallenge()
    });
})();
'''


def similar_token(selector: str) -> str:
    """Pick the longest word-like fragment of a selector to look for among the page's ids and names."""

    fragments = re.findall(r"[A-Za-z][A-Za-z0-9]{3,}", selector or "")
    if not fragments:
        return ""
    return max(fragments, key=len).lower()


def build_not_found_diagnostics_js(selector: str) -> str:
    return _NOT_FOUND_JS_TEMPLATE.replace("__TOKEN__", json.dumps(similar_token(selector)))


def is_not_found_result(result: Dict[str, Any]) -> bool:
    if not isinstance(result, dict) or result.get("success") is not False:
        return False
    if result.get("sensitive_fill") or result.get("requires_user_input"):
        return False
    return "not found" in str(result.get("error") or "").lower()


def build_not_found_hint(page_state: Dict[str, Any]) -> str:
    challenge = page_state.get("challenge")
    if isinstance(challenge, dict):
        kind = str(challenge.get("kind") or "challenge")
        if challenge.get("handoff_only"):
            return (
                f"The page is showing a {kind.replace('_', ' ')} step instead of the page you expected. "
                "Call browser_tabs with action request_human_help, then confirm with browser_inspect that it is gone."
            )
        return (
            "The page is showing a type-the-characters CAPTCHA instead of the page you expected. "
            "Call browser_interact with action capture_captcha, read the image with analyze_with_vision, "
            "then call browser_interact with action submit_captcha."
        )
    if page_state.get("similar"):
        return "No element matched that selector, but the page has similar ones listed in page_state.similar. Use one of those."
    return "The page does not contain that element. Call browser_inspect again, because the page may have changed or navigated."


async def attach_not_found_diagnostics(
    run_js: RunJs,
    browser: str,
    selector: str,
    result: Dict[str, Any],
    *,
    window_index: Optional[int],
    tab_index: Optional[int],
) -> None:
    """Add `page_state` and `hint` to a not-found result. Never raises."""

    if not is_not_found_result(result):
        return
    try:
        diagnostics = await run_js(
            browser,
            build_not_found_diagnostics_js(selector),
            timeout=15.0,
            window_index=window_index,
            tab_index=tab_index,
        )
    except Exception as error:
        logger.debug("Not-found diagnostics failed: %s", error)
        return
    if not isinstance(diagnostics, dict) or not diagnostics.get("success"):
        return
    diagnostics.pop("success", None)
    result["page_state"] = diagnostics
    result["hint"] = build_not_found_hint(diagnostics)
