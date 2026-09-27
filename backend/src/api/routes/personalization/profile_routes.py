"""Profile and context routes for personalization."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from api.core.knowledge.personalization_models import (
    ContextType,
    PersonalizationContext,
    UserProfile,
    UserProfileCreate,
)
from api.core.knowledge.personalization_service import PersonalizationService

from .dependencies import get_personalization_service
from .models import DeleteResponse


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/profile", response_model=UserProfile)
async def get_user_profile(
    service: PersonalizationService = Depends(get_personalization_service)
):
    """Get user profile.
    
    Returns:
        UserProfile if exists, otherwise returns default empty profile
    """
    try:
        profile = await service.get_user_profile()
        
        # Verbose diagnostics: always log what we're about to return
        try:
            safe_profile = None
            if profile is not None:
                # Pydantic model -> dict for readable logging
                safe_profile = profile.dict()
            logger.info(f"[PERSONALIZATION][GET:/user/profile] Resolved profile: {safe_profile}")
        except Exception as log_err:
            logger.warning(f"[PERSONALIZATION][GET:/user/profile] Failed to log profile: {log_err}")

        if profile is None:
            # Return minimal default profile
            return UserProfile(
                id="default",
                full_name=None,
                preferred_name=None,
                email=None,
                job_title=None,
                company_name=None,
                industry=None,
                default_formality=None,
                default_tone=None
            )
        
        return profile
    
    except Exception as e:
        logger.error(f"Error getting user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get user profile: {str(e)}")


@router.post("/profile", response_model=UserProfile)
async def create_or_update_profile(
    profile_data: UserProfileCreate,
    service: PersonalizationService = Depends(get_personalization_service)
):
    """Create or update user profile.
    
    Args:
        profile_data: Profile data to create/update
        
    Returns:
        Updated UserProfile
    """
    try:
        # Log incoming payload for end-to-end traceability
        try:
            logger.info(f"[PERSONALIZATION][POST:/user/profile] Incoming payload: {profile_data.dict()}")
        except Exception as log_err:
            logger.warning(f"[PERSONALIZATION][POST:/user/profile] Failed to log incoming payload: {log_err}")

        profile = await service.create_or_update_user_profile(profile_data)

        # Log saved profile
        try:
            logger.info(f"[PERSONALIZATION][POST:/user/profile] Saved profile: {profile.dict()}")
        except Exception as log_err:
            logger.warning(f"[PERSONALIZATION][POST:/user/profile] Failed to log saved profile: {log_err}")

        logger.info(f"Profile updated for user: {profile.id}")
        return profile
    
    except Exception as e:
        logger.error(f"Error updating user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update user profile: {str(e)}")


@router.get("/personalization-context", response_model=PersonalizationContext)
async def get_personalization_context(
    context_type: str = "email_reply",
    recipient: Optional[str] = None,
    service: PersonalizationService = Depends(get_personalization_service)
) -> PersonalizationContext:
    """Get complete personalization context for a given context type.
    
    Args:
        context_type: Context type (email_reply, slack, document, etc.)
        recipient: Optional recipient email for relationship context
        
    Returns:
        PersonalizationContext with profile, style, samples, contact info
    """
    try:
        # Validate and convert context_type
        try:
            ctx_type = ContextType(context_type)
        except ValueError:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid context_type: {context_type}. Must be one of: {[e.value for e in ContextType]}"
            )
        
        context = await service.build_personalization_context(
            context_type=ctx_type,
            recipient=recipient
        )
        
        return context
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error building personalization context: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to build personalization context: {str(e)}")


@router.delete("/profile", response_model=DeleteResponse)
async def delete_user_profile(
    service: PersonalizationService = Depends(get_personalization_service)
) -> DeleteResponse:
    """Delete user profile and all personalization data.
    
    WARNING: This deletes all learned data including writing samples,
    communication styles, and contact relationships.
    
    Returns:
        Success message
    """
    try:
        async with service._get_connection() as conn:
            # Delete all personalization data for default user
            user_id = "default"
            
            await conn.execute("DELETE FROM personalization_insights WHERE user_id = ?", (user_id,))
            await conn.execute("DELETE FROM user_signatures WHERE user_id = ?", (user_id,))
            await conn.execute("DELETE FROM contact_relationships WHERE user_id = ?", (user_id,))
            await conn.execute("DELETE FROM writing_samples WHERE user_id = ?", (user_id,))
            await conn.execute("DELETE FROM communication_style_profile WHERE user_id = ?", (user_id,))
            await conn.execute("DELETE FROM user_profile WHERE id = ?", (user_id,))
            
            await conn.commit()
            
            logger.info(f"Deleted all personalization data for user: {user_id}")
            
            return DeleteResponse(
                success=True,
                message="All personalization data deleted successfully"
            )
    
    except Exception as e:
        logger.error(f"Error deleting user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete user profile: {str(e)}")
