"""The one pure reducer from persisted timeline events to renderable Companion state.

The TypeScript store in the MeetingAssistant web component reimplements this reducer; ``timeline_parity.json`` in the backend test fixtures is the shared proof that both produce the same state.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field, ValidationError

from .models import (
    ChatMessage,
    CompanionItem,
    CompanionRoot,
    CompanionSettings,
    CompanionSnapshot,
    CompanionStatus,
    CompanionWatch,
    TimelineEvent,
)

MAX_DERIVED_RETRIEVALS = 200


class DerivedState(BaseModel):
    """Everything the UI renders, computed only from timeline events."""

    items: List[CompanionItem] = Field(default_factory=list)
    roots: List[CompanionRoot] = Field(default_factory=list)
    watches: List[CompanionWatch] = Field(default_factory=list)
    chat: List[ChatMessage] = Field(default_factory=list)
    retrievals: List[TimelineEvent] = Field(default_factory=list)
    status: Optional[Dict[str, Any]] = None
    last_error: Optional[Dict[str, Any]] = None
    last_seq: int = 0


class _Accumulator:
    def __init__(self) -> None:
        self.items: Dict[str, CompanionItem] = {}
        self.roots: Dict[str, CompanionRoot] = {}
        self.watches: Dict[str, CompanionWatch] = {}
        self.chat: Dict[str, ChatMessage] = {}
        self.retrievals: List[TimelineEvent] = []
        self.status: Optional[Dict[str, Any]] = None
        self.last_error: Optional[Dict[str, Any]] = None
        self.last_seq = 0

    def apply(self, event: TimelineEvent) -> None:
        self.last_seq = max(self.last_seq, event.seq)
        payload = event.payload
        if event.kind == "item":
            item = CompanionItem.model_validate(payload["item"])
            if item.id not in self.items:
                self.items[item.id] = item
        elif event.kind == "retrieval":
            self.retrievals.append(event)
            if len(self.retrievals) > MAX_DERIVED_RETRIEVALS:
                del self.retrievals[: len(self.retrievals) - MAX_DERIVED_RETRIEVALS]
        elif event.kind == "feedback":
            self._apply_feedback(str(payload["item_id"]), str(payload["action"]))
        elif event.kind == "chat":
            message_id = str(payload["message_id"])
            self.chat[message_id] = ChatMessage(
                id=message_id,
                role=payload["role"],
                text=str(payload["text"]),
                meeting_time=event.meeting_time,
                truncated=bool(payload.get("truncated", False)),
                status=payload.get("status", "complete"),
            )
        elif event.kind == "watch":
            self._apply_watch(event)
        elif event.kind == "source":
            self._apply_source(event)
        elif event.kind == "status":
            self.status = dict(payload)
        elif event.kind == "error":
            self.last_error = {"code": str(payload["code"]), "message": str(payload["message"])}

    def _apply_feedback(self, item_id: str, action: str) -> None:
        item = self.items.get(item_id)
        if item is None:
            return
        if action == "dismissed":
            self.items[item_id] = item.model_copy(update={"dismissed": True, "pinned": False})
        elif action == "pinned":
            self.items[item_id] = item.model_copy(update={"pinned": True, "dismissed": False})
        elif action == "unpinned":
            self.items[item_id] = item.model_copy(update={"pinned": False})

    def _apply_watch(self, event: TimelineEvent) -> None:
        payload = event.payload
        watch_id = str(payload["watch_id"])
        state = payload["state"]
        if state == "created":
            self.watches[watch_id] = CompanionWatch(
                id=watch_id,
                topic=str(payload["topic"]),
                instruction=str(payload["instruction"]),
                keywords=[str(keyword) for keyword in payload.get("keywords", [])],
                created_at=event.meeting_time,
            )
            return
        watch = self.watches.get(watch_id)
        if watch is None:
            return
        if state == "triggered":
            self.watches[watch_id] = watch.model_copy(update={"last_triggered_at": event.meeting_time})
        elif state == "cancelled":
            self.watches[watch_id] = watch.model_copy(update={"active": False})

    def _apply_source(self, event: TimelineEvent) -> None:
        payload = event.payload
        root_id = str(payload["root_id"])
        state = payload["state"]
        if state == "attached":
            self.roots[root_id] = CompanionRoot(
                id=root_id,
                path=str(payload["path"]),
                display_name=str(payload["display_name"]),
                kind=payload["kind"],
                attached_at=event.meeting_time,
            )
        elif state == "detached":
            self.roots.pop(root_id, None)


def reduce_timeline(events: Iterable[TimelineEvent]) -> DerivedState:
    """Fold events (in ``seq`` order) into derived state, skipping malformed payloads."""
    accumulator = _Accumulator()
    for event in events:
        try:
            accumulator.apply(event)
        except (ValidationError, KeyError, TypeError, ValueError):
            accumulator.last_seq = max(accumulator.last_seq, event.seq)
            continue
    return DerivedState(
        items=list(accumulator.items.values()),
        roots=list(accumulator.roots.values()),
        watches=list(accumulator.watches.values()),
        chat=list(accumulator.chat.values()),
        retrievals=list(accumulator.retrievals),
        status=accumulator.status,
        last_error=accumulator.last_error,
        last_seq=accumulator.last_seq,
    )


def stored_status(derived: DerivedState, settings: CompanionSettings) -> CompanionStatus:
    """Status for a meeting that is not live, from the last persisted status event and the saved settings."""
    status = derived.status or {}
    return CompanionStatus(
        live=False,
        enabled=bool(status.get("enabled", settings.enabled)),
        mode=status.get("mode", settings.mode),
        model_id=status.get("model_id", settings.model_id),
        focus=status.get("focus", settings.focus),
        capacity="ok",
        capacity_reason=None,
    )


def build_snapshot(
    *,
    meeting_id: str,
    session_key: str,
    status: CompanionStatus,
    derived: DerivedState,
) -> CompanionSnapshot:
    """Assemble the client snapshot from a status and derived state."""
    return CompanionSnapshot(
        meeting_id=meeting_id,
        session_key=session_key,
        status=status,
        roots=derived.roots,
        items=derived.items,
        watches=derived.watches,
        chat=derived.chat,
        retrievals=derived.retrievals,
        last_seq=derived.last_seq,
    )
