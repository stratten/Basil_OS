"""The conversation window shown to the model: rolling summary plus the recent verbatim transcript."""

from __future__ import annotations

import re
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


SINGLE_SOURCE_SPEAKER = "Speaker"
SINGLE_SOURCE_NOTE = (
    "(Basil note, not part of the meeting: one microphone recorded these lines, so they are not attributed to people and several people may be talking, the user among them. "
    "Work out the turn changes from how the conversation reads: a question followed by a reply, short acknowledgments such as \"yeah\" or \"right\", a change in who is being addressed, a change of viewpoint, and pauses between lines. "
    "Treat the lines as a dialogue, not as one person's monologue, and never assume the user said a particular line.)"
)
_DIARIZED_SPEAKER = re.compile(r"^Speaker \d+$")


def is_single_source(turns: Sequence[CompanionTurn]) -> bool:
    """True when every turn came from the microphone, as in an in-person meeting where the room is the only audio source."""
    return bool(turns) and all(turn.role == "self" for turn in turns)


def speaker_label(turn: CompanionTurn, single_source: bool = False) -> str:
    if turn.role == "self":
        if single_source:
            return turn.speaker if _DIARIZED_SPEAKER.match(turn.speaker or "") else SINGLE_SOURCE_SPEAKER
        return "You"
    return turn.speaker or "Other"


def format_turn_line(turn: CompanionTurn, single_source: bool = False) -> str:
    text = turn.text if len(turn.text) <= MAX_TURN_CHARS else turn.text[: MAX_TURN_CHARS - 1].rstrip() + "…"
    return f"[{turn.id} @ {clock_label(turn.start)}] {speaker_label(turn, single_source)}: {text}"


def format_transcript(turns: Sequence[CompanionTurn], max_chars: int = 6000) -> str:
    """Newest turns that fit in ``max_chars``, oldest first. A window drawn only from the microphone is labeled "Speaker" and led by ``SINGLE_SOURCE_NOTE``, which sits outside the ``max_chars`` budget."""
    single_source = is_single_source(turns)
    lines: List[str] = []
    used = 0
    for turn in reversed(turns):
        line = format_turn_line(turn, single_source)
        if lines and used + len(line) + 1 > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
    rendered = "\n".join(reversed(lines))
    return f"{SINGLE_SOURCE_NOTE}\n{rendered}" if single_source and rendered else rendered
