"""Exclusion windows: daily time ranges in which a recurring schedule must not start a run.

This module has no dependencies on any other component module, so ``schedule_time_math`` can import it without an import cycle.
A window is a start and an end wall-clock time in the schedule's own timezone, optionally limited to the weekdays on which it starts (Monday is 0).
An end that is not after the start crosses midnight, and an end equal to the start covers a full 24 hours.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

MAX_EXCLUSION_WINDOWS = 8
_MINUTES_PER_DAY = 24 * 60


@dataclass(frozen=True)
class ExclusionWindow:
    """One excluded range, as minutes after local midnight plus the weekdays on which it starts (empty means every day)."""

    start_minute: int
    end_minute: int
    days: Tuple[int, ...]

    @property
    def duration_minutes(self) -> int:
        span = (self.end_minute - self.start_minute) % _MINUTES_PER_DAY
        return span or _MINUTES_PER_DAY


def _parse_clock(value: Any, label: str) -> int:
    parts = str(value or "").strip().split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError(f"The exclusion window {label} time must look like 22:00.")
    hour, minute = int(parts[0]), int(parts[1])
    if hour > 23 or minute > 59:
        raise ValueError(f"The exclusion window {label} time must be between 00:00 and 23:59.")
    return hour * 60 + minute


def _format_clock(total_minutes: int) -> str:
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def _parse_days(raw: Any) -> Tuple[int, ...]:
    if raw is None:
        return ()
    message = "The exclusion window days must be a list of weekday numbers from 0 (Monday) to 6 (Sunday)."
    if not isinstance(raw, list):
        raise ValueError(message)
    days = set()
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 6:
            raise ValueError(message)
        days.add(item)
    return tuple(sorted(days))


def normalize_exclusion_windows(raw: Any) -> List[Dict[str, Any]]:
    """Validate windows from an API caller and return them in canonical form; raises ValueError with a plain message."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("exclusion_windows must be a list.")
    if len(raw) > MAX_EXCLUSION_WINDOWS:
        raise ValueError(f"A schedule can have at most {MAX_EXCLUSION_WINDOWS} exclusion windows.")
    parsed: List[ExclusionWindow] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Each exclusion window must have a start and an end.")
        parsed.append(
            ExclusionWindow(
                _parse_clock(item.get("start"), "start"),
                _parse_clock(item.get("end"), "end"),
                _parse_days(item.get("days")),
            )
        )
    canonical: List[Dict[str, Any]] = []
    for window in sorted(set(parsed), key=lambda w: (w.start_minute, w.end_minute, w.days)):
        entry: Dict[str, Any] = {"start": _format_clock(window.start_minute), "end": _format_clock(window.end_minute)}
        if window.days:
            entry["days"] = list(window.days)
        canonical.append(entry)
    return canonical


def parse_exclusion_windows(raw: Any) -> List[ExclusionWindow]:
    """Lenient reader for stored values: unusable windows are ignored so a bad row never stops a schedule from running."""
    try:
        normalized = normalize_exclusion_windows(raw)
    except ValueError as error:
        logger.warning("Ignoring unusable exclusion windows: %s", error)
        return []
    return [
        ExclusionWindow(
            _parse_clock(entry["start"], "start"),
            _parse_clock(entry["end"], "end"),
            tuple(entry.get("days", ())),
        )
        for entry in normalized
    ]


def _covering_end(moment: datetime, windows: Sequence[ExclusionWindow]) -> Optional[datetime]:
    """The latest end among windows that cover ``moment``, or None when none does.

    A window lasts at most 24 hours, so only a window that started today or yesterday can cover the moment.
    The start and end are built with the moment's own tzinfo, so the arithmetic is wall-clock arithmetic.
    """
    latest_end: Optional[datetime] = None
    for window in windows:
        for day_offset in (0, -1):
            day = moment.date() + timedelta(days=day_offset)
            if window.days and day.weekday() not in window.days:
                continue
            start = datetime.combine(day, time(window.start_minute // 60, window.start_minute % 60), tzinfo=moment.tzinfo)
            end = start + timedelta(minutes=window.duration_minutes)
            if start <= moment < end and (latest_end is None or end > latest_end):
                latest_end = end
    return latest_end


def shift_out_of_windows(moment: datetime, windows: Sequence[ExclusionWindow]) -> datetime:
    """The earliest instant at or after ``moment`` that no window covers; ``moment`` itself when it is already allowed.

    Windows can chain (22:00-07:00 followed by 07:00-08:00), so the shift repeats until nothing covers the result.
    If windows still cover the result after the bounded number of passes (together they leave no gap), the last shifted value is returned and the caller treats an unchanged-versus-changed comparison as "still excluded".
    """
    current = moment
    for _ in range(len(windows) * 2 + 2):
        end = _covering_end(current, windows)
        if end is None:
            return current
        current = end
    return current
