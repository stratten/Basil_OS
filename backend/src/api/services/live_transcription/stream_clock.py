"""Map a native audio stream's sample positions onto the client's meeting-elapsed clock."""

from __future__ import annotations

import bisect
import math
from typing import List, Optional


class StreamClock:
    """Piecewise sample-to-time map built from client clock anchors.

    Each anchor pairs a session sample index with the meeting-elapsed seconds the client measured when that sample was captured. A sample is placed relative to the nearest preceding anchor, so capture-rate drift, dropped audio, and processing lag never accumulate beyond one anchor interval.
    """

    def __init__(self, sample_rate: int = 16000) -> None:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        self.sample_rate = sample_rate
        self._sample_indexes: List[int] = []
        self._elapsed_seconds: List[float] = []

    @property
    def has_anchors(self) -> bool:
        return bool(self._sample_indexes)

    def add_anchor(self, sample_index: int, elapsed_seconds: float) -> bool:
        """Record that ``sample_index`` was captured at ``elapsed_seconds``; returns False for an invalid or out-of-order anchor."""
        if isinstance(sample_index, bool) or not isinstance(sample_index, int) or sample_index < 0:
            return False
        if (
            isinstance(elapsed_seconds, bool)
            or not isinstance(elapsed_seconds, (int, float))
            or not math.isfinite(elapsed_seconds)
            or elapsed_seconds < 0.0
        ):
            return False
        if self._sample_indexes and sample_index < self._sample_indexes[-1]:
            return False
        if self._sample_indexes and sample_index == self._sample_indexes[-1]:
            self._elapsed_seconds[-1] = float(elapsed_seconds)
            return True
        self._sample_indexes.append(sample_index)
        self._elapsed_seconds.append(float(elapsed_seconds))
        return True

    def timeline_seconds_for_sample(self, sample_index: int) -> Optional[float]:
        """Meeting-elapsed seconds for a session sample index, or None before any anchor exists."""
        if not self._sample_indexes:
            return None
        position = bisect.bisect_right(self._sample_indexes, sample_index) - 1
        if position < 0:
            first_sample = self._sample_indexes[0]
            first_elapsed = self._elapsed_seconds[0]
            return max(0.0, first_elapsed - (first_sample - sample_index) / self.sample_rate)
        anchor_sample = self._sample_indexes[position]
        return self._elapsed_seconds[position] + (sample_index - anchor_sample) / self.sample_rate
