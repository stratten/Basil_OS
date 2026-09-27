"""Model management router for handling model-related operations.

Post-Huey-removal (step 1.3.7), download orchestration goes through
`app.state.download_manager` (an `api.core.services.model_download_manager.DownloadManager`).
There is no longer a JSON-file IPC layer, no Huey result store, and no
WebSocket progress endpoint — Swift's `ModelDownloadViewModel` polls the
HTTP `GET .../download/progress` endpoint every ~500ms, which now reads
straight from the in-memory `DownloadEntry`.

Field names returned from `/download/progress` and `/download/status` MUST
match the Swift decoder (`client/.../ModelDownloadViewModel.swift`).
The single source of truth for that mapping is
`DownloadEntry.to_progress_payload()` / `to_status_summary()`.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import shutil
import time
import traceback
from pathlib import Path
from queue import Queue
from threading import Lock
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.core.logging.api_logger import api_logger
from api.core.models.model_types import ModelCapability
from api.core.models.model_manager import ModelManager
from api.core.services.model_download_manager import DownloadManager
from api.core.services.model_service import ModelService
from api.dependencies import get_model_service

router = APIRouter(prefix="/models", tags=["Models"])

# Cache for installed models
_installed_models_cache: Dict[str, Any] = {
    "data": None,
    "timestamp": 0,
    "ttl": 5,  # seconds
}

# Queue and lock for log streaming
_log_queues: Dict[str, Queue] = {}
_log_lock = Lock()


def _get_download_manager(request: Request) -> DownloadManager:
    """Resolve the singleton `DownloadManager` off `app.state`.

    Returning a 503 here (rather than raising at import time) covers the
    narrow window between FastAPI accepting the first request and the
    `startup` hook in `api/main.py` finishing — in normal operation the
    state attribute is set before the first request can land.
    """
    manager = getattr(request.app.state, "download_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=503,
            detail="Download manager not initialized; backend still starting.",
        )
    return manager


class LogHandler(logging.Handler):
    """Custom logging handler that writes to a queue."""

    def __init__(self, model_id: str):
        super().__init__()
        self.model_id = model_id
        self.queue: Queue = Queue()
        with _log_lock:
            _log_queues[model_id] = self.queue

    def emit(self, record):
        try:
            msg = self.format(record)
            with _log_lock:
                if self.model_id in _log_queues:
                    _log_queues[self.model_id].put(msg)
        except Exception:
            self.handleError(record)


@router.get("/predefined/{model_type}/{variant}/logs", response_class=StreamingResponse)
async def stream_download_logs(
    model_type: str,
    variant: str,
    model_service: ModelService = Depends(get_model_service),
) -> StreamingResponse:
    """Stream download logs for a specific predefined model."""
    model_id = f"{model_type}-{variant}"

    handler = LogHandler(model_id)
    handler.setFormatter(logging.Formatter("%(message)s"))
    api_logger.addHandler(handler)

    async def event_generator():
        try:
            while True:
                if model_id in _log_queues and not _log_queues[model_id].empty():
                    msg = _log_queues[model_id].get_nowait()
                    yield f"data: {msg}\n\n"
                await asyncio.sleep(0.1)
        finally:
            with _log_lock:
                if model_id in _log_queues:
                    del _log_queues[model_id]
            api_logger.removeHandler(handler)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/available")
async def list_available_models(
    model_service: ModelService = Depends(get_model_service),
) -> Dict:
    """List all available models and their variants."""
    available_models = model_service.model_downloader.get_available_models()
    api_logger.debug("Returning available models list")
    return available_models


@router.get("/installed")
async def list_installed_models(
    model_service: ModelService = Depends(get_model_service),
) -> Dict:
    """List all installed models and their metadata."""
    global _installed_models_cache

    current_time = time.time()
    if (
        _installed_models_cache["data"] is not None
        and current_time - _installed_models_cache["timestamp"]
        < _installed_models_cache["ttl"]
    ):
        api_logger.debug("Returning cached installed models list")
        return _installed_models_cache["data"]

    installed_models = model_service.model_downloader.get_installed_models()
    _installed_models_cache["data"] = installed_models
    _installed_models_cache["timestamp"] = current_time
    return installed_models


class ModelDownloadRequest(BaseModel):
    """Inner request body for model download."""

    model_type: str
    variant: str


class DownloadRequest(BaseModel):
    """Request body for model download endpoint."""

    request: ModelDownloadRequest


@router.post("/download")
async def download_model(
    request: DownloadRequest,
    http_request: Request,
) -> Dict[str, str]:
    """Enqueue a model download via `DownloadManager`.

    Idempotent for in-flight or already-installed models (the manager
    short-circuits both cases). Returns the canonical `<type>-<variant>`
    model_id; Swift uses that as the polling key against
    `/predefined/{type}/{variant}/download/progress`.
    """
    model_type = request.request.model_type
    variant = request.request.variant
    model_id = f"{model_type}-{variant}"

    api_logger.info(f"Initiating download for {model_id}")

    from api.core.models.models_registry import is_in_registry

    if not is_in_registry(model_id):
        raise HTTPException(
            status_code=404,
            detail=f"Model {model_type}/{variant} not found",
        )

    manager = _get_download_manager(http_request)
    try:
        entry = await manager.start(model_type, variant)
    except Exception as exc:
        api_logger.error(f"Failed to enqueue download for {model_id}: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to start download: {exc}")

    return {"model_id": entry.model_id, "status": entry.status}


@router.delete("/predefined/{model_type}/{variant}")
async def remove_model(
    model_type: str,
    variant: str,
    model_service: ModelService = Depends(get_model_service),
) -> Dict[str, str]:
    """Remove a specific predefined model variant.

    Path: /models/predefined/{model_type}/{variant}
    Custom models use: DELETE /models/custom/{model_id}
    """
    try:
        api_logger.info(f"Received request to remove model {model_type}/{variant}")
        model_id = f"{model_type}-{variant}"
        model_path = model_service.model_downloader._get_model_path_for_id(model_id)
        if not model_path.exists():
            api_logger.warning(
                f"Model {model_type}/{variant} not found at path {model_path}"
            )
            raise HTTPException(
                status_code=404, detail=f"Model {model_type}/{variant} not found"
            )
        success = model_service.model_downloader.remove_model(model_type, variant)
        if not success:
            api_logger.error(f"Failed to remove model {model_type}/{variant}")
            raise HTTPException(
                status_code=500,
                detail=f"Model {model_type}/{variant} could not be removed",
            )
        api_logger.info(f"Successfully removed model {model_type}/{variant}")
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(
            f"Unexpected error removing model {model_type}/{variant}: {str(e)}"
        )
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.get("/predefined/{model_type}/{variant}/download/progress")
async def get_download_progress(
    model_type: str,
    variant: str,
    http_request: Request,
    model_service: ModelService = Depends(get_model_service),
) -> dict:
    """Return current download progress for a predefined model.

    The returned dict's field shape MUST match the Swift decoder in
    `client/.../ModelDownloadViewModel.swift` — the canonical mapping
    lives in `DownloadEntry.to_progress_payload()`. Swift polls this every
    ~500ms; there is intentionally no WebSocket equivalent post-Huey-removal.
    """
    manager = _get_download_manager(http_request)
    entry = manager.get_by_pair(model_type, variant)
    if entry is not None:
        payload = entry.to_progress_payload()
        payload["timestamp"] = time.time()
        return payload

    # No DownloadEntry: either the model is already installed (Swift treats
    # `completed` as terminal and stops polling) or the user has never started
    # a download. Differentiate so the UI doesn't briefly flash "downloading"
    # for installed models on cold-start.
    try:
        installed = model_service.model_downloader.get_installed_models()
        provider_block = installed.get(model_type) or {}
        variants = provider_block.get("variants") or {}
        if variant in variants and variants[variant].get("valid"):
            return {
                "progress": 1.0,
                "status": "completed",
                "total_downloaded": 0,
                "total_size": 0,
                "message": "Already installed",
                "current_file": "",
                "current_file_percent": 0.0,
                "files_completed": 0,
                "total_files": 0,
                "timestamp": time.time(),
            }
    except Exception:
        api_logger.exception("Error checking installed status during progress poll")

    return {
        "progress": 0.0,
        "status": "not_found",
        "total_downloaded": 0,
        "total_size": 0,
        "message": "No active download",
        "current_file": "",
        "current_file_percent": 0.0,
        "files_completed": 0,
        "total_files": 0,
        "timestamp": time.time(),
    }


@router.get("/predefined/{model_type}/{variant}/status")
async def get_model_status(
    model_type: str,
    variant: str,
    model_service: ModelService = Depends(get_model_service),
) -> Dict[str, bool]:
    """Get the installation status of a predefined model."""
    try:
        installed_models = model_service.model_downloader.get_installed_models()
        is_installed = (
            model_type in installed_models
            and variant in installed_models[model_type]["variants"]
            and installed_models[model_type]["variants"][variant]["valid"]
        )
        return {"is_downloaded": is_installed}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/predefined/{model_type}/{variant}/size")
async def get_model_size(
    model_type: str,
    variant: str,
    model_service: ModelService = Depends(get_model_service),
) -> Dict[str, int]:
    """Get the size of a predefined model in bytes."""
    try:
        available_models = model_service.model_downloader.get_available_models()
        if (
            model_type not in available_models
            or variant not in available_models[model_type]["variants"]
        ):
            raise HTTPException(status_code=404, detail="Model not found")

        variant_info = available_models[model_type]["variants"][variant]
        size_str = variant_info.get("size", "0GB").lower()

        # Decimal conversion (1000^3) to match Hugging Face file sizes.
        size_bytes = 0
        if size_str.endswith("gb"):
            size_bytes = int(float(size_str.replace("gb", "")) * 1000 * 1000 * 1000)
        elif size_str.endswith("mb"):
            size_bytes = int(float(size_str.replace("mb", "")) * 1000 * 1000)

        return {"size": size_bytes}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/status")
async def get_all_downloads_status(http_request: Request) -> Dict[str, List[Dict]]:
    """Return a coarse summary of every download the manager has seen.

    Replaces the old Huey-result-store walk. Capped at 10 most-recent for
    parity with the previous behavior; sort key is completion time falling
    back to start time.
    """
    api_logger.debug("Download status request received")
    try:
        manager = _get_download_manager(http_request)
        entries = manager.list_all()
        tasks = [e.to_status_summary() for e in entries]
        tasks.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return {"tasks": tasks[:10]}
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"Error getting download status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/active")
async def get_active_downloads(http_request: Request) -> Dict[str, List[Dict]]:
    """Return full progress for downloads the manager has seen this process.

    Unlike ``/download/status`` (which is capped and coarse), this endpoint
    returns the complete per-model payload required by the global progress
    widget. Terminal entries remain available so a client can show their
    final state briefly before removing them locally.
    """
    api_logger.debug("Active downloads request received")
    try:
        manager = _get_download_manager(http_request)
        downloads = [
            {
                "model_id": entry.model_id,
                "model_type": entry.model_type,
                "variant": entry.variant,
                **entry.to_progress_payload(),
            }
            for entry in manager.list_all()
        ]
        return {"downloads": downloads}
    except HTTPException:
        raise
    except Exception as e:
        api_logger.error(f"Error getting active downloads: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel")
async def cancel_model_download(
    request: ModelDownloadRequest,
    http_request: Request,
    model_service: ModelService = Depends(get_model_service),
) -> Dict[str, str]:
    """Cancel an in-progress model download via `DownloadManager`.

    Cancellation flow:
      1. `DownloadManager.cancel(...)` sets the per-entry `cancel_event`.
      2. The per-call tqdm subclass observes the event on its next tick and
         raises `CancelledError`, unwinding `snapshot_download` /
         `hf_hub_download`.
      3. `task.cancel()` covers the case where no tqdm tick fires before
         cancellation lands (tiny window, tiny files).
      4. The DownloadManager `_run` finally block flips status to
         `user_cancelled`, which Swift's progress poll picks up.

    Partial-file cleanup on disk is best-effort and runs after cancellation
    is requested. The HF cache keeps any fully-fetched blobs so a subsequent
    download can resume cheaply.
    """
    model_type = request.model_type
    variant = request.variant
    model_id = f"{model_type}-{variant}"

    api_logger.info(f"Received request to cancel download for {model_id}")
    manager = _get_download_manager(http_request)

    try:
        cancelled = await manager.cancel(model_id)
        if not cancelled:
            api_logger.warning(f"No active download found for {model_id}")
            return {"status": "not_found", "message": "No active download found"}

        if not model_service.model_downloader.remove_partial_model(model_type, variant):
            api_logger.warning("Partial cleanup reported failure for %s", model_id)

        api_logger.info(f"Successfully cancelled download for {model_id}")
        return {"status": "success", "message": "Download cancelled"}
    except Exception as e:
        api_logger.error(f"Error cancelling download: {e}")
        raise HTTPException(status_code=500, detail=str(e))
