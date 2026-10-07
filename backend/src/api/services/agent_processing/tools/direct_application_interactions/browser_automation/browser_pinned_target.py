"""Remember the dedicated browser window Basil opened for each task chain."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .browser_target_runtime import BrowserAutomationTarget

_pinned_targets: dict[str, "BrowserAutomationTarget"] = {}
_pinned_targets_lock = threading.Lock()

_BROWSER_FAMILIES = {
    "safari": "safari",
    "chrome": "chrome",
    "google chrome": "chrome",
    "edge": "edge",
    "microsoft edge": "edge",
}


def _browser_family(browser: Optional[str]) -> Optional[str]:
    return _BROWSER_FAMILIES.get((browser or "").strip().lower())


def browser_pin_key() -> Optional[str]:
    from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

    context = get_current_agent_context()
    key = context.get("root_task_id") or context.get("agent_task_id")
    return str(key) if key else None


def current_agent_task_id() -> Optional[str]:
    from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context

    agent_task_id = get_current_agent_context().get("agent_task_id")
    return str(agent_task_id) if agent_task_id else None


def pin_browser_target(target: "BrowserAutomationTarget") -> None:
    key = browser_pin_key()
    if key is None or target.window_id is None:
        return
    with _pinned_targets_lock:
        _pinned_targets[key] = target


def pinned_browser_target(browser: Optional[str] = None) -> Optional["BrowserAutomationTarget"]:
    """Return the chain's pinned target, or None when there is none or it belongs to a different browser."""
    key = browser_pin_key()
    if key is None:
        return None
    with _pinned_targets_lock:
        target = _pinned_targets.get(key)
    if target is None:
        return None
    if browser and _browser_family(browser) != _browser_family(target.browser):
        return None
    return target


def clear_pinned_browser_targets(key: Optional[str] = None) -> None:
    with _pinned_targets_lock:
        if key is None:
            _pinned_targets.clear()
        else:
            _pinned_targets.pop(key, None)
