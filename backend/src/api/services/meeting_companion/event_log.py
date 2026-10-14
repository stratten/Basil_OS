"""Append-only timeline log with debounced atomic persistence and subscriber fan-out."""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from api.core.utc_time import utc_now_naive_iso_z

from .models import CompanionSettings, TimelineEvent, TimelineKind
from .store import CompanionDocument, CompanionStore
from .timeline import DerivedState, reduce_timeline

logger = logging.getLogger(__name__)

Subscriber = Callable[[TimelineEvent], None]


class CompanionEventLog:
    def __init__(
        self,
        *,
        session_key: str,
        resolve_directory: Callable[[], Path],
        settings_provider: Callable[[], CompanionSettings],
        wall_clock: Callable[[], str] = utc_now_naive_iso_z,
        flush_interval_seconds: float = 2.0,
        max_events: int = 20000,
    ) -> None:
        self.session_key = session_key
        self._resolve_directory = resolve_directory
        self._settings_provider = settings_provider
        self._wall_clock = wall_clock
        self._flush_interval_seconds = flush_interval_seconds
        self._max_events = max_events
        self._lock = threading.RLock()
        self._flush_lock = threading.Lock()
        self._events: List[TimelineEvent] = []
        self._seq = 0
        self._subscribers: List[Subscriber] = []
        self._dirty = False
        self._last_flush_monotonic: Optional[float] = None
        self._last_directory: Optional[Path] = None
        self._discarded = False

    def load_existing(self, search_directories: Sequence[Path]) -> Optional[CompanionSettings]:
        """Load the first ``companion.json`` found in ``search_directories`` (anchor first); return its saved settings."""
        for directory in search_directories:
            document = CompanionStore(directory).load()
            if document is None:
                continue
            with self._lock:
                self._events = sorted(document.events, key=lambda event: event.seq)
                self._seq = max((event.seq for event in self._events), default=0)
                self._dirty = False
            self._last_directory = directory
            return document.settings
        return None

    def subscribe(self, callback: Subscriber) -> None:
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: Subscriber) -> None:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def append(self, kind: TimelineKind, meeting_time: float, payload: Dict[str, Any]) -> TimelineEvent:
        """Record one event. ``payload`` must be JSON-serializable (use ``model_dump(mode="json")``)."""
        with self._lock:
            self._seq += 1
            event = TimelineEvent(
                id=f"ev-{uuid.uuid4().hex[:12]}",
                seq=self._seq,
                kind=kind,
                meeting_time=round(max(0.0, float(meeting_time)), 3),
                wall_time=self._wall_clock(),
                payload=payload,
            )
            self._events.append(event)
            self._trim_locked()
            self._dirty = True
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception as error:
                logger.error("Companion event subscriber failed: %s", error, exc_info=True)
        return event

    def events(self) -> List[TimelineEvent]:
        with self._lock:
            return list(self._events)

    def events_since(self, seq: int) -> List[TimelineEvent]:
        with self._lock:
            return [event for event in self._events if event.seq > seq]

    def derived(self) -> DerivedState:
        return reduce_timeline(self.events())

    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def is_dirty(self) -> bool:
        with self._lock:
            return self._dirty and not self._discarded

    def mark_dirty(self) -> None:
        """Request a flush without appending an event (used when only settings changed)."""
        with self._lock:
            self._dirty = True

    def discard(self) -> None:
        """Stop all future writes (the recording part was canceled and its directory deleted)."""
        with self._lock:
            self._discarded = True
            self._dirty = False

    def flush_if_due(self, now_monotonic: float) -> bool:
        with self._lock:
            if not self._dirty or self._discarded:
                return False
            last = self._last_flush_monotonic
        if last is not None and now_monotonic - last < self._flush_interval_seconds:
            return False
        written = self.flush()
        if written:
            self._last_flush_monotonic = now_monotonic
        return written

    def flush(self) -> bool:
        """Write ``companion.json`` now if there is anything unsaved; return whether a file was written."""
        with self._flush_lock:
            with self._lock:
                if self._discarded or not self._dirty:
                    return False
                document = CompanionDocument(
                    session_key=self.session_key,
                    settings=self._settings_provider(),
                    events=list(self._events),
                    saved_at=self._wall_clock(),
                )
                self._dirty = False
            directory = self._resolve_directory()
            try:
                CompanionStore(directory).save(document)
            except OSError as error:
                logger.error("Could not save Companion data to %s: %s", directory, error, exc_info=True)
                with self._lock:
                    self._dirty = True
                return False
            previous = self._last_directory
            if previous is not None and previous != directory:
                CompanionStore(previous).remove()
            self._last_directory = directory
            return True

    def _trim_locked(self) -> None:
        excess = len(self._events) - self._max_events
        if excess <= 0:
            return
        kept: List[TimelineEvent] = []
        for event in self._events:
            if excess > 0 and event.kind == "retrieval":
                excess -= 1
                continue
            kept.append(event)
        self._events = kept
