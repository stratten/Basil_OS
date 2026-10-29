"""In-memory pause requests and queued user notes for agent runs that are currently attached to a loop."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence
from uuid import uuid4


def note_with_references(text: str, reference_paths: Sequence[str]) -> str:
    """The note text followed by the local paths the user attached to it."""
    body = text.strip()
    paths = [path for path in reference_paths if path]
    if not paths:
        return body
    listing = "Attached for you to look at (local paths on the user's Mac):\n" + "\n".join(f"- {path}" for path in paths)
    return f"{body}\n\n{listing}" if body else listing


@dataclass(frozen=True)
class QueuedRunMessage:
    message_id: str
    text: str
    queued_at: str


class AgentRunControl:
    """Pause flag and note queue for one agent task's live loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._attached = False
        self._pause_requested = False
        self._queue: List[QueuedRunMessage] = []

    def attach(self) -> None:
        with self._lock:
            self._attached = True
            self._pause_requested = False

    def detach(self) -> List[QueuedRunMessage]:
        with self._lock:
            self._attached = False
            self._pause_requested = False
            leftovers = list(self._queue)
            self._queue.clear()
            return leftovers

    def is_attached(self) -> bool:
        with self._lock:
            return self._attached

    def request_pause(self) -> bool:
        with self._lock:
            if not self._attached:
                return False
            self._pause_requested = True
            return True

    def pause_requested(self) -> bool:
        with self._lock:
            return self._pause_requested

    def clear_pause(self) -> None:
        with self._lock:
            self._pause_requested = False

    def enqueue(self, text: str) -> Optional[QueuedRunMessage]:
        with self._lock:
            if not self._attached:
                return None
            message = QueuedRunMessage(
                message_id=f"note_{uuid4().hex}",
                text=text,
                queued_at=datetime.now(timezone.utc).isoformat(),
            )
            self._queue.append(message)
            return message

    def drain(self) -> List[QueuedRunMessage]:
        with self._lock:
            drained = list(self._queue)
            self._queue.clear()
            return drained


_controls_lock = threading.Lock()
_controls: Dict[str, AgentRunControl] = {}


def run_control_for(agent_task_id: str) -> AgentRunControl:
    with _controls_lock:
        control = _controls.get(agent_task_id)
        if control is None:
            control = AgentRunControl()
            _controls[agent_task_id] = control
        return control


def existing_run_control(agent_task_id: str) -> Optional[AgentRunControl]:
    with _controls_lock:
        return _controls.get(agent_task_id)


def discard_run_control(agent_task_id: str, control: AgentRunControl) -> None:
    if control.is_attached():
        return
    with _controls_lock:
        if _controls.get(agent_task_id) is control:
            del _controls[agent_task_id]
