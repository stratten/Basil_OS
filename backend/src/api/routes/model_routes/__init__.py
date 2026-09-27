"""Model route package exports."""

from .custom_routes import router as custom_models_router
from .management_routes import router as model_management_router
from .predefined_routes import router as models_router
from .testing_routes import router as model_testing_router

__all__ = [
    "models_router",
    "model_management_router",
    "custom_models_router",
    "model_testing_router",
]
