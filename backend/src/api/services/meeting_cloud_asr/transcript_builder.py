"""Turns provider events into recorder segments and cumulative results-shaped frames for the live transcript."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable, Dict, List, Optional

from .models import EVENT_FINAL, EVENT_INTERIM, PCM_SAMPLE_RATE, AsrEvent

TimelineForSample = Callable[[int], Optional[float]]
AddSegment = Callable[..., None]

# The local engine labels every line with speaker 1 and the recorder stores that value; cloud lines match so downstream consumers see no difference.
LOCAL_COMPATIBLE_SPEAKER = 1


def format_clock(seconds: float) -> str:
    """HH:MM:SS exactly as the local engine formats line times."""
    return str(timedelta(seconds=int(max(0.0, seconds))))


class CloudTranscriptBuilder:
    def __init__(
        self,
        *,
        base_sample: int,
        timeline_for_sample: TimelineForSample,
        add_segment: AddSegment,
        sample_rate: int = PCM_SAMPLE_RATE,
    ) -> None:
        self._base_sample = max(0, base_sample)
        self._timeline_for_sample = timeline_for_sample
        self._add_segment = add_segment
        self._sample_rate = sample_rate
        self.lines: List[Dict[str, Any]] = []
        self.interim = ""
        self._last_end = 0.0
        self._open_line: Optional[Dict[str, Any]] = None

    def _session_seconds(self, stream_seconds: float) -> float:
        return self._base_sample / self._sample_rate + stream_seconds

    def _timeline_seconds(self, stream_seconds: float) -> float:
        sample = self._base_sample + int(stream_seconds * self._sample_rate)
        mapped = self._timeline_for_sample(sample)
        return mapped if mapped is not None else self._session_seconds(stream_seconds)

    def apply(self, event: AsrEvent) -> bool:
        """Apply one event; True when the frame the web client renders changed."""
        if event.kind == EVENT_INTERIM:
            if event.text == self.interim:
                return False
            self.interim = event.text
            return True
        if event.kind != EVENT_FINAL:
            return False
        changed = bool(self.interim)
        self.interim = ""
        if event.text:
            changed = True
            self._commit(event)
        if event.utterance_end and self._open_line is not None:
            self._open_line["line_complete"] = True
            self._open_line = None
            changed = True
        return changed

    def _commit(self, event: AsrEvent) -> None:
        start = max(event.start_seconds, self._last_end)
        end = max(event.end_seconds, start)
        self._last_end = end
        timeline_start = self._timeline_seconds(start)
        timeline_end = max(self._timeline_seconds(end), timeline_start)
        self._add_segment(
            start=timeline_start,
            end=timeline_end,
            text=event.text,
            speaker=LOCAL_COMPATIBLE_SPEAKER,
            is_interim=False,
        )
        line = self._open_line
        if line is None:
            line = {
                "speaker": LOCAL_COMPATIBLE_SPEAKER,
                "text": event.text,
                "start": format_clock(self._session_seconds(start)),
                "end": format_clock(self._session_seconds(end)),
                "line_complete": False,
                "timeline_start_seconds": timeline_start,
                "timeline_end_seconds": timeline_end,
            }
            self.lines.append(line)
            self._open_line = line
            return
        line["text"] = f"{line['text']} {event.text}"
        line["end"] = format_clock(self._session_seconds(end))
        line["timeline_end_seconds"] = timeline_end

    def front_data(self, lag_seconds: float = 0.0) -> Dict[str, Any]:
        """The same keys the local engine's ``FrontData.to_dict`` carries."""
        has_text = bool(self.lines) or bool(self.interim)
        return {
            "status": "active_transcription" if has_text else "no_audio_detected",
            "lines": [dict(line) for line in self.lines],
            "buffer_transcription": self.interim,
            "buffer_diarization": "",
            "buffer_translation": "",
            "remaining_time_transcription": max(0.0, lag_seconds),
            "remaining_time_diarization": 0.0,
            "line_complete": bool(self.lines) and bool(self.lines[-1]["line_complete"]),
        }
