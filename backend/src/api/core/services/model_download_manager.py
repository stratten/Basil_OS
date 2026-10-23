"""In-process orchestration for predefined model downloads.

``DownloadManager`` owns the application-level queue, cancellation signal, and
Swift-facing progress snapshot for predefined model downloads. The actual file
and Hugging Face artifact work stays in ``api.core.models.model_downloader`` and
``api.core.models.model_download``.

The manager replaces the old Huey task queue + JSON progress-file path with an
``asyncio.Semaphore``-gated set of in-process tasks. It is attached to
``app.state.download_manager`` at FastAPI startup so routes and onboarding share
one download state owner.

Concurrency is configurable via ``api_settings.MODEL_DOWNLOAD_MAX_CONCURRENT``
(default ``1``). Keep the default strict FIFO unless the tqdm progress hook is
made per-download; the current Hugging Face integrations patch tqdm during each
download so concurrent downloads can race on progress/cancellation state.

State exposed to routes (``to_progress_payload``) intentionally matches the
exact field names that ``client/.../ModelDownloadViewModel.swift`` decodes.
Changing those keys breaks the UI.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional

from api.core.config.api_settings import settings as api_settings
from api.core.logging.api_logger import api_logger
from api.core.models.model_downloader import ModelDownloader
from api.settings import get_models_dir

DownloadStatus = Literal[
    "queued",
    "downloading",
    "completed",
    "failed",
    "user_canceled",
    "skipped_installed",
]

# Status values that mean "still in flight" for queue / dedup purposes.
_ACTIVE_STATUSES: frozenset = frozenset({"queued", "downloading"})


@dataclass
class DownloadEntry:
    """Single in-memory record of a model download.

    Field names exposed via ``to_progress_payload()`` match the Swift
    ``ModelDownloadViewModel`` decoder exactly. Renaming or removing any of
    them silently breaks the model-management UI.
    """

    model_id: str
    model_type: str
    variant: str
    status: DownloadStatus = "queued"
    progress: float = 0.0
    bytes_downloaded: int = 0
    total_bytes: int = 0
    current_file: str = ""
    current_file_percent: float = 0.0
    files_completed: int = 0
    total_files: int = 0
    message: str = ""
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    def to_progress_payload(self) -> Dict[str, Any]:
        return {
            "progress": self.progress,
            "status": self.status,
            "total_downloaded": self.bytes_downloaded,
            "total_size": self.total_bytes,
            "message": self.message,
            "current_file": self.current_file,
            "current_file_percent": self.current_file_percent,
            "files_completed": self.files_completed,
            "total_files": self.total_files,
        }

    def to_status_summary(self) -> Dict[str, Any]:
        """Coarse summary used by the collection ``/models/download/status`` route."""
        return {
            "id": self.model_id,
            "model": self.model_id,
            "status": self.status,
            "progress": self.progress,
            "timestamp": (self.completed_at or self.started_at or datetime.now()).timestamp(),
            "error": self.error,
        }


class DownloadManager:
    """Asyncio-based replacement for the Huey download queue."""

    def __init__(
        self,
        max_concurrent: Optional[int] = None,
        models_dir: Optional[Path] = None,
        model_downloader: Optional[ModelDownloader] = None,
    ) -> None:
        cap = (
            max_concurrent
            if max_concurrent is not None
            else getattr(api_settings, "MODEL_DOWNLOAD_MAX_CONCURRENT", 1)
        )
        if cap < 1:
            cap = 1
        self._semaphore = asyncio.Semaphore(cap)
        self._max_concurrent = cap
        self._entries: Dict[str, DownloadEntry] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

        if model_downloader is not None:
            self._downloader = model_downloader
            self._models_dir = model_downloader.models_dir
            return

        # Test/standalone fallback. Production startup passes the singleton
        # ModelService downloader so queue state and model lifecycle checks share
        # one downloader object graph.
        if models_dir is None:
            models_dir = get_models_dir()
        self._models_dir = models_dir
        self._downloader = ModelDownloader(models_dir)

    @staticmethod
    def model_id_for(model_type: str, variant: str) -> str:
        return f"{model_type}-{variant}"

    async def start(self, model_type: str, variant: str) -> DownloadEntry:
        """Enqueue a download. Idempotent for in-flight or installed models."""
        model_id = self.model_id_for(model_type, variant)
        async with self._lock:
            existing = self._entries.get(model_id)
            if existing and existing.status in _ACTIVE_STATUSES:
                return existing

            if self._is_installed(model_type, variant):
                entry = DownloadEntry(
                    model_id=model_id,
                    model_type=model_type,
                    variant=variant,
                    status="skipped_installed",
                    progress=1.0,
                    message="Already installed",
                    completed_at=datetime.now(),
                )
                self._entries[model_id] = entry
                api_logger.info(
                    "[DOWNLOAD_MANAGER] %s already installed; skipping enqueue", model_id
                )
                return entry

            entry = DownloadEntry(
                model_id=model_id,
                model_type=model_type,
                variant=variant,
                message="Queued",
            )
            self._entries[model_id] = entry
            self._tasks[model_id] = asyncio.create_task(
                self._run(entry), name=f"download::{model_id}"
            )
            api_logger.info(
                "[DOWNLOAD_MANAGER] enqueued %s (active=%d, cap=%d)",
                model_id,
                len(self.list_active()),
                self._max_concurrent,
            )
            return entry

    async def cancel(self, model_id: str) -> bool:
        entry = self._entries.get(model_id)
        if not entry or entry.status not in _ACTIVE_STATUSES:
            return False
        entry.cancel_event.set()
        entry.message = "Canceling..."
        task = self._tasks.get(model_id)
        if task and not task.done():
            task.cancel()
        api_logger.info("[DOWNLOAD_MANAGER] cancel requested for %s", model_id)
        return True

    def get(self, model_id: str) -> Optional[DownloadEntry]:
        return self._entries.get(model_id)

    def get_by_pair(self, model_type: str, variant: str) -> Optional[DownloadEntry]:
        return self._entries.get(self.model_id_for(model_type, variant))

    async def wait_for_terminal_status(self, model_id: str) -> Optional[DownloadEntry]:
        """Wait for an enqueued download to reach a terminal status."""
        entry = self._entries.get(model_id)
        if entry is None:
            return None

        task = self._tasks.get(model_id)
        if task is None:
            return entry

        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.cancelled():
                raise

        return self._entries.get(model_id)

    def list_active(self) -> List[DownloadEntry]:
        return [e for e in self._entries.values() if e.status in _ACTIVE_STATUSES]

    def list_all(self) -> List[DownloadEntry]:
        return list(self._entries.values())

    def queue_position(self, model_id: str) -> int:
        """1-based position among queued entries; 0 if not queued."""
        queued_ids = [
            mid for mid, e in self._entries.items() if e.status == "queued"
        ]
        if model_id not in queued_ids:
            return 0
        return queued_ids.index(model_id) + 1

    async def shutdown(self) -> None:
        """Cancel every in-flight download and wait for tasks to drain."""
        if not self._tasks:
            return
        api_logger.info(
            "[DOWNLOAD_MANAGER] shutdown: canceling %d task(s)", len(self._tasks)
        )
        for entry in self._entries.values():
            if entry.status in _ACTIVE_STATUSES:
                entry.cancel_event.set()
        for task in list(self._tasks.values()):
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    def _is_installed(self, model_type: str, variant: str) -> bool:
        try:
            installed = self._downloader.get_installed_models()
        except Exception:
            api_logger.exception(
                "[DOWNLOAD_MANAGER] get_installed_models failed; assuming not installed"
            )
            return False
        provider_block = installed.get(model_type)
        if not provider_block:
            return False
        return variant in (provider_block.get("variants") or {})

    # Subset of DownloadStatus values that are valid mid-download. The
    # terminal transitions (`completed`, `failed`, `user_canceled`,
    # `skipped_installed`) are owned by `_run` itself; the progress pipeline
    # may not overwrite them with `"downloading"` after the fact.
    _PROGRESS_STATUSES: frozenset = frozenset({"downloading", "queued"})

    # Map progress-tracker metadata keys -> DownloadEntry attribute names.
    # `CustomHFCallback` emits the left-hand keys; `DownloadEntry` (and the
    # Swift-facing payload via `to_progress_payload`) uses the right-hand
    # names for `bytes_downloaded` / `total_bytes`. The remaining keys
    # (`current_file`, `current_file_percent`, `files_completed`,
    # `total_files`, `message`) already match 1:1.
    _METADATA_KEY_MAP: Dict[str, str] = {
        "total_downloaded": "bytes_downloaded",
        "total_size": "total_bytes",
        "current_file": "current_file",
        "current_file_percent": "current_file_percent",
        "files_completed": "files_completed",
        "total_files": "total_files",
        "message": "message",
    }

    def _make_progress_callback(
        self, entry: DownloadEntry
    ) -> Callable[[float, str, Optional[Dict[str, Any]]], None]:
        """Return a callback matching ``ProgressTracker``'s 3-arg dispatch shape."""

        def _cb(progress: float, status: str, metadata: Optional[Dict[str, Any]] = None) -> None:
            try:
                try:
                    entry.progress = float(progress)
                except (TypeError, ValueError):
                    pass

                if status and status in self._PROGRESS_STATUSES:
                    entry.status = status  # type: ignore[assignment]

                if metadata:
                    for src_key, dst_attr in self._METADATA_KEY_MAP.items():
                        if src_key not in metadata:
                            continue
                        value = metadata[src_key]
                        if dst_attr in ("message", "current_file") and value is None:
                            continue
                        setattr(entry, dst_attr, value)
            except Exception:
                api_logger.exception(
                    "[DOWNLOAD_MANAGER] progress callback failure for %s", entry.model_id
                )

        return _cb

    async def _run(self, entry: DownloadEntry) -> None:
        try:
            async with self._semaphore:
                if entry.cancel_event.is_set():
                    entry.status = "user_canceled"
                    entry.message = "Canceled before start"
                    return
                entry.status = "downloading"
                entry.started_at = datetime.now()
                entry.message = "Starting download..."

                callback = self._make_progress_callback(entry)
                await self._downloader.download_model(
                    entry.model_type,
                    entry.variant,
                    progress_callback=callback,
                    cancel_event=entry.cancel_event,
                )
                if entry.cancel_event.is_set():
                    entry.status = "user_canceled"
                    entry.message = "Canceled by user"
                    return
                entry.status = "completed"
                entry.progress = 1.0
                entry.message = "Download complete"
        except asyncio.CancelledError:
            entry.status = "user_canceled"
            entry.message = "Canceled by user"
            raise
        except Exception as exc:
            api_logger.exception(
                "[DOWNLOAD_MANAGER] download failed for %s", entry.model_id
            )
            entry.status = "failed"
            entry.error = str(exc)
            entry.message = f"Failed: {exc}"
        finally:
            entry.completed_at = datetime.now()
            self._tasks.pop(entry.model_id, None)
