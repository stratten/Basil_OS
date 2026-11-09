"""Mechanical splitting of an import into pieces a model can read one at a time. It never interprets the text."""

from __future__ import annotations

import re
from typing import List

# About 1,500 tokens, so a chunk plus the instructions and the answer fit a small local model's context.
CHUNK_TARGET_CHARS = 6000
HEAD_HINT_CHARS = 300


def clean_text(text: str) -> str:
    """Drop NUL bytes and replacement characters, normalize line endings and trim the ends. Nothing else is changed."""
    return text.replace("\x00", "").replace("\ufffd", "").replace("\r\n", "\n").replace("\r", "\n").strip()


def first_line_hint(text: str) -> str:
    """The first line of the whole text, so a later chunk of a table can still be read against its column names."""
    first = clean_text(text).split("\n", 1)[0].strip()
    return first[:HEAD_HINT_CHARS]


def split_into_chunks(text: str, target_chars: int = CHUNK_TARGET_CHARS) -> List[str]:
    """Pack paragraphs, then lines, then words into chunks of at most about ``target_chars`` characters."""
    cleaned = clean_text(text)
    if not cleaned:
        return []
    pieces: List[str] = []
    for block in re.split(r"\n{2,}", cleaned):
        block = block.strip()
        if not block:
            continue
        if len(block) <= target_chars:
            pieces.append(block)
        else:
            pieces.extend(_split_long_block(block, target_chars))
    chunks: List[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + 2 + len(piece) > target_chars:
            chunks.append(current)
            current = piece
        else:
            current = f"{current}\n\n{piece}" if current else piece
    if current:
        chunks.append(current)
    return chunks


def _split_long_block(block: str, target_chars: int) -> List[str]:
    out: List[str] = []
    current = ""
    for line in block.split("\n"):
        while len(line) > target_chars:
            if current:
                out.append(current)
                current = ""
            cut = line.rfind(" ", 0, target_chars)
            cut = cut if cut > target_chars // 2 else target_chars
            head = line[:cut].strip()
            if head:
                out.append(head)
            line = line[cut:].strip()
        if current and len(current) + 1 + len(line) > target_chars:
            out.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        out.append(current)
    return [piece for piece in out if piece]
