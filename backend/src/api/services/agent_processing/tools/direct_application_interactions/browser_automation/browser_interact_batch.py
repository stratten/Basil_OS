"""Fill several form fields in one tool call, then read the values back."""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Dict, List

logger = logging.getLogger(__name__)

MAX_FORM_FIELDS = 25

_FORM_READBACK_JS_TEMPLATE = r'''// basil:form_readback
(function() {
    var selectors = __SELECTORS__;
    var sensitivePattern = /password|passwd|passcode|secret|token|cvv|cvc|card|ssn|routing/i;
    function queryDeep(deepSelector) {
        var parts = String(deepSelector).split(/\s*>>>\s*/).filter(Boolean);
        var root = document;
        var current = null;
        for (var i = 0; i < parts.length; i++) {
            current = root.querySelector(parts[i]);
            if (!current) return null;
            if (i === parts.length - 1) return current;
            if (current.shadowRoot) root = current.shadowRoot;
            else if (current.contentDocument) root = current.contentDocument;
            else return null;
        }
        return current;
    }
    var out = {};
    for (var s = 0; s < selectors.length; s++) {
        try {
            var el = queryDeep(selectors[s]);
            if (!el) { out[selectors[s]] = {found: false}; continue; }
            var tag = el.tagName.toLowerCase();
            var type = el.type || null;
            var hint = [type, el.name, el.id, el.getAttribute('autocomplete')].join(' ');
            var masked = type === 'password' || sensitivePattern.test(hint);
            var entry = {found: true, tag: tag, type: type};
            if (type === 'checkbox' || type === 'radio') entry.checked = Boolean(el.checked);
            else if (tag === 'select' && el.selectedIndex >= 0) entry.selected_text = String(el.options[el.selectedIndex].text).slice(0, 120);
            else entry.value = masked ? '[hidden]' : String(el.value === undefined ? '' : el.value).slice(0, 200);
            out[selectors[s]] = entry;
        } catch (error) {
            out[selectors[s]] = {found: false, error: String(error && error.message ? error.message : error)};
        }
    }
    return JSON.stringify({success: true, fields: out});
})();
'''


def build_form_readback_js(selectors: List[str]) -> str:
    return _FORM_READBACK_JS_TEMPLATE.replace("__SELECTORS__", json.dumps(list(selectors)))


FillOne = Callable[[str, str], Awaitable[str]]
ReadBack = Callable[[List[str]], Awaitable[Dict[str, Any]]]


async def fill_form_batch(fill_one: FillOne, read_back: ReadBack, fields: Any) -> Dict[str, Any]:
    """Fill each selector in order through `fill_one`, stop at the first failure, and read the filled values back."""

    if not isinstance(fields, dict) or not fields:
        return {
            "success": False,
            "action": "fill_form",
            "error": "Action 'fill_form' requires a non-empty 'fields' object mapping each selector to its value.",
        }
    if len(fields) > MAX_FORM_FIELDS:
        return {
            "success": False,
            "action": "fill_form",
            "error": f"Action 'fill_form' accepts at most {MAX_FORM_FIELDS} fields per call.",
        }
    items = [(str(selector).strip(), "" if value is None else str(value)) for selector, value in fields.items()]
    if any(not selector for selector, _ in items):
        return {"success": False, "action": "fill_form", "error": "Every key in 'fields' must be a non-empty selector."}

    filled: List[str] = []
    failed: Dict[str, Any] = {}
    skipped: List[str] = []
    for index, (selector, value) in enumerate(items):
        raw = await fill_one(selector, value)
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            parsed = {"success": False, "error": str(raw)[:200]}
        if isinstance(parsed, dict) and parsed.get("success"):
            filled.append(selector)
            continue
        parsed = parsed if isinstance(parsed, dict) else {}
        failed = {
            "selector": selector,
            "error": parsed.get("error") or "Fill failed.",
            "requires_user_input": bool(parsed.get("requires_user_input")),
            "sensitive_fill": bool(parsed.get("sensitive_fill")),
        }
        if parsed.get("page_state") is not None:
            failed["page_state"] = parsed["page_state"]
        if parsed.get("hint"):
            failed["hint"] = parsed["hint"]
        skipped = [remaining for remaining, _ in items[index + 1:]]
        break

    result: Dict[str, Any] = {
        "success": not failed,
        "action": "fill_form",
        "field_count": len(items),
        "filled": filled,
    }
    if filled:
        try:
            readback = await read_back(filled)
            result["readback"] = readback.get("fields", {}) if isinstance(readback, dict) else {}
        except Exception as error:
            logger.debug("Form readback failed: %s", error)
            result["readback_error"] = str(error)[:200]
    if failed:
        result["failed"] = failed
        result["skipped"] = skipped
        result["error"] = f"Stopped at {failed['selector']}: {failed['error']}"
        if failed["requires_user_input"]:
            result["requires_user_input"] = True
    return result
