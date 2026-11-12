"""Tests for the progress numbers a model download reports to the UI.

huggingface_hub 2.x reports one download through several progress bars at once: a "downloading bytes" bar for what the network has delivered, a "reconstructing file" bar for what has been written to disk, and, for a snapshot, shared aggregate bars of each kind plus a "Fetching N files" counter. These tests feed the callback the same bar sequences and check that the reported size and progress describe one download, not the sum of the bars.
"""

from __future__ import annotations

from typing import Any, Dict, List

from api.core.models.model_download.callbacks import CustomHFCallback, _display_file_name

# Registry entry "Google-gemma4-e4b-it-qat-mlx-4bit": a snapshot download whose real size is 6.83 GB against a 6.8 GB registry estimate.
MLX_MODEL_TYPE = "Google"
MLX_VARIANT = "gemma4-e4b-it-qat-mlx-4bit"
MLX_REAL_BYTES = 6_830_000_000

# Registry entry "Google-gemma4-e4b-it-qat-q4_0": a single GGUF file of 5.15 GB.
GGUF_MODEL_TYPE = "Google"
GGUF_VARIANT = "gemma4-e4b-it-qat-q4_0"
GGUF_REAL_BYTES = 5_150_000_000


class _RecordingDownloader:
    """Stands in for ``ModelDownloader`` and keeps every progress update the callback sends."""

    def __init__(self) -> None:
        self.updates: List[Dict[str, Any]] = []

    def _update_progress_sync(self, model_type: str, variant: str, progress: float, status: str = "downloading", metadata: Dict[str, Any] | None = None) -> None:
        self.updates.append({"progress": progress, "status": status, **(metadata or {})})

    async def _update_progress(self, *args: Any, **kwargs: Any) -> None:
        return None


class _IdleLoop:
    """An event loop stand-in that is not running, so the callback skips the thread-safe fan-out."""

    def is_running(self) -> bool:
        return False


def _callback(model_type: str, variant: str) -> tuple[CustomHFCallback, _RecordingDownloader]:
    downloader = _RecordingDownloader()
    callback = CustomHFCallback(model_type, variant, downloader, _IdleLoop())
    callback.update_interval = 0
    return callback, downloader


def test_snapshot_bars_are_not_summed_into_double_the_real_size() -> None:
    callback, downloader = _callback(MLX_MODEL_TYPE, MLX_VARIANT)

    callback(3, 12, "Fetching 12 files")
    callback(3_000_000_000, MLX_REAL_BYTES, "Downloading bytes")
    callback(2_500_000_000, MLX_REAL_BYTES, "Reconstructing (incomplete total...)")

    last = downloader.updates[-1]
    assert last["total_size"] == MLX_REAL_BYTES
    assert last["total_downloaded"] == 3_000_000_000
    assert abs(last["progress"] - 0.95 * 3_000_000_000 / MLX_REAL_BYTES) < 1e-9


def test_snapshot_reaches_the_cap_when_every_byte_is_reconstructed() -> None:
    callback, downloader = _callback(MLX_MODEL_TYPE, MLX_VARIANT)

    callback(12, 12, "Fetching 12 files")
    callback(MLX_REAL_BYTES, MLX_REAL_BYTES, "Downloading bytes")
    callback(MLX_REAL_BYTES, MLX_REAL_BYTES, "Reconstructing (incomplete total...)")

    last = downloader.updates[-1]
    assert last["total_size"] == MLX_REAL_BYTES
    assert last["total_downloaded"] == MLX_REAL_BYTES
    assert last["progress"] == 0.95


def test_gguf_file_with_two_xet_bars_reports_one_file_size() -> None:
    callback, downloader = _callback(GGUF_MODEL_TYPE, GGUF_VARIANT)
    file_name = "gemma-4-E4B_q4_0-it.gguf"

    callback(1_000_000_000, GGUF_REAL_BYTES, f"{file_name}: downloading bytes")
    callback(400_000_000, GGUF_REAL_BYTES, f"{file_name}: reconstructing file")

    last = downloader.updates[-1]
    assert last["total_size"] == GGUF_REAL_BYTES
    assert last["total_downloaded"] == 1_000_000_000
    assert last["current_file"] == "gemma-4-E4B_q4_0-it.gguf"
    assert last["message"] == "Downloading gemma-4-E4B_q4_0-it.gguf..."


def test_gguf_progress_rises_with_the_network_bar_and_never_goes_backward() -> None:
    callback, downloader = _callback(GGUF_MODEL_TYPE, GGUF_VARIANT)
    file_name = "gemma-4-E4B_q4_0-it.gguf"

    for delivered in range(500_000_000, GGUF_REAL_BYTES + 1, 500_000_000):
        callback(delivered, GGUF_REAL_BYTES, f"{file_name}: downloading bytes")
        callback(max(0, delivered - 800_000_000), GGUF_REAL_BYTES, f"{file_name}: reconstructing file")

    fractions = [update["progress"] for update in downloader.updates]
    assert fractions == sorted(fractions)
    assert fractions[0] > 0
    assert fractions[-1] <= 0.95


def test_single_bar_download_still_reports_its_own_bytes() -> None:
    callback, downloader = _callback("Unregistered", "single-file")

    callback(150_000_000, 300_000_000, "model.gguf")

    last = downloader.updates[-1]
    assert last["total_downloaded"] == 150_000_000
    assert last["total_size"] == 300_000_000
    assert abs(last["progress"] - 0.95 * 0.5) < 1e-9


def test_completed_download_never_reports_more_bytes_than_its_total() -> None:
    callback, downloader = _callback(GGUF_MODEL_TYPE, GGUF_VARIANT)

    callback(GGUF_REAL_BYTES, GGUF_REAL_BYTES, "gemma-4-E4B_q4_0-it.gguf: reconstructing file")

    last = downloader.updates[-1]
    assert last["total_downloaded"] <= last["total_size"]
    assert last["progress"] == 0.95


def test_display_file_name_strips_xet_suffixes_and_names_shared_bars_plainly() -> None:
    assert _display_file_name("model.gguf: downloading bytes") == "model.gguf"
    assert _display_file_name("model.gguf: reconstructing file") == "model.gguf"
    assert _display_file_name("Reconstructing (incomplete total...)") == "model files"
    assert _display_file_name("Downloading bytes") == "model files"
    assert _display_file_name("Fetching 12 files") == "model files"
    assert _display_file_name("model-00001-of-00002.safetensors") == "model-00001-of-00002.safetensors"
    assert _display_file_name("") == "model files"
