"""
HuggingFace Transcription Service.

A thin coordinator that delegates to specialized modules for:
- Model lifecycle management (model_lifecycle.py)
- Audio processing utilities (audio_utils.py)
- Core transcription logic (transcription_processor.py)
"""

from ..base_transcription_service import BaseTranscriptionService
from ..local_model.model_lifecycle import ModelManager
from ..processing.transcription_processor import TranscriptionProcessor

from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime
import shutil
import logging

from ....core.logging.api_logger import setup_api_logger
from ....core.config.api_settings import settings
from ....core.knowledge.sqlite.transcription_repository import TranscriptionRepository

logger = setup_api_logger(
    __name__,
    log_file=settings.STORAGE_DIR / "logs" / "api.log" if not settings.DEBUG else None,
    level=logging.DEBUG if settings.DEBUG else logging.INFO
)


class HuggingFaceTranscriptionService(BaseTranscriptionService):
    """
    HuggingFace-based transcription service using Whisper models.
    
    This is a thin coordinator that delegates to specialized modules:
    - ModelManager: Handles model loading, unloading, and shared state
    - TranscriptionProcessor: Handles the core transcription workflow
    """
    
    def __init__(self, model_id: Optional[str] = None):
        super().__init__()
        self._model_id = model_id
        
        # Initialize the model manager (handles shared model state)
        self.model_manager = ModelManager()
        
        # Path for recordings, derived from settings.STORAGE_DIR
        # This will be ~/.basil/data/Recordings/
        self.recordings_dir = settings.STORAGE_DIR / "Recordings" 
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        
        # Path for uploads, derived from settings.STORAGE_DIR
        # This will be ~/.basil/data/Uploads/
        self.uploads_dir = settings.STORAGE_DIR / "Uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize transcription repository
        self.transcription_repository = TranscriptionRepository()
        
        # Initialize the transcription processor
        self.transcription_processor = TranscriptionProcessor(
            model_manager=self.model_manager,
            recordings_dir=self.recordings_dir,
            uploads_dir=self.uploads_dir,
            transcription_repository=self.transcription_repository
        )
    
    def load_model(self) -> None:
        """Load the transcription model. Delegates to ModelManager."""
        self.model_manager.load_model(self._model_id)
    
    def unload_model(self) -> None:
        """Unload the transcription model. Delegates to ModelManager."""
        self.model_manager.unload_model()
    
    def is_model_loaded(self) -> bool:
        """Check if the transcription model is loaded."""
        return self.model_manager.is_model_loaded()
    
    @classmethod
    def schedule_unload(cls, delay_seconds: int) -> None:
        """Schedule model unload after specified delay."""
        ModelManager.schedule_unload(delay_seconds)
    
    @classmethod
    def cancel_unload(cls) -> None:
        """Cancel any scheduled unload."""
        ModelManager.cancel_unload()
    
    async def transcribe(self, audio_data: bytes, context_info: Optional[Dict[str, Any]] = None) -> str:
        """
        Transcribe audio data to text.
        
        Args:
            audio_data: Raw audio bytes to transcribe
            context_info: Optional context information
            
        Returns:
            Transcribed text string
        """
        return await self.transcription_processor.process_transcription(audio_data, context_info)
    
    def cleanup_old_recordings(self, days_to_keep: int = 30) -> None:
        """Clean up recordings and uploaded files older than the specified number of days."""
        try:
            cutoff_date = datetime.now().timestamp() - (days_to_keep * 24 * 60 * 60)
            print(f"Cleaning up audio files older than {days_to_keep} days")
            
            # Clean up recordings
            deleted_recordings = self._cleanup_directory(self.recordings_dir, cutoff_date)
            
            # Clean up uploaded files
            deleted_uploads = self._cleanup_directory(self.uploads_dir, cutoff_date)
            
            print(f"Cleanup completed: {deleted_recordings} recordings and {deleted_uploads} uploaded files removed")
                    
        except Exception as e:
            print(f"Error during cleanup: {e}")
            
    def _cleanup_directory(self, root_dir: Path, cutoff_date: float) -> int:
        """Clean up files in the specified directory older than the cutoff date."""
        deleted_count = 0
        
        if not root_dir.exists():
            return deleted_count
        
        for year_month_dir in root_dir.iterdir():
            if not year_month_dir.is_dir():
                continue
                
            for day_dir in year_month_dir.iterdir():
                if not day_dir.is_dir():
                    continue
                
                for audio_file in day_dir.glob("*.wav"):
                    if audio_file.stat().st_mtime < cutoff_date:
                        try:
                            audio_file.unlink()
                            deleted_count += 1
                        except Exception as e:
                            print(f"Failed to delete {audio_file}: {e}")
                
                # Remove empty directories
                if not any(day_dir.iterdir()):
                    try:
                        day_dir.rmdir()
                        print(f"Removed empty directory: {day_dir}")
                    except Exception as e:
                        print(f"Failed to remove empty directory {day_dir}: {e}")
                
            if not any(year_month_dir.iterdir()):
                try:
                    year_month_dir.rmdir()
                    print(f"Removed empty directory: {year_month_dir}")
                except Exception as e:
                    print(f"Failed to remove empty directory {year_month_dir}: {e}")
        
        return deleted_count
    
    # Expose model manager properties for backward compatibility
    @property
    def _shared_model(self):
        """Access the shared model for backward compatibility."""
        return self.model_manager.shared_model
    
    @property
    def _shared_processor(self):
        """Access the shared processor for backward compatibility."""
        return self.model_manager.shared_processor
    
    @property
    def _shared_pipe(self):
        """Access the shared pipeline for backward compatibility."""
        return self.model_manager.shared_pipe
    
    @property
    def _shared_model_loaded(self):
        """Check if model is loaded for backward compatibility."""
        return self.model_manager.is_model_loaded()
    
    @property
    def _shared_device(self):
        """Access the shared device for backward compatibility."""
        return self.model_manager.shared_device
