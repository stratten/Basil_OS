from enum import Enum, auto
from typing import Any, Dict, List, Protocol, runtime_checkable
from pathlib import Path


class ModelCapability(Enum):
    """Enum representing different model capabilities."""
    NONE = auto()
    VISION = auto()
    REASONING = auto()
    TRANSCRIPTION = auto()


@runtime_checkable
class VisionCapable(Protocol):
    """Protocol for models with vision capabilities."""
    
    async def analyze_image(self, image_path: Path) -> Dict[str, Any]:
        """Analyze an image and return results.
        
        Args:
            image_path: Path to the image file to analyze
            
        Returns:
            Dictionary containing analysis results like:
            {
                'objects': List[str],  # Detected objects
                'text': str,  # OCR text if available
                'scene': str,  # Scene description
                'confidence': float  # Overall confidence score
            }
        """
        ...

    async def describe_image(self, image_path: Path) -> str:
        """Generate a natural language description of an image.
        
        Args:
            image_path: Path to the image file to describe
            
        Returns:
            String containing natural language description of the image
        """
        ...


@runtime_checkable
class ReasoningCapable(Protocol):
    """Protocol for models with reasoning capabilities."""
    
    async def generate_response(
        self,
        prompt: str,
        context: Dict[str, Any] = None,
        max_tokens: int = 1000
    ) -> str:
        """Generate a reasoned response to a prompt.
        
        Args:
            prompt: The input prompt/question
            context: Optional context dictionary with relevant information
            max_tokens: Maximum number of tokens in the response
            
        Returns:
            Generated response text
        """
        ...


@runtime_checkable
class TranscriptionCapable(Protocol):
    """Protocol for models with transcription capabilities."""
    
    async def transcribe_audio(
        self,
        audio_path: Path,
        language: str = "en"
    ) -> Dict[str, Any]:
        """Transcribe audio file to text.
        
        Args:
            audio_path: Path to the audio file
            language: Language code (default: "en")
            
        Returns:
            Dictionary containing transcription results like:
            {
                'text': str,  # Full transcription
                'segments': List[Dict],  # Time-aligned segments
                'language': str,  # Detected language
                'confidence': float  # Overall confidence score
            }
        """
        ...

    async def detect_language(self, audio_path: Path) -> str:
        """Detect the primary language spoken in an audio file.
        
        Args:
            audio_path: Path to the audio file
            
        Returns:
            Language code (e.g. "en", "es", etc.)
        """
        ... 