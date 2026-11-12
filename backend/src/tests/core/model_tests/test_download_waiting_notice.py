"""Tests that a download which has not received a byte yet says so instead of showing made-up progress.

Hugging Face's xet transfer can take tens of seconds to start sending data, and nothing is reported meanwhile. Before this change a GGUF download sat at a hard-coded 2% with "Downloading ..." for that whole time.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from api.core.models.model_download import progress_tracker as progress_tracker_module
from api.core.models.model_download.direct_file_downloader import DirectFileDownloader
from api.core.models.model_download.progress_tracker import ProgressTracker

MODEL_ID = "Test-waiting"


class _RecordingOwner:
    """Stands in for the downloader that owns progress and keeps every update it is given."""

    def __init__(self) -> None:
        self.updates: List[Tuple[float, str, Dict[str, Any]]] = []

    async def _update_progress(self, model_type: str, variant: str, progress: float, status: str = "downloading", metadata: Dict[str, Any] | None = None) -> None:
        self.updates.append((progress, status, dict(metadata or {})))


async def _run_heartbeats(tracker: ProgressTracker, beats: int = 3) -> List[Tuple[float, str, Dict[str, Any]]]:
    """Run the tracker's heartbeat for a few fast beats and return what registered callbacks received."""
    received: List[Tuple[float, str, Dict[str, Any]]] = []
    tracker.register_progress_callback("Test", "waiting", lambda progress, status, metadata: received.append((progress, status, dict(metadata))))
    task = asyncio.create_task(tracker._start_heartbeat("Test", "waiting"))
    await asyncio.sleep(0.01 * beats + 0.02)
    tracker._current_operations[MODEL_ID] = "completed"
    await task
    return received


@pytest.fixture
def fast_heartbeat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(progress_tracker_module, "HEARTBEAT_INTERVAL_SECONDS", 0.01)


@pytest.mark.asyncio
async def test_heartbeat_says_it_is_waiting_while_no_byte_has_arrived(tmp_path: Path, fast_heartbeat: None) -> None:
    tracker = ProgressTracker(tmp_path)
    tracker._update_progress_sync("Test", "waiting", 0.0, status="downloading", metadata={"message": "Contacting Hugging Face for model.gguf..."})

    received = await _run_heartbeats(tracker)

    assert received
    assert all(progress == 0.0 for progress, _, _ in received)
    assert all(metadata["message"].startswith("Waiting for Hugging Face to start sending data (") for _, _, metadata in received)


@pytest.mark.asyncio
async def test_heartbeat_leaves_the_message_alone_once_bytes_are_flowing(tmp_path: Path, fast_heartbeat: None) -> None:
    tracker = ProgressTracker(tmp_path)
    tracker._update_progress_sync(
        "Test", "waiting", 0.05, status="downloading",
        metadata={"message": "Downloading model.gguf...", "total_downloaded": 500_000_000, "total_size": 5_000_000_000},
    )

    received = await _run_heartbeats(tracker)

    assert received
    assert all(metadata["message"] == "Downloading model.gguf..." for _, _, metadata in received)


@pytest.mark.asyncio
async def test_heartbeat_does_not_claim_to_be_waiting_during_a_manifest_download(tmp_path: Path, fast_heartbeat: None) -> None:
    tracker = ProgressTracker(tmp_path)
    tracker._update_progress_sync(
        "Test", "waiting", 0.0, status="downloading",
        metadata={"message": "Downloading artifact 1 of 4: part-1.gguf", "current_file": "part-1.gguf"},
    )

    received = await _run_heartbeats(tracker)

    assert received
    assert all(metadata["message"] == "Downloading artifact 1 of 4: part-1.gguf" for _, _, metadata in received)


@pytest.mark.asyncio
async def test_heartbeat_does_not_claim_to_be_waiting_while_copying(tmp_path: Path, fast_heartbeat: None) -> None:
    tracker = ProgressTracker(tmp_path)
    tracker._update_progress_sync("Test", "waiting", 0.95, status="copying", metadata={"message": "Copying to models directory..."})

    received = await _run_heartbeats(tracker)

    assert received
    assert all(metadata["message"] == "Copying to models directory..." for _, _, metadata in received)


@pytest.mark.asyncio
async def test_a_gguf_download_reports_no_progress_before_its_first_byte(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The start of a direct Hugging Face download must not invent a percentage."""
    import huggingface_hub

    def failing_download(**kwargs: Any) -> str:
        raise RuntimeError("stop before any byte")

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", failing_download)
    owner = _RecordingOwner()
    downloader = DirectFileDownloader(tmp_path, artifacts=None, progress_tracker=ProgressTracker(tmp_path), progress_owner=owner)

    with pytest.raises(RuntimeError, match="stop before any byte"):
        await downloader.download_direct_file(
            "Test",
            "waiting",
            MODEL_ID,
            {},
            {"url": "https://huggingface.co/owner/repo/resolve/main/model.gguf"},
            tmp_path / "model.gguf",
        )

    assert owner.updates
    assert all(progress == 0.0 for progress, _, _ in owner.updates)
    assert owner.updates[-1][2]["message"] == "Contacting Hugging Face for model.gguf..."
