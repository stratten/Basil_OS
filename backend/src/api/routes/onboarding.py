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

from ..core.models.model_download.disk_space import InsufficientDiskSpaceError, larger_model_blocked_message
from ..core.services.model_download_manager import DownloadManager
from ..core.logging.api_logger import api_logger
from ..core.services.model_service import ModelService
from ..dependencies import get_model_service

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


# The starter model pack downloads automatically on first launch. The two transcription models are fixed. The reasoning model comes from get_starter_models().
_TRANSCRIPTION_STARTER_MODELS = [
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
]

# The two builds of each starter reasoning model, MLX first. Either build being installed satisfies the pack, so an install that already has one never downloads the other. The 4B pair is what a Mac with too little memory for the 9B receives, and the 35B pair is what a Mac with enough memory for it receives.
_REASONING_STARTER_EQUIVALENTS_BY_MODEL = (
    ("Qwen-qwen36-35b-a3b-mlx-4bit", "Qwen-qwen36-35b-a3b-ud-q4km"),
    ("Qwen-qwen35-9b-mlx-4bit", "Qwen-qwen35-9b-q4km"),
    ("Qwen-qwen35-4b-mlx-4bit", "Qwen-qwen35-4b-q4km"),
)
_REASONING_STARTER_FALLBACK_ID = "Qwen-qwen35-9b-q4km"


def get_starter_models(model_service: Any) -> List[Dict[str, Any]]:
    """Return the first-launch download pack.

    The reasoning model is the registry's onboarding default for this machine: the MLX build on an Apple Silicon Mac that can run MLX, the GGUF build everywhere else, the 4B model instead of the 9B on a Mac with less memory than the 9B declares it needs, and the 35B model instead of the 9B on an MLX Mac with at least the memory the 9B names for that upgrade. If the other build of that model is already installed, that build is reported instead, so first launch never downloads a second copy of a model the user already has.
    """
    from ..core.models.models_registry import get_model
    from ..core.models.preference_models.defaults import _get_default_local_reasoning_model_id

    chosen_id = _get_default_local_reasoning_model_id() or _REASONING_STARTER_FALLBACK_ID
    equivalents = next((pair for pair in _REASONING_STARTER_EQUIVALENTS_BY_MODEL if chosen_id in pair), ())
    if equivalents:
        for candidate_id in equivalents:
            if get_model(candidate_id) is None:
                continue
            candidate_type, candidate_variant = candidate_id.split("-", 1)
            if model_service.is_model_downloaded(candidate_type, candidate_variant):
                chosen_id = candidate_id
                break
    model_type, variant = chosen_id.split("-", 1)
    size = (get_model(chosen_id) or {}).get("size")
    description = f"Reasoning model for suggestions ({size})" if size else "Reasoning model for suggestions"
    return [
        *_TRANSCRIPTION_STARTER_MODELS,
        {"model_type": model_type, "variant": variant, "priority": 3, "description": description},
    ]


def starter_disk_warnings() -> List[str]:
    """Warn when this Mac has the memory for the larger starter model but not the free disk space for it.

    The starter pack then holds the smaller model, so the person using the app is told what they would gain by freeing space. The free space is read each time, so freeing it clears the warning on the next call.
    """
    from ..core.models.models_registry import get_model
    from ..core.models.preference_models.defaults import _choose_local_reasoning_model

    choice = _choose_local_reasoning_model()
    if not choice.blocked_by_disk or choice.required_disk_gb is None or choice.free_disk_gb is None:
        return []
    preferred = get_model(choice.preferred_model_id) or {}
    fallback = get_model(choice.model_id) or {}
    return [
        larger_model_blocked_message(
            str(preferred.get("display_name") or choice.preferred_model_id),
            str(fallback.get("display_name") or choice.model_id),
            choice.required_disk_gb,
            choice.free_disk_gb,
        )
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
    # Plain-language notices for the person using the app, such as a larger model held back by free disk space. Empty when there is nothing to say.
    warnings: List[str] = []


@router.get("/starter-models")
async def get_starter_models_status(
    model_service: ModelService = Depends(get_model_service),
) -> StarterModelsResponse:
    """Status of starter models without starting downloads."""
    models: List[StarterModelInfo] = []
    all_installed = True

    for model_config in get_starter_models(model_service):
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
        models=models,
        all_installed=all_installed,
        downloads_started=0,
        warnings=starter_disk_warnings(),
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

    sorted_models = sorted(get_starter_models(model_service), key=lambda x: x.get("priority", 99))

    models: List[StarterModelInfo] = []
    downloads_started = 0
    all_installed = True
    warnings = starter_disk_warnings()

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
            except InsufficientDiskSpaceError as exc:
                api_logger.warning(f"[Onboarding] Not enough disk space for starter model {canonical_id}: {exc}")
                warnings.append(str(exc))
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
        warnings=warnings,
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
    starter_models = get_starter_models(model_service)
    total_models = len(starter_models)
    completed_models = 0
    total_progress = 0.0

    for model_config in starter_models:
        model_type = model_config["model_type"]
        variant = model_config["variant"]
        model_id = f"{model_type}-{variant}"
        description = model_config["description"]
        from ..core.models.models_registry import get_model as get_registry_model
        from .setup_assistant.validation_model_routes import can_copy_from_normal_basil

        display_name = str((get_registry_model(model_id) or {}).get("display_name") or model_id)
        # True only in a fresh validation session whose normal Basil holds this model, so the setup page can offer a copy.
        can_copy = can_copy_from_normal_basil(model_id)

        if model_service.is_model_downloaded(model_type, variant):
            completed_models += 1
            total_progress += 100.0
            progress_data[model_id] = {
                "status": "completed",
                "progress": 100.0,
                "description": description,
                "display_name": display_name,
                "can_copy_from_normal_basil": can_copy,
            }
            continue

        entry = manager.get_by_pair(model_type, variant)
        if entry is None:
            progress_data[model_id] = {
                "status": "pending",
                "progress": 0.0,
                "description": description,
                "display_name": display_name,
                "can_copy_from_normal_basil": can_copy,
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
            "display_name": display_name,
            "can_copy_from_normal_basil": can_copy,
        }
        if entry.bytes_downloaded:
            record["total_downloaded"] = entry.bytes_downloaded
        if entry.total_bytes:
            record["total_size"] = entry.total_bytes
        if status in ("queued", "downloading") and entry.message:
            # The setup page shows this line under the bar while nothing has downloaded yet, such as "Waiting for Hugging Face to start sending data (20s)...".
            record["message"] = entry.message
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


class SmallerReasoningModelResponse(BaseModel):
    """Result of asking Basil to move to a smaller local reasoning model."""

    status: str
    model_id: str | None = None
    message: str


@router.post("/use-smaller-reasoning-model")
async def use_smaller_reasoning_model(
    http_request: Request,
    model_service: ModelService = Depends(get_model_service),
) -> SmallerReasoningModelResponse:
    """Move the reasoning model to the smaller local model its registry entry names, after a failure to run the current one.

    Idempotent, so the setup UI can call it again while the download runs: once the smaller model is installed the call switches the preference and reports ``switched``.
    ``downloading`` means the download was started or is already running, and ``unavailable`` means no smaller local model exists for the current one.
    """
    from ..core.models.models_registry import get_model
    from ..core.preferences.preferences_io import load_preferences, save_preferences

    preferences = load_preferences()
    current_id = preferences.models.reasoning_model
    fallback_id = (get_model(current_id) or {}).get("onboarding_low_memory_fallback")
    if not fallback_id or get_model(fallback_id) is None:
        return SmallerReasoningModelResponse(
            status="unavailable",
            message="There is no smaller local model for this one. Use Basil Cloud or your own API key instead.",
        )

    model_type, variant = fallback_id.split("-", 1)
    size = (get_model(fallback_id) or {}).get("size")
    if model_service.is_model_downloaded(model_type, variant):
        preferences.models.reasoning_model = fallback_id
        save_preferences(preferences)
        api_logger.info(f"[Onboarding] Switched reasoning model from {current_id} to {fallback_id}")
        return SmallerReasoningModelResponse(
            status="switched",
            model_id=fallback_id,
            message="Basil is now using a smaller model on this Mac.",
        )

    manager = _get_download_manager(http_request)
    try:
        await manager.start(model_type, variant)
    except InsufficientDiskSpaceError as exc:
        api_logger.warning(f"[Onboarding] Not enough disk space for {fallback_id}: {exc}")
        return SmallerReasoningModelResponse(status="unavailable", model_id=fallback_id, message=str(exc))
    except Exception as exc:
        api_logger.error(f"[Onboarding] Failed to start download of {fallback_id}: {exc}")
        return SmallerReasoningModelResponse(
            status="unavailable",
            model_id=fallback_id,
            message="Basil could not start downloading the smaller model. Check your connection and try again.",
        )
    return SmallerReasoningModelResponse(
        status="downloading",
        model_id=fallback_id,
        message=f"Downloading a smaller model{f' ({size})' if size else ''}. Basil will switch to it when it finishes.",
    )
