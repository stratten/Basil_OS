"""Runtime capture route package exports."""

from .activity_routes import router as activity_capture_router
from .management_routes import router as capture_management_router
from .manual_routes import router as manual_capture_router
from .window_routes import router as capture_router

__all__ = [
    "activity_capture_router",
    "capture_management_router",
    "capture_router",
    "manual_capture_router",
]
