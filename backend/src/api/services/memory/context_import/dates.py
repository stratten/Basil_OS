"""Deterministic date reading for imported context. Nothing here guesses: a value that is not clearly a date yields None."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional, Tuple

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))

_ISO = re.compile(r"^\W{0,3}(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ](\d{1,2}):(\d{2})(?::(\d{2}))?)?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_MONTH_FIRST = re.compile(rf"^\W{{0,3}}({_MONTH_NAMES})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})", re.IGNORECASE)
_DAY_FIRST = re.compile(rf"^\W{{0,3}}(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_NAMES})\.?,?\s+(\d{{4}})", re.IGNORECASE)
_MONTH_YEAR = re.compile(rf"^\W{{0,3}}({_MONTH_NAMES})\.?,?\s+(\d{{4}})\b", re.IGNORECASE)
_US_SLASH = re.compile(r"^\W{0,3}(\d{1,2})/(\d{1,2})/(\d{4})\b")


def _utc_iso(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> Optional[str]:
    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def read_leading_date(text: str) -> Tuple[Optional[str], str]:
    """Read a date at the very start of *text*. Returns (ISO timestamp or None, the text after the date)."""
    candidate = text.lstrip()
    match = _ISO.match(candidate)
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        hour = int(match.group(4)) if match.group(4) else 0
        minute = int(match.group(5)) if match.group(5) else 0
        second = int(match.group(6)) if match.group(6) else 0
        iso = _utc_iso(year, month, day, hour, minute, second)
        if iso:
            return iso, _strip_separator(candidate[match.end():])
    match = _MONTH_FIRST.match(candidate)
    if match:
        iso = _utc_iso(int(match.group(3)), _MONTHS[match.group(1).lower()], int(match.group(2)))
        if iso:
            return iso, _strip_separator(candidate[match.end():])
    match = _DAY_FIRST.match(candidate)
    if match:
        iso = _utc_iso(int(match.group(3)), _MONTHS[match.group(2).lower()], int(match.group(1)))
        if iso:
            return iso, _strip_separator(candidate[match.end():])
    match = _US_SLASH.match(candidate)
    if match:
        iso = _utc_iso(int(match.group(3)), int(match.group(1)), int(match.group(2)))
        if iso:
            return iso, _strip_separator(candidate[match.end():])
    match = _MONTH_YEAR.match(candidate)
    if match:
        iso = _utc_iso(int(match.group(2)), _MONTHS[match.group(1).lower()], 1)
        if iso:
            return iso, _strip_separator(candidate[match.end():])
    return None, text


def read_date_value(value: object) -> Optional[str]:
    """Read a whole field as a date. Numbers are never treated as dates, so an id column cannot become one."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    iso, remainder = read_leading_date(candidate)
    if iso is None or remainder.strip():
        return None
    return iso


def _strip_separator(remainder: str) -> str:
    return re.sub(r"^[\s:\-\u2013\u2014.,)\]]+", "", remainder).strip()
