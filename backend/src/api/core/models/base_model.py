from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Set

from pydantic import BaseModel

from .model_types import ModelCapability


class ModelState(Enum):
    """Possible states of a model."""
    UNLOADED = "unloaded"
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"


class ModelMetadata(BaseModel):
    """Metadata about a model."""
    name: str
    version: str
    source: str  # e.g., "huggingface", "openai", "whisper"
    capabilities: Set[ModelCapability]
    description: str
    parameters: Dict[str, Any]
    requirements: Dict[str, str]
    memory_requirements: str  # e.g., "4GB", "8GB"
    supports_gpu: bool = False
    context_window: int = 2048  # Maximum context window size in tokens
    max_output_tokens: Optional[int] = None  # Maximum output tokens (if different from context window)


class BaseAIModel(ABC):
    """Base class for all AI models in the system."""

    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        self.model_path = model_path
        self.required_capabilities = required_capabilities
        self.state = ModelState.UNLOADED
        self._model: Optional[Any] = None
        self._error: Optional[str] = None

    @property
    def is_loaded(self) -> bool:
        """Check if the model is loaded and ready."""
        return self.state == ModelState.READY

    @property
    def error(self) -> Optional[str]:
        """Get the last error message if any."""
        return self._error

    @abstractmethod
    async def load(self) -> None:
        """Load the model into memory."""
        pass

    @abstractmethod
    async def unload(self) -> None:
        """Unload the model from memory."""
        pass

    @abstractmethod
    def get_metadata(self) -> ModelMetadata:
        """Get model metadata."""
        pass

    def validate_capabilities(self) -> bool:
        """Validate that the model supports all required capabilities."""
        metadata = self.get_metadata()
        if not metadata.capabilities:
            return False
        return all(cap in metadata.capabilities for cap in self.required_capabilities)

    def supports_capability(self, capability: ModelCapability) -> bool:
        """Check if the model supports a specific capability."""
        return capability in self.required_capabilities

    @abstractmethod
    async def predict(self, input_data: Any) -> Any:
        """Run inference on the model."""
        pass

    @abstractmethod
    async def validate(self) -> bool:
        """Validate that the model is working correctly."""
        pass

    def generate(self, prompt: str, max_tokens: int = 100) -> str:
        """Generate text synchronously."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")
        return self._generate(prompt, max_tokens)

    async def generate_async(self, prompt: str, max_tokens: int = 100) -> str:
        """Generate text asynchronously."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")
        return await self._generate_async(prompt, max_tokens)

    @abstractmethod
    def _generate(self, prompt: str, max_tokens: int) -> str:
        """Internal method for synchronous text generation."""
        pass

    @abstractmethod
    async def _generate_async(self, prompt: str, max_tokens: int) -> str:
        """Internal method for asynchronous text generation."""
        pass 