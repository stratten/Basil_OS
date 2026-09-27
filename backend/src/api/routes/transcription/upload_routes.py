"""Upload/transcription endpoints."""

import logging
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from api.services.transcription.processing.file_transcription_service import transcribe_audio_file

from .models import ALLOWED_AUDIO_TYPES, TranscriptionFileResponse, TranscriptionResponse


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(
    audio: UploadFile = File(...),
    app_name: Optional[str] = Query(None, description="The application name for context"),
    window_title: Optional[str] = Query(None, description="The window title for context"),
    task_category: Optional[str] = Query(None, description="The task category for context")
) -> TranscriptionResponse:
    """
    Handle audio file upload and transcription.
    
    Args:
        audio: The audio file to transcribe
        app_name: Optional application name for context
        window_title: Optional window title for context
        task_category: Optional task category for context
        
    Returns:
        dict: A response containing the transcribed text
        
    Raises:
        HTTPException: If the file is not a valid audio file
    """
    try:
        # Validate content type
        if audio.content_type not in ALLOWED_AUDIO_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Must be one of: {', '.join(ALLOWED_AUDIO_TYPES)}"
            )
        
        # Create a temporary file to store the uploaded audio
        with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as temp_file:
            # Write uploaded file to temp file
            content = await audio.read()
            
            # Basic validation of audio content
            if len(content) < 44:  # Minimum size for a valid WAV header
                raise HTTPException(
                    status_code=400,
                    detail="Invalid audio file: File too small to be valid audio"
                )
            
            temp_file.write(content)
            temp_file_path = temp_file.name
        
        try:
            # Prepare context information
            context_info = {}
            if app_name:
                context_info['app_name'] = app_name
            if window_title:
                context_info['window_title'] = window_title
            if task_category:
                context_info['task_category'] = task_category
                
            # Process the audio file with context
            transcribed_text = await transcribe_audio_file(
                temp_file_path, 
                context_info=context_info or None  # Pass None if empty dict
            )
            
            return TranscriptionResponse(
                success=True,
                text=transcribed_text
            )
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing audio file: {e}")
        return TranscriptionResponse(
            success=False,
            error=str(e)
        )


@router.post("/transcribe/file", response_model=TranscriptionFileResponse)
async def transcribe_file(
    file: UploadFile = File(...),
    description: Optional[str] = Query(None, description="Optional description for the audio file"),
    language: Optional[str] = Query("en", description="Language of the audio (ISO code)"),
    task_category: Optional[str] = Query("audio_file", description="The task category for context")
) -> TranscriptionFileResponse:
    """
    Process an uploaded audio file for transcription.
    
    This endpoint allows users to upload an existing audio file for transcription.
    The file is processed using the same transcription engine as the real-time transcription.
    
    Args:
        file: The audio file to transcribe
        description: Optional description of the audio file content
        language: Language of the audio (defaults to "en" for English)
        task_category: Optional task category (defaults to "audio_file")
        
    Returns:
        dict: A response containing the transcribed text
        
    Raises:
        HTTPException: If the file is not a valid audio file
    """
    try:
        # Validate content type
        content_type = file.content_type
        if content_type not in ALLOWED_AUDIO_TYPES:
            # Try to infer from filename if content_type is not reliable
            filename = file.filename.lower()
            if filename.endswith(('.wav', '.mp3', '.ogg', '.m4a', '.flac', '.aac')):
                logger.info(f"Content type {content_type} not in allowed types, but filename {filename} has valid extension")
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid file type. Must be one of: {', '.join(ALLOWED_AUDIO_TYPES)}"
                )
        
        logger.info(f"Processing uploaded audio file: {file.filename}, size: {file.size}, type: {content_type}")
        
        # Create a temporary file to store the uploaded audio
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            # Write uploaded file to temp file
            content = await file.read()
            
            # Basic validation of audio content
            if len(content) < 44:  # Minimum size for a valid WAV header
                raise HTTPException(
                    status_code=400,
                    detail="Invalid audio file: File too small to be valid audio"
                )
            
            temp_file.write(content)
            temp_file_path = temp_file.name
            
            logger.info(f"Saved uploaded file to temporary location: {temp_file_path}")
        
        try:
            # Prepare context information with more relevant metadata for uploaded files
            context_info = {
                'source': 'file_upload',
                'task_category': task_category or "audio_file",
                'original_filename': file.filename,
                'file_size': len(content),
                'content_type': content_type,
                'language': language,
                'description': description
            }
                
            logger.info(f"Transcribing file with context: {context_info}")
            
            # Process the audio file with context
            transcribed_text = await transcribe_audio_file(
                temp_file_path, 
                context_info=context_info
            )
            
            return TranscriptionFileResponse(
                success=True,
                text=transcribed_text,
                original_filename=file.filename,
                file_size=len(content),
                language=language
            )
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
                logger.info(f"Cleaned up temporary file: {temp_file_path}")
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing audio file: {e}", exc_info=True)
        return TranscriptionFileResponse(
            success=False,
            error=str(e)
        )
