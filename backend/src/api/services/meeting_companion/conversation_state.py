"""The conversation window shown to the model: rolling summary plus the recent verbatim transcript."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

from .models import CompanionTurn
from .similarity import normalize_text

MAX_STATE_CHARS = 1200
MAX_TURN_CHARS = 400


@dataclass
class ConversationState:
    """Model-maintained rolling summary, replaced by each evaluation response."""

    text: str = ""
    updated_at: float = 0.0

    def apply(self, text: str, meeting_time: float) -> bool:
        cleaned = normalize_text(text)[:MAX_STATE_CHARS]
        if not cleaned:
            return False
        self.text = cleaned
        self.updated_at = meeting_time
        return True


def clock_label(seconds: float) -> str:
    total = int(max(0.0, seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def speaker_label(turn: CompanionTurn) -> str:
    if turn.role == "self":
        return "You"
    return turn.speaker or "Other"


def format_turn_line(turn: CompanionTurn) -> str:
    text = turn.text if len(turn.text) <= MAX_TURN_CHARS else turn.text[: MAX_TURN_CHARS - 1].rstrip() + "…"
    return f"[{turn.id} @ {clock_label(turn.start)}] {speaker_label(turn)}: {text}"


def format_transcript(turns: Sequence[CompanionTurn], max_chars: int = 6000) -> str:
    """Newest turns that fit in ``max_chars``, oldest first."""
    lines: List[str] = []
    used = 0
    for turn in reversed(turns):
        line = format_turn_line(turn)
        if lines and used + len(line) + 1 > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(reversed(lines))
