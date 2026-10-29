"""Meetings route package entrypoint."""

from fastapi import APIRouter

from .analysis_routes import router as analysis_router
from .cloud_transcription_routes import router as cloud_transcription_router
from .companion_routes import router as companion_router
from .lifecycle_routes import router as lifecycle_router
from .live_transcription_routes import router as live_transcription_router
from .post_processing_routes import router as post_processing_router
from .resource_advice_routes import router as resource_advice_router
from .search_routes import router as search_router


router = APIRouter()
# Register search BEFORE lifecycle so GET /meetings/search is matched ahead of
# the catch-all GET /meetings/{meeting_id} (which would otherwise treat
# "search" as a meeting id).
router.include_router(search_router, prefix="/meetings", tags=["meetings"])
# Register the Companion router BEFORE lifecycle so literal paths such as
# /meetings/companion/settings are never captured by /meetings/{meeting_id} routes.
router.include_router(companion_router, prefix="/meetings", tags=["meetings"])
# Likewise register the resource advice router before lifecycle so /meetings/resource-advice is never read as a meeting id.
router.include_router(resource_advice_router, prefix="/meetings", tags=["meetings"])
# Likewise register the cloud transcription router before lifecycle so /meetings/cloud-transcription is never read as a meeting id.
router.include_router(cloud_transcription_router, prefix="/meetings", tags=["meetings"])
router.include_router(lifecycle_router, prefix="/meetings", tags=["meetings"])
router.include_router(post_processing_router, prefix="/meetings", tags=["meetings"])
router.include_router(analysis_router, prefix="/meetings", tags=["meetings"])


__all__ = ["live_transcription_router", "router"]
