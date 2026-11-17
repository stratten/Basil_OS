"""Routes for importing personal context from pasted text or a file's text, read by a model."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.core.logging.api_logger import api_logger
from api.routes.setup_assistant.models import SetupAgentModelAccess
from api.services.memory.context_import import get_context_import_service
from api.services.memory.context_import.image_reading import (
    ImageInputError,
    ImageRouteError,
    read_images_as_text,
    validate_images,
)
from api.services.memory.context_import.jobs import ImportBusyError, UnknownJobError
from api.services.memory.context_import.model_access import load_settings_import_model, load_setup_import_model
from api.services.memory.context_import.models import ImportEmptyError, ImportTooLargeError
from api.services.memory.context_import.profile_store import ProfileTooLargeError, UnknownProfileBackupError
from api.services.memory.context_import.service import PreviewExpiredError, UnknownBatchError


router = APIRouter(prefix="/memory/context-import", tags=["memory"])


class ContextImportJobRequest(BaseModel):
    text: str = Field(description="The pasted text, or the text of a chosen file.")
    filename: str = Field(default="", max_length=255, description="The file name, used only as the import's label.")
    label: str = Field(default="", max_length=120, description="A short name for this import, shown in the list of past imports.")


class ImageReadRequest(BaseModel):
    images: List[Dict[str, str]] = Field(description="Screenshots to read, each with mime_type and data_base64.")
    model_access: Optional[SetupAgentModelAccess] = Field(
        default=None,
        description="The route confirmed on the setup model step. When absent, the Settings memory model reads the pictures.",
    )


class ProfileJobRequest(ContextImportJobRequest):
    model_access: Optional[SetupAgentModelAccess] = Field(
        default=None,
        description="The route confirmed on the setup model step. When absent, the Settings memory model reads the text.",
    )


class ContextImportCommitRequest(BaseModel):
    preview_id: str
    categories: List[str] = Field(description="The categories to keep: dated, undated, stable_fact.")


class ProfileCommitRequest(BaseModel):
    draft_id: str
    essentials_md: str = Field(default="", description="The reviewed text for essentials.md. Blank leaves the file unchanged.")
    user_md: str = Field(default="", description="The reviewed text for user.md. Blank leaves the file unchanged.")


def _start_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ImportTooLargeError):
        return HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, ImportEmptyError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, ImportBusyError):
        return HTTPException(status_code=409, detail=str(exc))
    api_logger.error(f"Error starting context import: {exc}", exc_info=True)
    return HTTPException(status_code=500, detail="The import could not be started.")


@router.post("/jobs/records")
async def start_records_import(request: ContextImportJobRequest) -> Dict[str, Any]:
    """Start a model reading the text into memory records. Poll the job, then commit its preview."""
    try:
        return get_context_import_service().start_records_job(request.text, request.filename, request.label, load_settings_import_model)
    except Exception as exc:
        raise _start_error(exc) from exc


@router.post("/jobs/profile")
async def start_profile_import(request: ProfileJobRequest) -> Dict[str, Any]:
    """Start a model reading the text into a reviewable rewrite of the person's profile files."""
    access = request.model_access
    if access is not None and not access.resolved:
        raise HTTPException(status_code=400, detail="Choose how I should think first, then import again.")

    async def load_model():
        return await (load_setup_import_model(access) if access is not None else load_settings_import_model())

    try:
        return get_context_import_service().start_profile_job(request.text, request.filename, request.label, load_model)
    except Exception as exc:
        raise _start_error(exc) from exc


@router.post("/images/read")
async def read_import_images(request: ImageReadRequest) -> Dict[str, Any]:
    """Read screenshots into text for the paste box. A route that cannot read pictures answers 400 with a plain explanation."""
    access = request.model_access
    if access is not None and not access.resolved:
        raise HTTPException(status_code=400, detail="Choose how I should think first, then read the screenshot.")
    try:
        images = validate_images(request.images)
        loaded = await (load_setup_import_model(access) if access is not None else load_settings_import_model())
        text = await read_images_as_text(loaded.model, images)
    except ImageRouteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ImageInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        api_logger.error(f"Error reading import screenshots: {exc}", exc_info=True)
        raise HTTPException(status_code=502, detail="I could not read those pictures just now. Try again, or paste the text instead.") from exc
    return {"text": text}


@router.get("/jobs/{job_id}")
async def read_import_job(job_id: str) -> Dict[str, Any]:
    """Progress, and once finished the result, of one import."""
    try:
        return get_context_import_service().jobs.get(job_id).payload()
    except UnknownJobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/jobs/{job_id}")
async def cancel_import_job(job_id: str) -> Dict[str, Any]:
    """Ask a running import to stop after the part it is reading."""
    try:
        return get_context_import_service().jobs.cancel(job_id).payload()
    except UnknownJobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/commit")
async def commit_context_import(request: ContextImportCommitRequest) -> Dict[str, Any]:
    """Write the chosen categories of a finished records import."""
    try:
        return await asyncio.to_thread(get_context_import_service().commit, request.preview_id, request.categories)
    except PreviewExpiredError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        api_logger.error(f"Error committing context import: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="The import could not be saved.") from exc


@router.post("/profile/commit")
async def commit_profile_import(request: ProfileCommitRequest) -> Dict[str, Any]:
    """Save the reviewed profile text into essentials.md and user.md, keeping a backup to undo from."""
    try:
        return await asyncio.to_thread(get_context_import_service().commit_profile, request.draft_id, request.essentials_md, request.user_md)
    except PreviewExpiredError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProfileTooLargeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        api_logger.error(f"Error saving profile import: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="The profile could not be saved.") from exc


@router.delete("/profile/backups/{backup_id}")
async def undo_profile_import(backup_id: str) -> Dict[str, Any]:
    """Restore the profile files a profile import replaced."""
    try:
        return await asyncio.to_thread(get_context_import_service().undo_profile, backup_id)
    except UnknownProfileBackupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        api_logger.error(f"Error undoing profile import: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="The profile could not be restored.") from exc


@router.get("/batches")
async def list_context_imports() -> Dict[str, Any]:
    """List past imports that can still be undone."""
    try:
        return {"batches": await asyncio.to_thread(get_context_import_service().list_batches)}
    except Exception as exc:
        api_logger.error(f"Error listing context imports: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Past imports could not be listed.") from exc


@router.delete("/batches/{batch_id}")
async def undo_context_import(batch_id: str) -> Dict[str, Any]:
    """Remove every entry that one import added."""
    try:
        return await asyncio.to_thread(get_context_import_service().undo, batch_id)
    except UnknownBatchError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        api_logger.error(f"Error undoing context import: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="The import could not be undone.") from exc
