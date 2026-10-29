"""History and search endpoints for transcriptions."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query

from .dependencies import transcription_repository
from .models import TranscriptionHistoryResponse, TranscriptionSearchResponse


logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/transcription/history", response_model=TranscriptionHistoryResponse)
async def get_transcription_history(
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    days: Optional[int] = Query(None, ge=1, le=365)
) -> TranscriptionHistoryResponse:
    """
    Get transcription history.
    
    Args:
        limit: Maximum number of transcriptions to retrieve
        offset: Number of transcriptions to skip
        days: Only retrieve transcriptions from the last N days
        
    Returns:
        List of transcription records
    """
    logger.info(f"Transcription history requested - limit: {limit}, offset: {offset}, days: {days}")
    try:
        # Apply date filter if specified
        start_date = None
        if days:
            start_date = datetime.now() - timedelta(days=days)
            logger.info(f"Filtering by start date: {start_date}")
        
        # Get transcriptions
        logger.info("Calling transcription_repository.search_transcriptions")
        transcriptions = await transcription_repository.search_transcriptions(
            start_date=start_date,
            limit=limit
        )
        
        logger.info(f"Found {len(transcriptions)} transcriptions")
        
        # Convert to dictionaries for JSON response
        return TranscriptionHistoryResponse(
            success=True,
            transcriptions=[t.to_dict() for t in transcriptions]
        )
    except Exception as e:
        logger.error(f"Error retrieving transcription history: {e}")
        logger.exception("Detailed exception info:")
        return TranscriptionHistoryResponse(
            success=False,
            error=str(e)
        )


@router.get("/transcription/search", response_model=TranscriptionSearchResponse)
async def search_transcriptions(
    query: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    app: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    edited: Optional[bool] = Query(None),
    rated: Optional[bool] = Query(None),
    days: Optional[int] = Query(None, ge=1, le=365),
    limit: int = Query(50, ge=1, le=100)
) -> TranscriptionSearchResponse:
    """
    Search for transcriptions.
    
    Args:
        query: Text to search for in transcription_text
        model: Filter by model name
        app: Filter by application name
        category: Filter by task category
        edited: Filter by whether the transcription was edited
        rated: Filter by whether the transcription has a user rating
        days: Only retrieve transcriptions from the last N days
        limit: Maximum number of results to return
        
    Returns:
        List of matching transcription records
    """
    try:
        # Apply date filter if specified
        start_date = None
        if days:
            start_date = datetime.now() - timedelta(days=days)
        
        # Search transcriptions
        transcriptions = await transcription_repository.search_transcriptions(
            query=query,
            start_date=start_date,
            model_name=model,
            app_name=app,
            task_category=category,
            was_edited=edited,
            user_rated=rated,
            limit=limit
        )
        
        # Convert to dictionaries for JSON response
        return TranscriptionSearchResponse(
            success=True,
            transcriptions=[t.to_dict() for t in transcriptions]
        )
    except Exception as e:
        logger.error(f"Error searching transcriptions: {e}")
        return TranscriptionSearchResponse(
            success=False,
            error=str(e)
        )
