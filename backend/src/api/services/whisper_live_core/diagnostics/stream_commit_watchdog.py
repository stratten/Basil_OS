"""Stream commit watchdog.

Pure, time-injectable bookkeeping that detects the "audio keeps arriving but no
transcript is being committed" failure mode observed on the system-audio track
(audio.wav grows to full length while the persisted transcript stops part-way).

This module performs NO logging and NO teardown on its own; it only tracks
timestamps and reports a stall duration. The caller (AudioProcessor) decides how
to log/act. Keeping it isolated makes it trivially unit-testable and free of any
ASR/VAD/model state.

All timestamps are caller-supplied seconds (e.g. ``time.time()``); the watchdog
never reads the clock itself, so tests can drive it deterministically.
"""

from typing import Optional


class StreamCommitWatchdog:
    """Track audio-received vs commit timestamps for a single audio stream.

    A "commit" is the production of one or more finalized transcript lines. A
    stall is when audio is still actively arriving but no commit has occurred for
    at least ``stall_threshold_seconds``.
    """

    def __init__(
        self,
        source: str,
        stall_threshold_seconds: float = 60.0,
        audio_grace_seconds: float = 5.0,
    ) -> None:
        # Human-readable stream tag (e.g. "microphone" / "system_audio").
        self.source = source
        # How long without a commit (while audio flows) counts as a stall.
        self.stall_threshold_seconds = stall_threshold_seconds
        # Audio is considered "actively arriving" only if the last audio
        # timestamp is within this window of `now`; otherwise a gap is just the
        # stream being idle/finished, not a mid-stream stall.
        self.audio_grace_seconds = audio_grace_seconds

        self.first_audio_ts: Optional[float] = None
        self.last_audio_ts: Optional[float] = None
        self.last_commit_ts: Optional[float] = None
        self.commit_count: int = 0
        self._stall_warned: bool = False

    def note_audio_received(self, now: float) -> None:
        """Record that an audio chunk was received/written at time ``now``."""
        if self.first_audio_ts is None:
            self.first_audio_ts = now
        self.last_audio_ts = now

    def note_commit(self, now: float) -> None:
        """Record that finalized transcript line(s) were committed at ``now``.

        Re-arms the one-shot stall warning so a later stall is reported again.
        """
        self.last_commit_ts = now
        self.commit_count += 1
        self._stall_warned = False

    def stalled_for(self, now: float) -> Optional[float]:
        """Return seconds since the last commit if currently stalled, else None.

        Stalled means: audio arrived within ``audio_grace_seconds`` of ``now``
        (so the stream is live) AND the gap since the last commit (or since the
        first audio, if nothing has ever committed) is at least
        ``stall_threshold_seconds``.
        """
        if self.last_audio_ts is None:
            return None
        if (now - self.last_audio_ts) > self.audio_grace_seconds:
            # Audio is not currently flowing; a gap here is idle/finished, not a
            # mid-stream stall.
            return None

        reference = self.last_commit_ts if self.last_commit_ts is not None else self.first_audio_ts
        if reference is None:
            return None

        gap = now - reference
        if gap >= self.stall_threshold_seconds:
            return gap
        return None

    def should_warn(self, now: float) -> Optional[float]:
        """Return the stall duration to warn about, at most once per stall.

        Returns the gap (seconds) the first time a stall is observed and then
        None until a new commit re-arms it; this keeps logging to one WARNING
        per stall episode instead of one per audio chunk.
        """
        gap = self.stalled_for(now)
        if gap is not None and not self._stall_warned:
            self._stall_warned = True
            return gap
        return None
