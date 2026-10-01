"""Onboarding router for first-launch model downloads and setup.

Post-Huey-removal (step 1.3.8): the dispatch path is `DownloadManager.start`
for each starter model in priority order. The DownloadManager's semaphore
(default cap = 1) preserves the historical sequential behavior of the
deleted `download_starter_models_sequential` Huey task. Progress comes from
`DownloadManager` state, not `progress_*.json` files.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..core.services.model_download_manager import DownloadManager
from ..core.logging.api_logger import api_logger
from ..core.services.model_service import ModelService
from ..dependencies import get_model_service

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


# Define the starter model pack - downloads automatically on first launch
STARTER_MODELS = [
    {
        "model_type": "OpenAI",
        "variant": "whisper-tiny.en",
        "priority": 1,  # Download first
        "description": "Fast English transcription (151MB)",
    },
    {
        "model_type": "NVIDIA",
        "variant": "parakeet-tdt-0.6b-v3-quantized",
        "priority": 2,
        "description": "High-quality multilingual transcription (670MB)",
    },
    {
        "model_type": "Qwen",
        "variant": "qwen3-8b-instruct-q4km",
        "priority": 3,
        "description": "Reasoning model for suggestions (5GB)",
    },
]


def _get_download_manager(request: Request) -> DownloadManager:
    manager = getattr(request.app.state, "download_manager", None)
    if manager is None:
        # Mirrors the guard in routes/models.py: covers the narrow startup
        # window before the FastAPI startup hook attaches the manager.
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503,
            detail="Download manager not initialized; backend still starting.",
        )
    return manager


class StarterModelInfo(BaseModel):
    """Information about a starter model."""

    model_type: str
    variant: str
    model_id: str
    description: str
    is_installed: bool
    # Kept for wire-compat with the existing Swift onboarding decoder; this
    # used to be the Huey task UUID. Now it carries the canonical model_id
    # ("<type>-<variant>") which is the polling key Swift already uses.
    task_id: str | None = None


class StarterModelsResponse(BaseModel):
    """Response from starter models endpoint."""

    models: List[StarterModelInfo]
    all_installed: bool
    downloads_started: int


@router.get("/starter-models")
async def get_starter_models_status(
    model_service: ModelService = Depends(get_model_service),
) -> StarterModelsResponse:
    """Status of starter models without starting downloads."""
    models: List[StarterModelInfo] = []
    all_installed = True

    for model_config in STARTER_MODELS:
        model_type = model_config["model_type"]
        variant = model_config["variant"]
        # NOTE: this string uses "/" while the canonical model_id elsewhere
        # uses "-". Preserved for wire-compat with the existing Swift decoder.
        ui_id = f"{model_type}/{variant}"

        is_installed = model_service.is_model_downloaded(model_type, variant)
        if not is_installed:
            all_installed = False

        models.append(
            StarterModelInfo(
                model_type=model_type,
                variant=variant,
                model_id=ui_id,
                description=model_config["description"],
                is_installed=is_installed,
            )
        )

    return StarterModelsResponse(
        models=models, all_installed=all_installed, downloads_started=0
    )


@router.post("/start-starter-downloads")
async def start_starter_model_downloads(
    http_request: Request,
    model_service: ModelService = Depends(get_model_service),
) -> StarterModelsResponse:
    """Enqueue every not-yet-installed starter model into `DownloadManager`.

    Sequential ordering is preserved by `DownloadManager`'s semaphore
    (`MODEL_DOWNLOAD_MAX_CONCURRENT`, default 1). Idempotent: calling this
    repeatedly while downloads are in flight is a no-op per the manager's
    `start()` dedup logic.
    """
    manager = _get_download_manager(http_request)

    sorted_models = sorted(STARTER_MODELS, key=lambda x: x.get("priority", 99))

    models: List[StarterModelInfo] = []
    downloads_started = 0
    all_installed = True

    for model_config in sorted_models:
        model_type = model_config["model_type"]
        variant = model_config["variant"]
        canonical_id = f"{model_type}-{variant}"
        ui_id = f"{model_type}/{variant}"

        is_installed = model_service.is_model_downloaded(model_type, variant)
        if not is_installed:
            all_installed = False
            try:
                entry = await manager.start(model_type, variant)
                # `start()` returns an entry whose status is one of:
                #   * "queued" / "downloading" -> we just enqueued or it was
                #     already in flight from a prior call (idempotent).
                #   * "skipped_installed" -> raced with an install completion;
                #     don't count it as a fresh dispatch.
                if entry.status != "skipped_installed":
                    downloads_started += 1
            except Exception as exc:
                api_logger.error(
                    f"[Onboarding] Failed to enqueue starter model {canonical_id}: {exc}"
                )
        else:
            api_logger.info(
                f"[Onboarding] Starter model already installed: {canonical_id}"
            )

        models.append(
            StarterModelInfo(
                model_type=model_type,
                variant=variant,
                model_id=ui_id,
                description=model_config["description"],
                is_installed=is_installed,
                task_id=canonical_id if not is_installed else None,
            )
        )

    if downloads_started:
        api_logger.info(
            f"[Onboarding] Enqueued {downloads_started} starter model download(s)"
        )
    elif all_installed:
        api_logger.info("[Onboarding] All starter models already installed")

    return StarterModelsResponse(
        models=models,
        all_installed=all_installed,
        downloads_started=downloads_started,
    )


@router.get("/download-progress")
async def get_all_download_progress(
    http_request: Request,
    model_service: ModelService = Depends(get_model_service),
) -> Dict[str, Any]:
    """Aggregate progress for the starter model pack.

    Per-model progress comes from `DownloadManager` (in-memory). Already-
    installed models are reported as 100% completed without consulting the
    manager. The aggregate "phase_message" is what the onboarding UI
    displays at the top of the screen and follows the same thresholds as
    before.
    """
    manager = _get_download_manager(http_request)

    progress_data: Dict[str, Dict[str, Any]] = {}
    total_models = len(STARTER_MODELS)
    completed_models = 0
    total_progress = 0.0

    for model_config in STARTER_MODELS:
        model_type = model_config["model_type"]
        variant = model_config["variant"]
        model_id = f"{model_type}-{variant}"
        description = model_config["description"]

        if model_service.is_model_downloaded(model_type, variant):
            completed_models += 1
            total_progress += 100.0
            progress_data[model_id] = {
                "status": "completed",
                "progress": 100.0,
                "description": description,
            }
            continue

        entry = manager.get_by_pair(model_type, variant)
        if entry is None:
            progress_data[model_id] = {
                "status": "pending",
                "progress": 0.0,
                "description": description,
            }
            continue

        # Treat user_canceled as pending so the UI lets the user retry from
        # zero (matches the prior behavior).
        status = entry.status if entry.status != "user_canceled" else "pending"
        progress_pct = entry.progress * 100 if status != "pending" else 0.0
        total_progress += progress_pct

        record: Dict[str, Any] = {
            "status": status,
            "progress": progress_pct,
            "description": description,
        }
        if entry.bytes_downloaded:
            record["total_downloaded"] = entry.bytes_downloaded
        if entry.total_bytes:
            record["total_size"] = entry.total_bytes
        progress_data[model_id] = record

    overall_progress = total_progress / total_models if total_models else 0
    all_complete = completed_models == total_models

    if all_complete:
        phase_message = "Ready!"
    elif completed_models == 0:
        phase_message = "Learning to listen..."
    elif completed_models == 1:
        phase_message = "Improving accuracy..."
    else:
        phase_message = "Learning to think..."

    return {
        "overall_progress": overall_progress,
        "all_complete": all_complete,
        "completed_models": completed_models,
        "total_models": total_models,
        "phase_message": phase_message,
        "models": progress_data,
    }
