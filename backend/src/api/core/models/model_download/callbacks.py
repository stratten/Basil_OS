"""Per-tick progress aggregator for HF Hub downloads.

`CustomHFCallback` is invoked from the temporary `tqdm.__init__` monkey-patches
applied by the concrete Hugging Face downloaders for every `update()` tick
during a `snapshot_download` / `hf_hub_download` run. It folds per-file byte
counts into an overall download-progress fraction and forwards the result
through `ModelDownloader._update_progress` (which fans out into the registered
`DownloadManager` callback rather than writing JSON files).

What changed in step 1.2.5 (Huey-removal plan):
  * Dropped the `progress_tracker.check_for_external_cancellation(...)`
    file-poll. Cancellation is now driven by `cancel_event` checked inside
    the patched `update()`; if the event is set, `update()` raises
    `CancelledError` before this callback ever runs.
  * Removed file-based cancellation tied to the old monkey-patch
    instrumentation.
  * Removed the `get_operation_status` -> CancelledError branch (same
    rationale: cancellation is event-driven, not file-driven).

Followup note: the concrete downloaders still patch tqdm while a download is
active because Hugging Face's internal per-file bars do not consistently honor
the `tqdm_class` kwarg. Keep `MODEL_DOWNLOAD_MAX_CONCURRENT == 1` unless that
hook becomes per-download rather than class-global.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from ...logging.api_logger import api_logger
from ..models_registry import get_model, get_repo_info


class CustomHFCallback:
    """Aggregates per-file tqdm ticks into a single download-progress fraction."""

    def __init__(self, model_type: str, variant: str, downloader, event_loop):
        self.model_type = model_type
        self.variant = variant
        self.downloader = downloader
        self.event_loop = event_loop

        self.estimated_total_size = self._estimate_total_size()
        self.current_file = ""
        # Throttle progress emission to avoid spamming the manager / UI.
        self.last_update_time = time.time()
        self.update_interval = 1.0
        self.file_progress: dict[str, int] = {}
        self.actual_file_totals: dict[str, int] = {}
        self.completed_files: set[str] = set()

        # Best-effort upper bound on file count; refined as we observe completes.
        self.total_files: int = 1
        model_id = f"{model_type}-{variant}"
        model_cfg = get_model(model_id)
        if model_cfg and get_repo_info(model_id):
            # HF repo bundles vary widely; 11 mirrors the historical default for
            # Whisper-style snapshots and is only used when we haven't yet
            # observed enough file completions.
            self.total_files = 11

    def _estimate_total_size(self) -> int:
        """Estimate total bytes from the registry's `size` string (decimal units)."""
        model_id = f"{self.model_type}-{self.variant}"
        model_cfg = get_model(model_id)
        if not model_cfg:
            return 100_000_000
        size_str = (model_cfg.get("size") or "100MB").lower()
        try:
            if size_str.endswith("gb"):
                return int(float(size_str.replace("gb", "")) * 1000 * 1000 * 1000)
            if size_str.endswith("mb"):
                return int(float(size_str.replace("mb", "")) * 1000 * 1000)
        except ValueError:
            pass
        return 100_000_000

    def __call__(self, downloaded_bytes: int, total_bytes: Optional[int], file_name: str) -> None:
        self.current_file = file_name
        self.file_progress[file_name] = downloaded_bytes
        if total_bytes and total_bytes > 0:
            self.actual_file_totals[file_name] = total_bytes
            if downloaded_bytes >= total_bytes:
                self.completed_files.add(file_name)

        files_completed = len(self.completed_files)
        total_files = max(self.total_files, files_completed, 1)
        per_file_percent = (
            int(100 * downloaded_bytes / total_bytes) if total_bytes else 0
        )

        total_downloaded = sum(self.file_progress.values())
        actual_total_from_hf = sum(self.actual_file_totals.values())
        # Use the larger of (HF-reported actual) and (registry estimate) so
        # progress doesn't sail past 95% before all per-file totals are known.
        if actual_total_from_hf > 0:
            total_size = max(actual_total_from_hf, self.estimated_total_size)
        else:
            total_size = self.estimated_total_size or 1
        # Cap at 0.95: the final 5% is reserved for the cache->models copy phase.
        progress = min(0.95 * total_downloaded / max(total_size, 1), 0.95)

        now = time.time()
        if now - self.last_update_time < self.update_interval:
            return
        self.last_update_time = now

        metadata = {
            "message": f"Downloading {file_name}...",
            "current_file": file_name,
            "current_file_percent": per_file_percent,
            "files_completed": files_completed,
            "total_files": total_files,
            "total_downloaded": total_downloaded,
            "total_size": total_size,
        }

        try:
            # Synchronous in-memory update so a subsequent same-thread read
            # sees fresh state without waiting for the async pump to drain.
            self.downloader._update_progress_sync(
                self.model_type,
                self.variant,
                progress,
                status="downloading",
                metadata=metadata,
            )
            # Async fan-out: schedules the registered progress callback
            # (typically `DownloadManager._make_progress_callback`) on the
            # FastAPI event loop. Safe across threads because the tqdm tick
            # runs inside `asyncio.to_thread`, not on the event loop itself.
            if self.event_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.downloader._update_progress(
                        self.model_type,
                        self.variant,
                        progress,
                        status="downloading",
                        metadata=metadata,
                    ),
                    self.event_loop,
                )
        except Exception as exc:
            api_logger.error(f"[HF_CALLBACK] error forwarding progress: {exc}")
