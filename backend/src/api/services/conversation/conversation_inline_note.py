"""Separates the answering model's inline recap from the reply the user sees."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .conversation_summary_contract import (
    SUMMARY_FORMAT_VERSION,
    TurnSummaryRecord,
    TurnSummaryStatus,
    exchange_fingerprint,
)
from .conversation_turn_summarizer import TURN_SUMMARY_MAX_CHARS, clean_summary_output

NOTE_OPEN = "<basil_note>"
NOTE_CLOSE = "</basil_note>"
THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"
REASONING_NOTE_TERM = "basil_note"
REASONING_NOTE_TERM_REPLACEMENT = "recap"
INLINE_NOTE_INSTRUCTION = "Recap (from Basil, not written by the user): after your complete reply, add one final line in exactly this form: <basil_note>One to three sentences, under 90 words, recapping what the user asked and what you answered, keeping concrete facts, decisions, names, numbers, file paths, and open questions.</basil_note> Basil removes this recap before the user sees your reply, so never mention it, never place it anywhere except at the very end, and write nothing after it."
INLINE_NOTE_REMINDER = "(Reminder from Basil, not written by the user: end your reply with the basil_note recap line described in the system message.)"

_NORMAL = "normal"
_THINK = "think"
_NOTE = "note"


@dataclass(frozen=True)
class InlineNoteOutcome:
    """Visible text still held at the end of the stream, plus the captured note."""

    visible_tail: str
    note: Optional[str]


@dataclass(frozen=True)
class InlineNoteSplit:
    """A complete response separated into the visible reply and the note."""

    reply: str
    note: Optional[str]


def _held_suffix_length(text: str, markers: Tuple[str, ...]) -> int:
    longest = 0
    for marker in markers:
        for length in range(min(len(marker) - 1, len(text)), 0, -1):
            if text.endswith(marker[:length]):
                longest = max(longest, length)
                break
    return longest


class InlineNoteStreamFilter:
    """Passes reply and reasoning text through and withholds a note that starts outside reasoning blocks."""

    def __init__(self) -> None:
        self._state = _NORMAL
        self._buffer = ""
        self._note_raw = ""
        self._emitted_answer_text = False

    def feed(self, token: str) -> str:
        if not token:
            return ""
        if self._state == _NOTE:
            self._note_raw += token
            return ""
        self._buffer += token
        emitted: List[str] = []
        while self._buffer:
            if self._state == _NOTE:
                self._note_raw += self._buffer
                self._buffer = ""
                break
            markers = (THINK_CLOSE,) if self._state == _THINK else (THINK_OPEN, NOTE_OPEN)
            hit = self._earliest(markers)
            if hit is None:
                held_markers = (*markers, REASONING_NOTE_TERM) if self._state == _THINK else markers
                held = _held_suffix_length(self._buffer, held_markers)
                ready = self._buffer[: len(self._buffer) - held]
                self._buffer = self._buffer[len(self._buffer) - held:]
                self._emit(ready, emitted)
                break
            index, marker = hit
            self._emit(self._buffer[:index], emitted)
            self._buffer = self._buffer[index + len(marker):]
            if marker == NOTE_OPEN:
                self._state = _NOTE
                continue
            emitted.append(marker)
            self._state = _THINK if marker == THINK_OPEN else _NORMAL
        return "".join(emitted)

    def finish(self) -> InlineNoteOutcome:
        if self._state != _NOTE:
            tail = self._buffer
            self._buffer = ""
            if self._state == _THINK:
                tail = tail.replace(REASONING_NOTE_TERM, REASONING_NOTE_TERM_REPLACEMENT)
            return InlineNoteOutcome(visible_tail=tail, note=None)
        raw = self._note_raw
        self._note_raw = ""
        if not self._emitted_answer_text:
            return InlineNoteOutcome(visible_tail=raw.replace(NOTE_CLOSE, "").strip(), note=None)
        close_index = raw.find(NOTE_CLOSE)
        if close_index < 0:
            return InlineNoteOutcome(visible_tail="", note=None)
        try:
            note = clean_summary_output(raw[:close_index], TURN_SUMMARY_MAX_CHARS)
        except ValueError:
            note = None
        return InlineNoteOutcome(visible_tail="", note=note)

    def _earliest(self, markers: Tuple[str, ...]) -> Optional[Tuple[int, str]]:
        best: Optional[Tuple[int, str]] = None
        for marker in markers:
            index = self._buffer.find(marker)
            if index >= 0 and (best is None or index < best[0]):
                best = (index, marker)
        return best

    def _emit(self, text: str, emitted: List[str]) -> None:
        if not text:
            return
        if self._state == _THINK:
            text = text.replace(REASONING_NOTE_TERM, REASONING_NOTE_TERM_REPLACEMENT)
        if self._state == _NORMAL and text.strip():
            self._emitted_answer_text = True
        emitted.append(text)


def append_inline_note_reminder(content: Any) -> Any:
    """Small models follow the note instruction far more reliably when it also appears at the end of the prompt."""
    if isinstance(content, str):
        return f"{content}\n\n{INLINE_NOTE_REMINDER}"
    if isinstance(content, list):
        return [*content, {"type": "text", "text": INLINE_NOTE_REMINDER}]
    return content


def split_inline_note(text: str) -> InlineNoteSplit:
    """Separate a complete, non-streamed response into its visible reply and note."""
    note_filter = InlineNoteStreamFilter()
    visible = note_filter.feed(text)
    outcome = note_filter.finish()
    return InlineNoteSplit(reply=(visible + outcome.visible_tail).rstrip(), note=outcome.note)


def build_inline_turn_summary(
    note: Optional[str],
    *,
    user_text: str,
    reply_text: str,
    model_id: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Turn a captured note into the stored turn_summary metadata for the reply it describes."""
    if note is None or not reply_text.strip():
        return None
    record = TurnSummaryRecord(
        status=TurnSummaryStatus.COMPLETED,
        text=note,
        source_fingerprint=exchange_fingerprint(user_text, reply_text),
        model_id=model_id,
        attempt_count=1,
        version=SUMMARY_FORMAT_VERSION,
    )
    return record.to_metadata()
