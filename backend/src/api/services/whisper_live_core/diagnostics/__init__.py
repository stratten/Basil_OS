"""Diagnostics helpers for the live transcription pipeline.

These modules are intentionally side-effect free and dependency-light so they
can be unit-tested in isolation and dropped into the hot audio path cheaply.
"""

from .stream_commit_watchdog import StreamCommitWatchdog

__all__ = ["StreamCommitWatchdog"]
