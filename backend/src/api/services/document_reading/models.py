"""Result, limit and budget types shared by every document format reader."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, List, Optional

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_NO_TEXT = "no_text"
STATUS_ENCRYPTED = "encrypted"
STATUS_UNSUPPORTED = "unsupported"
STATUS_TOO_LARGE = "too_large"
STATUS_DEADLINE = "deadline"
STATUS_ERROR = "error"

# Statuses that describe the file itself and stay true until the file changes, so a cache may remember them.
# ``deadline`` depends on how long the caller allowed and is never remembered.
FINAL_STATUSES = frozenset(
    {STATUS_OK, STATUS_EMPTY, STATUS_NO_TEXT, STATUS_ENCRYPTED, STATUS_UNSUPPORTED, STATUS_TOO_LARGE, STATUS_ERROR}
)

AGENT_DEADLINE_SECONDS = 20.0


@dataclass(frozen=True)
class DocumentReadLimits:
    max_bytes: int = 40_000_000
    max_chars: int = 400_000
    max_pdf_pages: int = 400
    max_sheets: int = 40
    max_rows: int = 50_000
    max_slides: int = 400
    max_member_bytes: int = 64_000_000
    max_total_uncompressed_bytes: int = 192_000_000
    max_archive_members: int = 20_000


DEFAULT_LIMITS = DocumentReadLimits()
COMPANION_LIMITS = DocumentReadLimits(max_bytes=25_000_000, max_chars=300_000, max_pdf_pages=250)
AGENT_LIMITS = DocumentReadLimits(max_chars=60_000)
CONVERSATION_LIMITS = DocumentReadLimits(max_chars=150_000)


class DocumentReadError(Exception):
    """A reader could not produce text; ``status`` and ``detail`` are user-presentable."""

    def __init__(self, status: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class DocumentText:
    path: str
    kind: str
    status: str
    text: str = ""
    truncated: bool = False
    method: str = ""
    units: int = 0
    detail: str = ""

    @property
    def usable(self) -> bool:
        """True when there is text to use, including partial text from a read that hit its deadline."""
        return bool(self.text.strip())


class Deadline:
    """A wall-clock allowance that readers poll between pages, sheets and slides."""

    def __init__(self, seconds: Optional[float], clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._end = None if seconds is None else clock() + max(0.0, seconds)

    def expired(self) -> bool:
        return self._end is not None and self._clock() >= self._end


class TextAccumulator:
    """Collects text chunks up to a character budget and records whether anything was cut off."""

    def __init__(self, max_chars: int) -> None:
        self.max_chars = max_chars
        self.truncated = False
        self._parts: List[str] = []
        self._size = 0

    def add_line(self, line: str) -> bool:
        """Append ``line``; returns False once the budget is spent so callers can stop reading."""
        if self.truncated:
            return False
        clean = line.replace("\x00", "")
        cost = len(clean) + 1
        if self._size + cost > self.max_chars:
            remaining = self.max_chars - self._size
            if remaining > 0:
                self._parts.append(clean[:remaining])
                self._size += remaining
            self.truncated = True
            return False
        self._parts.append(clean)
        self._size += cost
        return True

    def text(self) -> str:
        return "\n".join(self._parts)


@dataclass
class ReadContext:
    """Mutable state passed to a format reader for one document."""

    limits: DocumentReadLimits
    accumulator: TextAccumulator
    deadline: Deadline
    method: str = ""
    detail: str = ""
    units: int = 0
    deadline_hit: bool = False

    def out_of_time(self) -> bool:
        if self.deadline.expired():
            self.deadline_hit = True
            return True
        return False

    def done(self) -> bool:
        return self.accumulator.truncated or self.deadline_hit
