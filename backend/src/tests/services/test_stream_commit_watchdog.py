"""Unit tests for the diagnostics-only StreamCommitWatchdog.

The watchdog is dependency-free, so it is loaded directly from its file to avoid
triggering the heavy `whisper_live_core` package import chain (numpy/torch/etc.)
and to keep these tests fast and isolated.
"""

import importlib.util
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "api" / "services" / "whisper_live_core" / "diagnostics" / "stream_commit_watchdog.py"
)
_spec = importlib.util.spec_from_file_location("stream_commit_watchdog_under_test", _MODULE_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
StreamCommitWatchdog = _mod.StreamCommitWatchdog


def test_no_stall_before_threshold_even_with_audio_flowing():
    wd = StreamCommitWatchdog("system_audio", stall_threshold_seconds=60.0, audio_grace_seconds=5.0)
    wd.note_audio_received(0.0)
    wd.note_commit(0.0)
    wd.note_audio_received(30.0)
    # 30s since last commit, audio still flowing, but below the 60s threshold.
    assert wd.stalled_for(30.0) is None
    assert wd.should_warn(30.0) is None


def test_stall_detected_when_audio_continues_but_commits_stop():
    wd = StreamCommitWatchdog("system_audio", stall_threshold_seconds=60.0, audio_grace_seconds=5.0)
    wd.note_audio_received(0.0)
    wd.note_commit(0.0)
    # Audio keeps arriving up to t=70 but no further commits.
    wd.note_audio_received(70.0)
    gap = wd.stalled_for(70.0)
    assert gap is not None
    assert gap == 70.0


def test_warning_is_one_shot_until_recommit():
    wd = StreamCommitWatchdog("system_audio", stall_threshold_seconds=60.0, audio_grace_seconds=5.0)
    wd.note_audio_received(0.0)
    wd.note_commit(0.0)
    wd.note_audio_received(70.0)

    first = wd.should_warn(70.0)
    assert first == 70.0
    # Same stall episode: no repeated warning.
    wd.note_audio_received(75.0)
    assert wd.should_warn(75.0) is None


def test_commit_clears_stall_and_rearms_warning():
    wd = StreamCommitWatchdog("system_audio", stall_threshold_seconds=60.0, audio_grace_seconds=5.0)
    wd.note_audio_received(0.0)
    wd.note_commit(0.0)
    wd.note_audio_received(70.0)
    assert wd.should_warn(70.0) == 70.0

    # A new commit clears the stall and re-arms the one-shot warning.
    wd.note_commit(71.0)
    assert wd.stalled_for(72.0) is None

    # A subsequent stall warns again.
    wd.note_audio_received(140.0)
    assert wd.should_warn(140.0) is not None


def test_idle_stream_is_not_a_stall():
    # If audio is NOT currently arriving (last audio is stale beyond the grace
    # window), a long gap since the last commit is just an idle/finished stream,
    # not a mid-recording stall.
    wd = StreamCommitWatchdog("microphone", stall_threshold_seconds=60.0, audio_grace_seconds=5.0)
    wd.note_audio_received(0.0)
    wd.note_commit(0.0)
    # No audio since t=0; now is t=120 (audio is 120s stale > 5s grace).
    assert wd.stalled_for(120.0) is None
    assert wd.should_warn(120.0) is None


def test_stall_before_any_commit_uses_first_audio_as_reference():
    # System-audio that never commits: stall measured from the first audio chunk.
    wd = StreamCommitWatchdog("system_audio", stall_threshold_seconds=60.0, audio_grace_seconds=5.0)
    wd.note_audio_received(10.0)
    wd.note_audio_received(75.0)
    gap = wd.stalled_for(75.0)
    assert gap is not None
    assert gap == 65.0


def test_no_audio_means_no_stall():
    wd = StreamCommitWatchdog("system_audio")
    assert wd.stalled_for(100.0) is None
    assert wd.should_warn(100.0) is None
