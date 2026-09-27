"""File-based transcription workflow helpers."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from api.dependencies import resolve_transcription_service
from api.services.transcription.audio_utils import convert_audio_to_wav
from api.services.websocket_events import send_transcription_status

logger = logging.getLogger(__name__)


async def transcribe_audio_file(audio_file_path: str, context_info: Optional[Dict[str, Any]] = None) -> str:
    """
    Transcribe a complete audio file and send status updates via WebSocket.

    Args:
        audio_file_path: Path to the audio file to transcribe
        context_info: Optional context information about the transcription

    Returns:
        str: The transcribed text
    """
    converted_file = None
    source_is_uploaded_file = context_info and context_info.get('source') == 'file_upload'

    transcription_service = resolve_transcription_service()

    try:
        # Send started status
        await send_transcription_status("started")

        # Ensure model is loaded
        if not transcription_service.is_model_loaded():
            logger.info("Loading transcription model...")
            transcription_service.load_model()

        # Get file extension to determine format
        file_ext = Path(audio_file_path).suffix.lower()
        is_wav = file_ext == '.wav'

        # Log information about the audio file
        if source_is_uploaded_file and context_info:
            logger.info(f"Processing uploaded audio file: {context_info.get('original_filename', 'unknown')}")
            logger.info(f"File type: {context_info.get('content_type', 'unknown')}, size: {context_info.get('file_size', 'unknown')}")
            if context_info.get('language'):
                logger.info(f"Language: {context_info.get('language')}")
            if context_info.get('description'):
                logger.info(f"Description: {context_info.get('description')}")

        # Convert audio to WAV format if needed
        if not is_wav:
            logger.info(f"File format is {file_ext}, converting to WAV")
            try:
                converted_file = await convert_audio_to_wav(audio_file_path)
                audio_file_path = converted_file
                logger.info(f"Converted to WAV: {audio_file_path}")
            except Exception as e:
                logger.error(f"Error converting audio: {e}")
                # Continue with original file if conversion fails
                logger.warning("Continuing with original file despite conversion failure")

        # Read the audio file
        with open(audio_file_path, 'rb') as f:
            audio_data = f.read()

        # Update context with additional information if needed
        if context_info:
            # Add conversion status to context
            context_info['converted_to_wav'] = converted_file is not None

            # If language is specified and file was uploaded, add it to context
            if source_is_uploaded_file and 'language' in context_info:
                # Make sure language code is properly formatted for the model
                language = context_info.get('language', 'en')
                logger.info(f"Setting language for transcription: {language}")
                # No need to modify context_info as language is already there

        # Perform transcription with context
        try:
            transcribed_text = await transcription_service.transcribe(audio_data, context_info)

            # Send completed status with transcribed text
            await send_transcription_status("completed", transcribed_text)

            return transcribed_text
        except Exception as e:
            # Check if this is a database error but transcription was successful
            if "no such table: transcriptions" in str(e) and hasattr(e, "__context__") and e.__context__ is not None and hasattr(e.__context__, "transcribed_text"):
                # We have the transcribed text despite the database error
                transcribed_text = e.__context__.transcribed_text  # type: ignore[attr-defined]
                logger.warning(f"Database error occurred but transcription was successful: {str(e)}")

                # Send completed status with transcribed text
                await send_transcription_status("completed", transcribed_text)

                return transcribed_text
            else:
                # This is a more serious error, re-raise
                raise

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        await send_transcription_status("failed", str(e))
        raise
    finally:
        # Clean up converted file if it exists
        if converted_file and converted_file != audio_file_path and os.path.exists(converted_file):
            try:
                os.unlink(converted_file)
                logger.info(f"Cleaned up temporary converted file: {converted_file}")
            except Exception as e:
                logger.error(f"Error cleaning up converted file: {e}")
