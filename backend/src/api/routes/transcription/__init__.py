"""Transcription route package entrypoint."""

from fastapi import APIRouter

from .history_routes import router as history_router
from .record_routes import router as record_router
from .upload_routes import router as upload_router


router = APIRouter()
router.include_router(upload_router)
router.include_router(history_router)
router.include_router(record_router)


__all__ = ["router"]
