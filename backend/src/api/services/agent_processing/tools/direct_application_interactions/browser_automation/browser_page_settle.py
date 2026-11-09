"""Wait for a selector from Python and wait for a page to stop changing after a click.

AppleScript `execute javascript` cannot await a Promise, so waiting is done here: each probe is a synchronous script, and the loop and the sleeping happen in Python.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from .browser_challenge_js import CHALLENGE_DETECTION_FUNCTION_JS

logger = logging.getLogger(__name__)

RunJs = Callable[..., Awaitable[Dict[str, Any]]]

WAIT_ATTEMPTS = 20
WAIT_INTERVAL_S = 0.5
SETTLE_INITIAL_DELAY_S = 0.35
SETTLE_MAX_WAIT_S = 8.0
SETTLE_INTERVAL_S = 0.4
SETTLE_STABLE_PROBES = 2
# Clicks on these input types never navigate, so settling would only add delay.
NON_NAVIGATING_INPUT_TYPES = frozenset({"checkbox", "radio"})

SETTLE_PROBE_JS = r'''// basil:settle_probe
(function() {
    var text = (document.body && document.body.innerText) ? document.body.innerText : '';
    return JSON.stringify({success: true, ready: document.readyState, url: window.location.href, title: document.title, text_length: text.length});
})();
'''

PAGE_SUMMARY_JS = "// basil:page_summary\n(function() {\n" + CHALLENGE_DETECTION_FUNCTION_JS + r'''
    function summaryVisible(el) {
        if (!el || typeof el.getBoundingClientRect !== 'function') return false;
        var style = window.getComputedStyle(el);
        var rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    }
    var headings = [];
    var headingNodes = document.querySelectorAll('h1, h2, h3');
    for (var h = 0; h < headingNodes.length && headings.length < 6; h++) {
        var headingText = (headingNodes[h].innerText || '').replace(/\s+/g, ' ').trim();
        if (headingText && summaryVisible(headingNodes[h])) headings.push(headingText.slice(0, 80));
    }
    var messages = [];
    var messageNodes = document.querySelectorAll('[role="alert"], .validation-summary-errors, .field-validation-error, .error, .errors, .text-danger, .alert-danger, .alert-error, .error-message');
    for (var m = 0; m < messageNodes.length && messages.length < 5; m++) {
        var messageText = (messageNodes[m].innerText || '').replace(/\s+/g, ' ').trim();
        if (messageText && summaryVisible(messageNodes[m]) && messages.indexOf(messageText.slice(0, 160)) === -1) messages.push(messageText.slice(0, 160));
    }
    return JSON.stringify({
        success: true,
        url: window.location.href,
        title: document.title,
        ready: document.readyState,
        headings: headings,
        messages: messages,
        challenge: basilDetectChallenge()
    });
})();
'''

_sleep = asyncio.sleep


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {"success": False, "error": "Browser returned an unexpected response."}


def _not_visible_yet(result: Dict[str, Any]) -> bool:
    return str(result.get("error") or "").startswith("Element not visible yet")


async def wait_for_selector(
    run_js: RunJs,
    browser: str,
    probe_js: str,
    selector: str,
    *,
    window_index: Optional[int],
    tab_index: Optional[int],
    attempts: int = WAIT_ATTEMPTS,
    interval_s: float = WAIT_INTERVAL_S,
) -> Dict[str, Any]:
    """Poll a synchronous visibility probe until the element is visible or the attempts run out."""

    last: Dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        result = _as_dict(
            await run_js(browser, probe_js, timeout=30.0, window_index=window_index, tab_index=tab_index)
        )
        if result.get("success"):
            result["attempts"] = attempt
            return result
        if result.get("empty_response") or _not_visible_yet(result):
            last = result
            if attempt < attempts:
                await _sleep(interval_s)
            continue
        result["attempts"] = attempt
        return result
    return {
        "success": False,
        "action": "wait",
        "selector": selector,
        "found": bool(last.get("found")),
        "visible": False,
        "attempts": attempts,
        "newUrl": last.get("newUrl"),
        "newTitle": last.get("newTitle"),
        "error": f"Element not found after {attempts * interval_s:g}s: {selector}",
    }


async def settle_after_click(
    run_js: RunJs,
    browser: str,
    *,
    before_url: Optional[str],
    before_title: Optional[str],
    window_index: Optional[int],
    tab_index: Optional[int],
    max_wait_s: float = SETTLE_MAX_WAIT_S,
    interval_s: float = SETTLE_INTERVAL_S,
    stable_probes: int = SETTLE_STABLE_PROBES,
) -> Dict[str, Any]:
    """Wait until two consecutive complete probes agree, then return a compact summary of the page."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + max_wait_s
    max_probes = int(max_wait_s / interval_s) + 1
    await _sleep(SETTLE_INITIAL_DELAY_S)
    previous = None
    stable = 0
    settled = False
    for probe_number in range(1, max_probes + 1):
        probe = _as_dict(
            await run_js(browser, SETTLE_PROBE_JS, timeout=10.0, window_index=window_index, tab_index=tab_index)
        )
        signature = None
        if probe.get("success") and probe.get("ready") == "complete":
            signature = (probe.get("url"), probe.get("title"), probe.get("text_length"))
        if signature is not None and signature == previous:
            stable += 1
        else:
            stable = 1 if signature is not None else 0
        previous = signature
        if stable >= stable_probes:
            settled = True
            break
        if loop.time() >= deadline or probe_number >= max_probes:
            break
        await _sleep(interval_s)

    summary = _as_dict(
        await run_js(browser, PAGE_SUMMARY_JS, timeout=15.0, window_index=window_index, tab_index=tab_index)
    )
    if not summary.get("success"):
        return {"settled": settled, "navigated": False, "page": {}, "page_summary_error": summary.get("error")}
    summary.pop("success", None)
    summary.pop("ready", None)
    navigated = bool(
        (before_url and summary.get("url") and summary["url"] != before_url)
        or (before_title and summary.get("title") and summary["title"] != before_title)
    )
    return {"settled": settled, "navigated": navigated, "page": summary}
