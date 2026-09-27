"""Personalization route package entrypoint."""

from fastapi import APIRouter

from .mac_contacts_routes import router as mac_contacts_router
from .profile_routes import router as profile_router
from .style_routes import router as style_router
from .writing_sample_routes import router as writing_sample_router


router = APIRouter(tags=["personalization"])
user_router = APIRouter(prefix="/user", tags=["personalization"])
user_router.include_router(profile_router)
user_router.include_router(writing_sample_router)
user_router.include_router(style_router)

router.include_router(user_router)
router.include_router(mac_contacts_router)


__all__ = ["router"]
