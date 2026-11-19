"""A per-task switch that approves every shell command the task asks to run.

It is the user's way out of approval prompts for one task, when they know that task is safe to run unattended. The switch is held in memory and keyed by the chain's root task id, so every follow-up turn of the task shares it and a backend restart turns it off. Nothing here is saved to the user's preferences. The approval service decides where the switch applies and what it never overrides.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Optional

MAX_TRACKED_TASKS = 512

_enabled: "OrderedDict[str, bool]" = OrderedDict()
_lock = threading.Lock()


def _key(root_task_id: Any) -> Optional[str]:
    if not isinstance(root_task_id, str):
        return None
    key = root_task_id.strip()
    return key or None


def set_task_auto_approve(root_task_id: Any, enabled: bool) -> bool:
    """Turn the switch on or off for one task. Returns False when the task id is unusable and nothing changed."""
    key = _key(root_task_id)
    if key is None:
        return False
    with _lock:
        if enabled:
            _enabled[key] = True
            _enabled.move_to_end(key)
            # Forgetting the oldest switch turns it off, which is the safe direction to fail in.
            while len(_enabled) > MAX_TRACKED_TASKS:
                _enabled.popitem(last=False)
        else:
            _enabled.pop(key, None)
    return True


def is_task_auto_approve_enabled(root_task_id: Any) -> bool:
    key = _key(root_task_id)
    if key is None:
        return False
    with _lock:
        return key in _enabled


def clear_all_task_auto_approve() -> None:
    """Turn every switch off. Used by tests."""
    with _lock:
        _enabled.clear()
