"""Validation-session helpers for the Setup Assistant's local model step.

Everything here is inert outside a validation session: the model chooser is empty and the copy route answers 404, so a normal build never shows or exposes either one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.core.logging.api_logger import api_logger
from api.core.models.model_download.disk_space import InsufficientDiskSpaceError
from api.core.models.model_download.validation_model_copy import source_has_model
from api.core.models.models_registry import is_in_registry
from api.core.runtime.validation_profile import (
    ValidationRuntimeConfigurationError,
    ValidationRuntimeProfile,
    is_validation_runtime,
)
from api.routes.model_routes.predefined_routes import _get_download_manager
from api.routes.setup_assistant.models import SetupAgentLocalModelChoice
from api.settings import get_models_dir

router = APIRouter(prefix="/model-access/validation", tags=["Setup Assistant"])

# The reasoning models a tester can pick between in a validation session, largest first. The machine's own recommendation and anything already installed are added to this list.
VALIDATION_LOCAL_MODEL_CHOICE_IDS = (
    "Qwen-qwen36-35b-a3b-mlx-4bit",
    "Qwen-qwen35-9b-mlx-4bit",
    "Qwen-qwen35-4b-mlx-4bit",
)


def validation_profile_or_none() -> Optional[ValidationRuntimeProfile]:
    """The validation profile when this backend is a validation session, otherwise None."""
    if not is_validation_runtime():
        return None
    try:
        return ValidationRuntimeProfile.from_environment()
    except ValidationRuntimeConfigurationError:
        return None


def copy_source_root_or_none() -> Optional[Path]:
    """The normal Basil's model folder when this session may copy from it, otherwise None."""
    profile = validation_profile_or_none()
    root = profile.copy_source_models_root if profile else None
    return root if root is not None and root.is_dir() else None


def can_copy_from_normal_basil(model_id: Optional[str]) -> bool:
    """Whether the normal Basil's model folder holds a complete copy of this model."""
    root = copy_source_root_or_none()
    if root is None or not model_id:
        return False
    return source_has_model(model_id, root, get_models_dir())


def validation_local_model_choices(
    local_models: Dict[str, Dict[str, Any]],
    machine_default: Optional[str],
    installed_ids: List[str],
    is_downloaded: Any,
) -> List[SetupAgentLocalModelChoice]:
    """The chooser list for a validation session, or an empty list outside one."""
    if validation_profile_or_none() is None:
        return []
    ordered: List[str] = []
    for model_id in (*VALIDATION_LOCAL_MODEL_CHOICE_IDS, machine_default, *installed_ids):
        if model_id and model_id in local_models and model_id not in ordered:
            ordered.append(model_id)
    choices: List[SetupAgentLocalModelChoice] = []
    for model_id in ordered:
        config = local_models[model_id]
        model_type, separator, variant = model_id.partition("-")
        if not separator:
            continue
        size_value = config.get("size")
        choices.append(
            SetupAgentLocalModelChoice(
                model_id=model_id,
                model_type=model_type,
                variant=variant,
                display_name=str(config.get("display_name") or model_id),
                size_description=str(size_value) if size_value else None,
                downloaded=bool(is_downloaded(model_type, variant)),
                can_copy_from_normal_basil=can_copy_from_normal_basil(model_id),
            )
        )
    return choices


class CopyModelRequest(BaseModel):
    model_type: str
    variant: str


@router.post("/copy-model")
async def copy_model_from_normal_basil(request: CopyModelRequest, http_request: Request) -> Dict[str, str]:
    """Start copying an installed model from the normal Basil's model folder into this session.

    Progress is read from the usual download progress routes, because the copy runs as a download-manager entry.
    """
    source_root = copy_source_root_or_none()
    if source_root is None:
        raise HTTPException(status_code=404, detail="Copying from your normal Basil is not available in this session.")
    model_id = f"{request.model_type}-{request.variant}"
    if not is_in_registry(model_id):
        raise HTTPException(status_code=404, detail=f"Model {request.model_type}/{request.variant} not found")
    if not can_copy_from_normal_basil(model_id):
        raise HTTPException(status_code=404, detail="Your normal Basil does not have a complete copy of that model.")
    manager = _get_download_manager(http_request)
    try:
        entry = await manager.start(request.model_type, request.variant, copy_source_root=source_root)
    except InsufficientDiskSpaceError as exc:
        raise HTTPException(status_code=507, detail=str(exc))
    except Exception as exc:
        api_logger.error("Failed to start copying %s: %s", model_id, exc)
        raise HTTPException(status_code=500, detail=f"Failed to start copying: {exc}")
    return {"model_id": entry.model_id, "status": entry.status}
