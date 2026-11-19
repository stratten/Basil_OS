"""In-memory pause requests and queued user notes for agent runs that are currently attached to a loop."""

from __future__ import annotations

import threading
from collections import OrderedDict
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

    def enqueue(self, text: str, *, hold_until_attached: bool = False) -> Optional[QueuedRunMessage]:
        """Queue a note for the loop's next model call.

        A run whose loop is not attached refuses the note, unless the caller knows the task is active and its loop is about to attach (it is still being set up, or is picking up after a resume). Then the note is held, attach() leaves the queue alone, and the first model call delivers it.
        """
        with self._lock:
            if not self._attached and not hold_until_attached:
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

# Tasks whose agent loop has finished. The task is still "processing" while the final summary is streamed and the result is saved, but nothing reads notes any more, so a note sent then must not be held. The mark is cleared when the same task starts a loop again (a resume, or an answer to a question). Only the most recent ones are remembered, so the table cannot grow without bound.
MAX_ENDED_RUNS_REMEMBERED = 256
_ended_runs: "OrderedDict[str, None]" = OrderedDict()


def mark_run_ended(agent_task_id: str) -> None:
    with _controls_lock:
        _ended_runs.pop(agent_task_id, None)
        _ended_runs[agent_task_id] = None
        while len(_ended_runs) > MAX_ENDED_RUNS_REMEMBERED:
            _ended_runs.popitem(last=False)


def clear_run_ended(agent_task_id: str) -> None:
    with _controls_lock:
        _ended_runs.pop(agent_task_id, None)


def run_has_ended(agent_task_id: str) -> bool:
    with _controls_lock:
        return agent_task_id in _ended_runs


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
