"""Writing sample routes for personalization."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from api.core.knowledge.personalization_models import ContextType, SourceType
from api.core.knowledge.personalization_service import PersonalizationService

from .dependencies import get_personalization_service
from .models import (
    DeleteResponse,
    DeleteWithCountResponse,
    SaveWritingSampleRequest,
    SaveWritingSampleResponse,
    UpdateWritingSampleRequest,
    UpdateWritingSampleResponse,
    WritingSamplesCountResponse,
    WritingSamplesListResponse,
)


logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# WRITING SAMPLES MANAGEMENT
# ============================================================================

@router.post("/writing-samples", response_model=SaveWritingSampleResponse)
async def save_writing_sample(
    request: SaveWritingSampleRequest,
    service: PersonalizationService = Depends(get_personalization_service)
) -> SaveWritingSampleResponse:
    """Save content as a writing sample for personalization.
    
    This endpoint allows saving suggestion outputs (from voice or regular suggestions)
    as writing samples that can be used for future personalization.
    
    Args:
        request: SaveWritingSampleRequest containing:
            - content: The text content to save as a sample
            - context_type: Type of context (email_reply, email_compose, document, etc.)
            - recipient: Optional recipient email for relationship tracking
            - metadata: Optional additional metadata
            
    Returns:
        SaveWritingSampleResponse with sample_id and status
    """
    try:
        logger.info(f"📝 [PERSONALIZATION] Saving writing sample: context_type={request.context_type}")
        
        # Map string context_type to ContextType enum
        context_type_map = {
            "email_reply": ContextType.EMAIL_REPLY,
            "email_compose": ContextType.EMAIL_COMPOSE,
            "email_generic": ContextType.EMAIL_REPLY,
            "document": ContextType.DOCUMENT,
            "social_media": ContextType.SOCIAL_MEDIA,
            "code": ContextType.DOCUMENT,
            "unknown": ContextType.DOCUMENT,
        }
        
        enum_context_type = context_type_map.get(request.context_type, ContextType.DOCUMENT)
        source_type_map = {
            "manual_entry": SourceType.MANUAL_ENTRY,
            "suggestion_accepted": SourceType.SUGGESTION_ACCEPTED,
        }
        source_type = source_type_map.get(request.source_type or "suggestion_accepted", SourceType.SUGGESTION_ACCEPTED)
        
        # Save as writing sample
        sample = await service.add_writing_sample(
            content=request.content,
            source_type=source_type,
            context_type=enum_context_type,
            recipient=request.recipient,
            auto_analyze_style=source_type != SourceType.MANUAL_ENTRY
        )
        
        logger.info(f"📝 [PERSONALIZATION] Saved writing sample: id='{sample.id}' context='{request.context_type}'")
        
        return SaveWritingSampleResponse(
            status="saved",
            sample_id=sample.id,
            context_type=request.context_type,
            signature_detected=False,
            contact_tracked=False
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving writing sample: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save writing sample: {str(e)}")


@router.get("/writing-samples/count", response_model=WritingSamplesCountResponse)
async def get_writing_samples_count(
    context_type: Optional[str] = None,
    service: PersonalizationService = Depends(get_personalization_service)
) -> WritingSamplesCountResponse:
    """Get count of writing samples.
    
    Args:
        context_type: Optional filter by context type (email_reply, social_media, document, etc.)
        
    Returns:
        {"count": int}
    """
    try:
        # Convert string to enum if provided
        enum_context_type = None
        if context_type:
            try:
                enum_context_type = ContextType(context_type)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid context_type: {context_type}")
        
        count = await service.get_writing_samples_count(context_type=enum_context_type)
        
        return WritingSamplesCountResponse(count=count)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting writing samples count: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get writing samples count: {str(e)}")


@router.get("/writing-samples", response_model=WritingSamplesListResponse)
async def list_writing_samples(
    context_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    service: PersonalizationService = Depends(get_personalization_service)
) -> WritingSamplesListResponse:
    """List writing samples with pagination.
    
    Args:
        context_type: Optional filter by context type
        limit: Maximum number of samples (default 50, max 100)
        offset: Number of samples to skip (for pagination)
        
    Returns:
        {
            "samples": [WritingSample],
            "total": int,
            "limit": int,
            "offset": int
        }
    """
    try:
        # Validate and cap limit
        if limit > 100:
            limit = 100
        if limit < 1:
            limit = 1
        if offset < 0:
            offset = 0
        
        # Convert string to enum if provided
        enum_context_type = None
        if context_type:
            try:
                enum_context_type = ContextType(context_type)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid context_type: {context_type}")
        
        # Get samples and total count
        samples = await service.list_writing_samples(
            context_type=enum_context_type,
            limit=limit,
            offset=offset
        )
        total = await service.get_writing_samples_count(context_type=enum_context_type)
        
        return WritingSamplesListResponse(
            samples=[sample.dict() for sample in samples],
            total=total,
            limit=limit,
            offset=offset
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing writing samples: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list writing samples: {str(e)}")


@router.patch("/writing-samples/{sample_id}", response_model=UpdateWritingSampleResponse)
async def update_writing_sample(
    sample_id: str,
    request: UpdateWritingSampleRequest,
    service: PersonalizationService = Depends(get_personalization_service)
) -> UpdateWritingSampleResponse:
    """Update an existing writing sample's content, context type, and recipient."""
    try:
        if not request.content.strip():
            raise HTTPException(status_code=400, detail="Writing sample content cannot be empty")

        context_type = None
        if request.context_type is not None:
            try:
                context_type = ContextType(request.context_type)
            except ValueError:
                context_type = None
            if context_type is None or context_type == ContextType.ALL:
                raise HTTPException(status_code=400, detail=f"Invalid context_type: {request.context_type}")

        update_recipient = "recipient" in request.model_fields_set
        recipient = (request.recipient or "").strip() or None

        updated = await service.update_writing_sample(
            sample_id=sample_id,
            content=request.content,
            context_type=context_type,
            recipient=recipient,
            update_recipient=update_recipient
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Writing sample not found")

        return UpdateWritingSampleResponse(
            status="updated",
            sample_id=updated.id,
            content=updated.content,
            context_type=ContextType(updated.context_type).value,
            recipient=updated.recipient
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating writing sample: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update writing sample: {str(e)}")


@router.delete("/writing-samples/{sample_id}", response_model=DeleteResponse)
async def delete_writing_sample(
    sample_id: str,
    service: PersonalizationService = Depends(get_personalization_service)
) -> DeleteResponse:
    """Delete a specific writing sample.
    
    Args:
        sample_id: ID of the sample to delete
        
    Returns:
        {"success": bool, "message": str}
    """
    try:
        deleted = await service.delete_writing_sample(sample_id)
        
        if not deleted:
            raise HTTPException(status_code=404, detail="Writing sample not found")
        
        logger.info(f"Deleted writing sample: {sample_id}")
        
        return DeleteResponse(
            success=True,
            message="Writing sample deleted successfully"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting writing sample: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete writing sample: {str(e)}")


@router.delete("/writing-samples", response_model=DeleteWithCountResponse)
async def delete_all_writing_samples(
    context_type: Optional[str] = None,
    service: PersonalizationService = Depends(get_personalization_service)
) -> DeleteWithCountResponse:
    """Delete all writing samples, optionally filtered by context type.
    
    Args:
        context_type: Optional filter by context type
        
    Returns:
        {"success": bool, "count": int, "message": str}
    """
    try:
        # Convert string to enum if provided
        enum_context_type = None
        if context_type:
            try:
                enum_context_type = ContextType(context_type)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid context_type: {context_type}")
        
        count = await service.delete_all_writing_samples(context_type=enum_context_type)
        
        logger.info(f"Deleted {count} writing samples" + (f" (context: {context_type})" if context_type else ""))
        
        return DeleteWithCountResponse(
            success=True,
            count=count,
            message=f"Deleted {count} writing sample(s)"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting all writing samples: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete writing samples: {str(e)}")
