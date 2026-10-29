"""Meeting-clock <-> audio-file-clock mapping for compacted meeting recordings.

A meeting's ``audio.wav`` is compacted: capture gaps (a paused stream, a device outage, a reconnect) are not written, so file time runs behind the recording clock after the first gap. Every transcript, window request, and UI timestamp is on the recording (meeting) clock. ``metadata.stream_timeline_ranges`` records, for each captured stream connection and in append order, the meeting-time range its audio covers; the WAV is the concatenation of those ranges. This module converts between the two clocks.

Ranges already include the recording part's resume offset (the recorder adds it when it sets each range origin), so a ranges-based timeline needs no extra offset. Recordings without usable ranges are "legacy": a single open-ended piece mapping file time to ``file + legacy_offset_seconds``.

Everything here is pure so it can be unit tested without a recorder or audio file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

_EPSILON = 1e-6


@dataclass(frozen=True)
class TimelinePiece:
    """One contiguous run of file audio and the meeting time it starts at."""

    file_start: float
    file_end: float
    meeting_start: float

    @property
    def meeting_end(self) -> float:
        return self.meeting_start + (self.file_end - self.file_start)


def _valid_range_pairs(ranges: Optional[Iterable[Any]]) -> List[Tuple[float, float]]:
    pairs: List[Tuple[float, float]] = []
    for item in ranges or []:
        if not isinstance(item, dict):
            continue
        start = item.get("start")
        end = item.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            continue
        if not math.isfinite(start) or not math.isfinite(end):
            continue
        pairs.append((float(start), float(end)))
    return pairs


class MeetingTimeline:
    """Converts between meeting-clock seconds and compacted-file seconds."""

    def __init__(self, pieces: List[TimelinePiece], *, is_legacy: bool) -> None:
        self.pieces = pieces
        self.is_legacy = is_legacy

    @classmethod
    def from_ranges(
        cls,
        ranges: Optional[Iterable[Any]],
        *,
        live: bool = False,
        legacy_offset_seconds: float = 0.0,
    ) -> "MeetingTimeline":
        """Build a timeline from ``stream_timeline_ranges``.

        Zero-length ranges (a connection that wrote no audio) are skipped. When ``live`` is true the final range is the one still being written, so it is open-ended regardless of its stored end. With no usable range, the result is a legacy single-piece timeline.
        """
        pairs = _valid_range_pairs(ranges)
        pieces: List[TimelinePiece] = []
        cumulative = 0.0
        for index, (start, end) in enumerate(pairs):
            is_last = index == len(pairs) - 1
            if live and is_last:
                pieces.append(TimelinePiece(cumulative, math.inf, start))
                break
            length = end - start
            if length <= _EPSILON:
                continue
            pieces.append(TimelinePiece(cumulative, cumulative + length, start))
            cumulative += length
        if not pieces:
            return cls(
                [TimelinePiece(0.0, math.inf, float(legacy_offset_seconds))],
                is_legacy=True,
            )
        return cls(pieces, is_legacy=False)

    def meeting_to_file_pieces(
        self, start_seconds: float, end_seconds: float
    ) -> List[Tuple[float, float, float]]:
        """Split a meeting-time window into ``(file_start, file_end, meeting_start)`` runs.

        A window that spans a capture gap yields one run per captured piece; a window entirely inside a gap yields none.
        """
        runs: List[Tuple[float, float, float]] = []
        for piece in self.pieces:
            overlap_start = max(start_seconds, piece.meeting_start)
            overlap_end = min(end_seconds, piece.meeting_end)
            if overlap_end - overlap_start <= _EPSILON:
                continue
            file_start = piece.file_start + (overlap_start - piece.meeting_start)
            file_end = piece.file_start + (overlap_end - piece.meeting_start)
            runs.append((file_start, file_end, overlap_start))
        return runs

    def _piece_index_for_file_time(self, file_seconds: float) -> int:
        for index, piece in enumerate(self.pieces):
            if piece.file_start - _EPSILON <= file_seconds < piece.file_end - _EPSILON:
                return index
        return len(self.pieces) - 1 if file_seconds >= self.pieces[0].file_start else 0

    def file_to_meeting(self, file_seconds: float) -> float:
        """Meeting-clock time of a point in the compacted file."""
        piece = self.pieces[self._piece_index_for_file_time(file_seconds)]
        return piece.meeting_start + (file_seconds - piece.file_start)

    def map_file_segments(self, segments: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return copies of file-time segments re-timed onto the meeting clock.

        A segment that ends in a later piece than it starts in (it spans a capture gap) is ended where its start piece ends, so it never claims time the recording did not capture.
        """
        mapped: List[Dict[str, Any]] = []
        for segment in segments:
            start = segment.get("start")
            end = segment.get("end")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                mapped.append(dict(segment))
                continue
            start_index = self._piece_index_for_file_time(start)
            end_index = self._piece_index_for_file_time(max(start, end - _EPSILON))
            start_piece = self.pieces[start_index]
            new_start = start_piece.meeting_start + (start - start_piece.file_start)
            if end_index == start_index:
                new_end = start_piece.meeting_start + (end - start_piece.file_start)
            else:
                new_end = start_piece.meeting_end
            shifted = dict(segment)
            shifted["start"] = new_start
            shifted["end"] = max(new_start, new_end)
            mapped.append(shifted)
        return mapped
