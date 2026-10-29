"""Style analysis routes for personalization."""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

from api.core.knowledge.personalization_models import ContextType
from api.core.knowledge.personalization_service import PersonalizationService

from .dependencies import get_personalization_service
from .models import StyleAnalysisAllResponse, StyleAnalysisResponse


logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================================
# STYLE ANALYSIS
# ============================================================================

@router.post("/style/analyze/{context_type}", response_model=StyleAnalysisResponse)
async def analyze_communication_style(
    context_type: str,
    force_reanalysis: bool = False,
    service: PersonalizationService = Depends(get_personalization_service)
) -> StyleAnalysisResponse:
    """
    Analyze writing samples and update communication style profile for a specific context.
    
    Args:
        context_type: Context type to analyze (email_reply, slack, document, etc.)
        force_reanalysis: If True, reanalyze even if recent analysis exists
        
    Returns:
        Updated CommunicationStyleProfile or error if no samples
    """
    try:
        # Convert string to enum
        try:
            enum_context_type = ContextType(context_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid context_type: {context_type}")
        
        logger.info(f"Analyzing communication style for context: {context_type}")
        
        profile = await service.analyze_and_update_style(
            context_type=enum_context_type,
            force_reanalysis=force_reanalysis
        )
        
        if profile is None:
            raise HTTPException(
                status_code=404,
                detail=f"No writing samples found for context: {context_type}"
            )
        
        logger.info(
            f"Style analysis complete for {context_type}: "
            f"confidence={profile.confidence:.2f}, samples={profile.sample_count}"
        )
        
        return StyleAnalysisResponse(
            success=True,
            context_type=context_type,
            profile=profile.dict(),
            message=f"Analyzed {profile.sample_count} samples with {profile.confidence:.0%} confidence"
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing communication style: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to analyze style: {str(e)}")


@router.post("/style/analyze-all", response_model=StyleAnalysisAllResponse)
async def analyze_all_communication_styles(
    service: PersonalizationService = Depends(get_personalization_service)
) -> StyleAnalysisAllResponse:
    """
    Analyze and update style profiles for all contexts that have writing samples.
    
    Returns:
        Dict with results for each context type
    """
    try:
        logger.info("Analyzing all communication styles")
        
        results = await service.analyze_all_contexts()
        
        # Format results
        formatted_results = {}
        for context_type, profile in results.items():
            if profile:
                formatted_results[context_type] = {
                    "success": True,
                    "confidence": profile.confidence,
                    "sample_count": profile.sample_count,
                    "profile": profile.dict()
                }
            else:
                formatted_results[context_type] = {
                    "success": False,
                    "message": "No samples found"
                }
        
        analyzed_count = sum(1 for r in formatted_results.values() if r.get("success"))
        
        logger.info(f"Analyzed {analyzed_count} context types")
        
        return StyleAnalysisAllResponse(
            success=True,
            analyzed_contexts=analyzed_count,
            results=formatted_results,
            message=f"Analyzed {analyzed_count} context type(s)"
        )
    
    except Exception as e:
        logger.error(f"Error analyzing all communication styles: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to analyze styles: {str(e)}")


@router.get("/style/{context_type}", response_model=Optional[Dict[str, Any]])
async def get_communication_style(
    context_type: str,
    service: PersonalizationService = Depends(get_personalization_service)
) -> Optional[Dict[str, Any]]:
    """
    Get communication style profile for a specific context.
    
    Args:
        context_type: Context type (email_reply, slack, document, etc.)
        
    Returns:
        CommunicationStyleProfile or null if not found (200 OK with null is expected for new users)
    """
    try:
        # Convert string to enum
        try:
            enum_context_type = ContextType(context_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid context_type: {context_type}")
        
        profile = await service.get_communication_style(enum_context_type)
        
        # Return null if no profile exists yet - this is expected for new users or contexts without samples
        if profile is None:
            return None
        
        return profile.dict()
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting communication style: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get style: {str(e)}")
