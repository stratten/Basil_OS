"""In-memory progress tracker for model downloads.

This module used to be a hybrid: it kept in-memory state on `ModelDownloader`
*and* wrote per-model `progress_*.json` files into the models directory so a
separate Huey worker process and the FastAPI process could both observe
progress. After the Huey-removal plan (step 1.2.6), downloads run inside the
same FastAPI process under `DownloadManager`, so the JSON layer is dead
weight and the cross-process polling code (`is_downloading`,
`check_for_external_cancellation`, `cancel_download`, the orphan-file
cleanup pass) has been deleted.

What survives:
  * In-memory state dicts (`_progress`, `_current_operations`,
    `_progress_metadata`, `_download_stats`) — read by `model_downloader.py`
    while a download is in flight.
  * Callback registry (`register_progress_callback` and friends) — the
    bridge into `DownloadManager._make_progress_callback`. Every progress
    update fan-outs to all callbacks registered for `<model_type>-<variant>`.
  * `_update_progress` / `_update_progress_sync` — same call sites
    (`model_downloader.py`, `callbacks.py`) but now only mutate in-memory
    state and invoke registered callbacks. Both file writes and the
    `huey.put(task_id, ...)` side-effect have been removed.
  * `_start_heartbeat` — still kicked off by `download_model` so callbacks
    keep firing even when bytes-per-second drops to zero.
  * `_progress_file_lock` is retained as an attribute (now a plain
    `threading.Lock` no-op) only so the existing `with
    self.progress_tracker._progress_file_lock:` blocks in
    `model_downloader.py` (resume-from-cancel branch) keep parsing without
    a follow-up edit. The lock is functionally unused.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ...logging.api_logger import api_logger


class ProgressTracker:
    """In-memory progress state for model downloads + callback fan-out."""

    def __init__(self, models_dir: Path):
        self.models_dir = models_dir
        self._progress: Dict[str, float] = {}
        self._current_operations: Dict[str, str] = {}
        self._progress_metadata: Dict[str, dict] = {}
        self._download_stats: Dict[str, dict] = {}
        self._progress_callbacks: Dict[str, List[Callable]] = {}
        # Vestigial: kept so existing `with ... :` blocks in model_downloader.py
        # still parse. No file I/O happens here anymore.
        self._progress_file_lock = threading.Lock()

    def get_progress(self, model_id: str) -> float:
        return self._progress.get(model_id, 0.0)

    def get_operation_status(self, model_id: str) -> str:
        return self._current_operations.get(model_id, "unknown")

    def register_progress_callback(
        self, model_type: str, variant: str, callback: Callable
    ) -> None:
        model_id = f"{model_type}-{variant}"
        bucket = self._progress_callbacks.setdefault(model_id, [])
        if callback not in bucket:
            bucket.append(callback)
            api_logger.debug(f"Registered progress callback for {model_id}")

    def unregister_progress_callback(
        self, model_type: str, variant: str, callback: Callable
    ) -> None:
        model_id = f"{model_type}-{variant}"
        bucket = self._progress_callbacks.get(model_id)
        if bucket and callback in bucket:
            bucket.remove(callback)
            api_logger.debug(f"Unregistered progress callback for {model_id}")

    def remove_all_progress_callbacks(self, model_type: str, variant: str) -> None:
        model_id = f"{model_type}-{variant}"
        self._progress_callbacks.pop(model_id, None)

    @staticmethod
    def _format_time(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        if seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}h {minutes}m"

    def _update_progress_sync(
        self,
        model_type: str,
        variant: str,
        progress: float,
        status: str = "downloading",
        metadata: Optional[dict] = None,
    ) -> None:
        """Synchronously mutate in-memory state. Safe to call from any thread.

        Pre-Huey-removal this also wrote `progress_<model_id>.json` for IPC.
        That JSON layer no longer exists; only in-memory state and the async
        `_update_progress` fan-out matter now.
        """
        model_id = f"{model_type}-{variant}"
        self._progress[model_id] = float(progress)
        self._current_operations[model_id] = status
        if metadata:
            md = dict(metadata)
            md.setdefault("timestamp", time.time())
            self._progress_metadata[model_id] = md

    async def _update_progress(
        self,
        model_type: str,
        variant: str,
        progress: float,
        status: str = "downloading",
        metadata: Optional[dict] = None,
    ) -> None:
        """Async progress update: stats, metadata, and registered-callback fan-out.

        After step 1.2.6:
          * No `progress_*.json` write.
          * No `huey.put(task_id, ...)` side effect (Huey is gone).
          * Registered callbacks (`DownloadManager._make_progress_callback`,
            tests, etc.) are invoked with `(progress, status, metadata)`.
            DownloadManager folds the metadata dict back into the
            `DownloadEntry` it owns, which is what the routes / Swift UI read.
        """
        model_id = f"{model_type}-{variant}"
        self._progress[model_id] = float(progress)
        self._current_operations[model_id] = status

        current_time = time.time()
        if metadata is None:
            metadata = {}
        metadata = dict(metadata)
        metadata.setdefault("timestamp", current_time)

        download_stats: Dict[str, float] = {}
        prior = self._download_stats.get(model_id)
        if prior:
            last_progress = prior.get("last_progress", 0.0)
            last_time = prior.get("last_time", current_time)
            start_time = prior.get("start_time", current_time)
            time_diff = current_time - last_time
            if time_diff > 0:
                rate = (progress - last_progress) / time_diff
                if rate > 0:
                    eta_seconds = (1.0 - progress) / rate
                    download_stats["eta_seconds"] = eta_seconds
                    download_stats["eta_formatted"] = self._format_time(eta_seconds)
                if current_time > start_time:
                    download_stats["avg_rate"] = progress / (current_time - start_time)
        else:
            download_stats["start_time"] = current_time

        download_stats["last_progress"] = float(progress)
        download_stats["last_time"] = current_time
        download_stats["status"] = status
        self._download_stats[model_id] = {**(prior or {}), **download_stats}

        # Surface ETA / rate to the metadata dict so the registered callback
        # (and therefore the UI) can render them without re-deriving.
        for k, v in download_stats.items():
            metadata.setdefault(k, v)
        self._progress_metadata[model_id] = metadata

        callbacks = list(self._progress_callbacks.get(model_id, ()))
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(progress, status, metadata)
                else:
                    callback(progress, status, metadata)
            except Exception as exc:
                api_logger.error(
                    f"[PROGRESS_CB] error invoking callback for {model_id}: {exc}"
                )

    async def _start_heartbeat(self, model_type: str, variant: str) -> None:
        """Periodic re-emit so registered callbacks keep firing during slow ticks.

        Same shape as before; the only difference is that the heartbeat now
        only flows through callbacks (no file write).
        """
        model_id = f"{model_type}-{variant}"
        terminal = {"completed", "error", "canceled", "user_canceled", "failed"}
        api_logger.debug(f"[HEARTBEAT] started for {model_id}")
        try:
            while self._current_operations.get(model_id) not in terminal:
                await asyncio.sleep(5)
                current_op = self._current_operations.get(model_id)
                if current_op in terminal or current_op is None:
                    break
                metadata = dict(self._progress_metadata.get(model_id, {}))
                metadata["heartbeat"] = True
                metadata["current_operation"] = current_op
                await self._update_progress(
                    model_type,
                    variant,
                    self.get_progress(model_id),
                    status=current_op,
                    metadata=metadata,
                )
        finally:
            api_logger.debug(f"[HEARTBEAT] stopped for {model_id}")
