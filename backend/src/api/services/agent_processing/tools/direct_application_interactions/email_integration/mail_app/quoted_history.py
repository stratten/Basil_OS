"""Separate the newest message from the quoted earlier messages in a mail body.

Mail returns ``content`` as the full text of one message, and a reply carries every earlier reply beneath it. Mail's own message view folds that history, so the agent should see the same thing by default: only what this message added, with a note saying how much earlier text was left out.
"""

from __future__ import annotations

import re
from typing import Sequence, Tuple

_ATTRIBUTION_LINE = re.compile(r"^\s*On\b.{0,300}$", re.IGNORECASE)
_ORIGINAL_MESSAGE_LINE = re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE)
_OUTLOOK_RULE_LINE = re.compile(r"^\s*_{10,}\s*$")
_HEADER_FROM_LINE = re.compile(r"^\s*From:\s*\S", re.IGNORECASE)
_HEADER_FIELD_LINE = re.compile(r"^\s*(Sent|Date|To|Subject|Cc):\s*", re.IGNORECASE)
_QUOTE_PREFIX_LINE = re.compile(r"^\s*>")

OMITTED_NOTE_TEMPLATE = "[Quoted earlier messages omitted: {count} characters. Ask for the full history only if this message depends on it.]"


def _is_attribution(lines: Sequence[str], index: int) -> bool:
    """Return whether ``lines[index]`` opens an ``On <date> <sender> wrote:`` attribution, which a mail client may wrap onto the next line."""
    line = lines[index]
    if not _ATTRIBUTION_LINE.match(line):
        return False
    if line.rstrip().endswith("wrote:"):
        return True
    return index + 1 < len(lines) and lines[index + 1].strip().endswith("wrote:") and len(lines[index + 1].strip()) < 300


def _is_outlook_header_block(lines: Sequence[str], index: int) -> bool:
    """Return whether ``lines[index]`` starts a ``From:`` header block followed by at least two more header fields."""
    if not _HEADER_FROM_LINE.match(lines[index]):
        return False
    following = [line for line in lines[index + 1 : index + 6] if line.strip()]
    return sum(1 for line in following if _HEADER_FIELD_LINE.match(line)) >= 2


def _is_quote_block(lines: Sequence[str], index: int) -> bool:
    """Return whether ``lines[index]`` begins a run of ``>`` quoted lines that continues to the end of the text."""
    if not _QUOTE_PREFIX_LINE.match(lines[index]):
        return False
    return all(_QUOTE_PREFIX_LINE.match(line) or not line.strip() for line in lines[index:])


def _quoted_history_start(lines: Sequence[str]) -> int | None:
    """Return the index of the first line of quoted history, or None when the text has none."""
    for index in range(1, len(lines)):
        if _is_attribution(lines, index) or _ORIGINAL_MESSAGE_LINE.match(lines[index]):
            return index
        if _OUTLOOK_RULE_LINE.match(lines[index]) and index + 1 < len(lines) and _is_outlook_header_block(lines, index + 1):
            return index
        if _is_outlook_header_block(lines, index) or _is_quote_block(lines, index):
            return index
    return None


def split_quoted_history(text: str) -> Tuple[str, int]:
    """Return the newest part of ``text`` and the number of characters of quoted history removed.

    A body whose first line already opens quoted history keeps everything, because the sender wrote nothing above it that could stand alone.
    """
    if not text:
        return text, 0
    lines = text.splitlines()
    start = _quoted_history_start(lines)
    if start is None:
        return text, 0
    newest = "\n".join(lines[:start]).rstrip()
    if not newest:
        return text, 0
    return newest, max(len(text) - len(newest), 0)


def fold_quoted_history(text: str) -> str:
    """Return the newest part of ``text`` followed by a one-line note when earlier messages were removed."""
    newest, omitted = split_quoted_history(text)
    if omitted <= 0:
        return text
    return f"{newest}\n\n{OMITTED_NOTE_TEMPLATE.format(count=omitted)}"
