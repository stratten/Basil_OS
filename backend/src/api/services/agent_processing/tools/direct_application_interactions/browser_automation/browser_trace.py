"""Structured browser action trace helpers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from api.core.preferences.preferences_io import load_preferences

logger = logging.getLogger(__name__)


def browser_action_trace_enabled() -> bool:
    """Return whether browser action trace recording is enabled."""
    try:
        return bool(load_preferences().browser_automation.record_browser_action_trace)
    except Exception:
        return True


def build_browser_trace_entry(
    action: str,
    browser: Optional[str] = None,
    domain: Optional[str] = None,
    selector: Optional[str] = None,
    target_text: Optional[str] = None,
    success: Optional[bool] = None,
    warning: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a redacted structured trace entry for browser automation."""
    trace_metadata: Dict[str, Any] = {
        "browser_action": action,
        "browser": browser,
        "domain": domain,
        "selector": selector,
        "target_text": target_text,
        "success": success,
        "warning": warning,
    }
    if metadata:
        trace_metadata.update(_redact_sensitive_metadata(metadata))

    return {
        "id": f"browser_trace_{action}_{datetime.now().timestamp()}",
        "type": "step",
        "timestamp": datetime.now().isoformat(),
        "content": f"Browser action: {action}",
        "detail_kind": "tool_result" if success is not None else "step_note",
        "summary": f"Browser {action}",
        "body": warning or f"{action} on {domain or browser or 'browser'}",
        "metadata": trace_metadata,
        "streaming": False,
    }


def record_browser_trace(
    action: str,
    browser: Optional[str] = None,
    domain: Optional[str] = None,
    selector: Optional[str] = None,
    target_text: Optional[str] = None,
    success: Optional[bool] = None,
    warning: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Record a redacted browser trace entry through the current trace sink."""
    if not browser_action_trace_enabled():
        return None
    entry = build_browser_trace_entry(
        action=action,
        browser=browser,
        domain=domain,
        selector=selector,
        target_text=target_text,
        success=success,
        warning=warning,
        metadata=metadata,
    )
    logger.info("BROWSER_TRACE %s", entry["metadata"])
    return entry


def _redact_sensitive_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    redacted = dict(metadata)
    for key in list(redacted.keys()):
        if key.lower() in {"value", "valuefilled", "password", "token", "secret"}:
            redacted[key] = "[redacted]"
    if redacted.get("sensitive_fill"):
        redacted["value_redacted"] = True
    return redacted

