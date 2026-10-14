"""Assembles the recorder's incremental fragments into utterances on the meeting timeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .models import CompanionTurn, TurnRole
from .similarity import normalize_text, tokens

_SENTENCE_END = re.compile(r"[.?!]['\")\]]*$")


def speaker_label(raw: Any) -> Optional[str]:
    """Normalize a recorder segment's ``speaker`` to a display label, or ``None`` when the speaker is unknown.

    Recorder segments carry a string label, ``None``, or a numeric diarization id where a negative id (``-1``) means no speaker was identified.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return f"Speaker {int(raw) + 1}" if raw >= 0 else None
    label = str(raw).strip()
    return label or None


class SessionClock:
    """Maps each member recording's segment times onto one shared session origin.

    Mirrors ``MeetingAnalyzer._gather_session_members``: the earliest registered start becomes the origin and later members get a non-negative offset.
    """

    def __init__(self) -> None:
        self._origin_epoch: Optional[float] = None
        self._offsets: Dict[str, float] = {}

    def register_member(self, meeting_id: str, start_epoch: Optional[float]) -> float:
        """Register a member once and return its offset; repeat calls return the stored offset."""
        if meeting_id in self._offsets:
            return self._offsets[meeting_id]
        if start_epoch is None:
            offset = 0.0
        else:
            if self._origin_epoch is None:
                self._origin_epoch = start_epoch
            offset = round(max(0.0, start_epoch - self._origin_epoch), 3)
        self._offsets[meeting_id] = offset
        return offset

    def offset_for(self, meeting_id: str) -> float:
        return self._offsets.get(meeting_id, 0.0)

    def to_meeting_time(self, meeting_id: str, segment_time: float) -> float:
        return segment_time + self.offset_for(meeting_id)


@dataclass
class _PendingUtterance:
    start: float
    end: float
    text: str
    speaker: str
    last_wall: float


class UtteranceAssembler:
    """Joins consecutive fragments from one audio source into utterances.

    An utterance ends at sentence-final punctuation (once it has enough words), after a silence gap, on a speaker change, at a length cap, or after the source has been idle on the wall clock. Time arguments are injected so the behavior is deterministic in tests and in replay.
    """

    def __init__(
        self,
        *,
        source_meeting_id: str,
        role: TurnRole,
        default_speaker: str,
        id_prefix: str,
        max_gap_seconds: float = 1.4,
        max_chars: int = 420,
        max_span_seconds: float = 25.0,
        idle_seconds: float = 1.6,
        min_sentence_words: int = 3,
    ) -> None:
        self.source_meeting_id = source_meeting_id
        self.role: TurnRole = role
        self.default_speaker = default_speaker
        self.id_prefix = id_prefix
        self.max_gap_seconds = max_gap_seconds
        self.max_chars = max_chars
        self.max_span_seconds = max_span_seconds
        self.idle_seconds = idle_seconds
        self.min_sentence_words = min_sentence_words
        self._pending: Optional[_PendingUtterance] = None
        self._sequence = 0

    def add_fragment(
        self,
        *,
        start: float,
        end: float,
        text: str,
        speaker: Any,
        now_wall: float,
    ) -> List[CompanionTurn]:
        """Add one fragment (times already on the meeting timeline) and return any utterances it completed."""
        finished: List[CompanionTurn] = []
        if not text or not text.strip():
            return finished
        label = speaker_label(speaker) or self.default_speaker
        pending = self._pending
        if pending is not None and (start - pending.end > self.max_gap_seconds or label != pending.speaker):
            finished.append(self._finalize())
            pending = None
        if pending is None:
            self._pending = _PendingUtterance(start=start, end=max(start, end), text=text, speaker=label, last_wall=now_wall)
        else:
            pending.text += text
            pending.end = max(pending.end, end)
            pending.last_wall = now_wall
        current = self._pending
        assert current is not None
        normalized = normalize_text(current.text)
        if len(normalized) >= self.max_chars or current.end - current.start >= self.max_span_seconds:
            finished.append(self._finalize())
        elif _SENTENCE_END.search(normalized) and len(tokens(normalized)) >= self.min_sentence_words:
            finished.append(self._finalize())
        return finished

    def flush_idle(self, now_wall: float) -> List[CompanionTurn]:
        """Finalize the pending utterance when the source has produced nothing for ``idle_seconds``."""
        pending = self._pending
        if pending is not None and now_wall - pending.last_wall >= self.idle_seconds:
            return [self._finalize()]
        return []

    def flush_all(self) -> List[CompanionTurn]:
        """Finalize whatever is pending (end of recording)."""
        if self._pending is None:
            return []
        return [self._finalize()]

    def _finalize(self) -> CompanionTurn:
        pending = self._pending
        assert pending is not None
        self._pending = None
        self._sequence += 1
        return CompanionTurn(
            id=f"{self.id_prefix}{self._sequence:05d}",
            source_meeting_id=self.source_meeting_id,
            role=self.role,
            speaker=pending.speaker,
            start=pending.start,
            end=pending.end,
            text=normalize_text(pending.text),
        )
