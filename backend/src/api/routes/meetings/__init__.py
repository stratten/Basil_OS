"""Meetings route package entrypoint."""

from fastapi import APIRouter

from .analysis_routes import router as analysis_router
from .lifecycle_routes import router as lifecycle_router
from .live_transcription_routes import router as live_transcription_router
from .post_processing_routes import router as post_processing_router
from .search_routes import router as search_router


router = APIRouter()
# Register search BEFORE lifecycle so GET /meetings/search is matched ahead of
# the catch-all GET /meetings/{meeting_id} (which would otherwise treat
# "search" as a meeting id).
router.include_router(search_router, prefix="/meetings", tags=["meetings"])
router.include_router(lifecycle_router, prefix="/meetings", tags=["meetings"])
router.include_router(post_processing_router, prefix="/meetings", tags=["meetings"])
router.include_router(analysis_router, prefix="/meetings", tags=["meetings"])


__all__ = ["live_transcription_router", "router"]
