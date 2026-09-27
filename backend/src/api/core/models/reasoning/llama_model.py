from pathlib import Path
from typing import Any, Dict, Optional, Set

from llama_cpp import Llama

from ..base_model import ModelMetadata, ModelState
from ..model_types import ModelCapability
from .base_reasoning import BaseReasoningModel
from ...logging.api_logger import api_logger


class LlamaModel(BaseReasoningModel):
    """Local LLaMA model implementation."""

    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        super().__init__(model_path, required_capabilities)
        self._llm: Optional[Llama] = None
        # Default settings for llama.cpp
        self.n_ctx = 2048
        self.n_threads = 4
        self.n_gpu_layers = 0  # CPU only by default

    async def load(self) -> None:
        """Load the LLaMA model."""
        try:
            self.state = ModelState.LOADING
            api_logger.debug(f"Loading LLaMA model from {self.model_path}")
            api_logger.debug(f"Using {self.n_threads} threads")
            self._llm = Llama(
                model_path=str(self.model_path),
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                n_gpu_layers=self.n_gpu_layers
            )
            api_logger.info("LLaMA model loaded successfully")
            self.state = ModelState.READY
        except Exception as e:
            self.state = ModelState.ERROR
            self._error = f"Failed to load LLaMA model: {str(e)}"
            api_logger.error(f"Error loading LLaMA model: {str(e)}")

    async def unload(self) -> None:
        """Unload the LLaMA model."""
        if self._llm is not None:
            del self._llm
            self._llm = None
        self.state = ModelState.UNLOADED
        api_logger.debug("LLaMA model unloaded successfully")

    async def get_metadata(self) -> ModelMetadata:
        """Get model metadata."""
        return ModelMetadata(
            name="LLaMA",
            version="2",  # Should be configured based on actual model
            source="local",
            capabilities={ModelCapability.REASONING},
            description="Local LLaMA model for reasoning tasks",
            parameters={
                "n_ctx": self.n_ctx,
                "n_threads": self.n_threads,
                "n_gpu_layers": self.n_gpu_layers,
                "temperature": self.temperature,
                "top_p": self.top_p
            },
            requirements={
                "llama-cpp-python": ">=0.2.0"
            },
            memory_requirements="4GB",  # Adjust based on model size
            supports_gpu=True
        )

    async def generate_response(
        self,
        prompt: str,
        context: Dict[str, Any] = None,
        max_tokens: int = 1000
    ) -> str:
        """Generate a response using LLaMA."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        try:
            response = self._llm(
                prompt,
                max_tokens=max_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
                echo=False
            )
            return response['choices'][0]['text'].strip()
        except Exception as e:
            raise RuntimeError(f"Error generating response: {str(e)}")

    async def validate(self) -> bool:
        """Validate LLaMA model functionality."""
        if not self.is_loaded:
            return False

        try:
            # Test basic generation
            response = await self.generate_response(
                "Test.",
                max_tokens=10
            )
            if not response or len(response) < 1:
                self._error = "Model failed to generate response"
                return False
            return True
        except Exception as e:
            self._error = f"Validation failed: {str(e)}"
            return False

    def configure(self, **kwargs) -> None:
        """Configure LLaMA specific parameters."""
        super().configure(**kwargs)
        if 'n_ctx' in kwargs:
            self.n_ctx = int(kwargs['n_ctx'])
        if 'n_threads' in kwargs:
            self.n_threads = int(kwargs['n_threads'])
        if 'n_gpu_layers' in kwargs:
            self.n_gpu_layers = int(kwargs['n_gpu_layers'])

    def _generate(self, prompt: str, max_tokens: int) -> str:
        """Internal method for synchronous text generation."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        try:
            response = self._llm(
                prompt,
                max_tokens=max_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
                echo=False
            )
            return response['choices'][0]['text'].strip()
        except Exception as e:
            raise RuntimeError(f"Error generating response: {str(e)}")

    async def _generate_async(self, prompt: str, max_tokens: int) -> str:
        """Internal method for asynchronous text generation."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        try:
            # Use the synchronous method since llama.cpp doesn't support async
            response = self._llm(
                prompt,
                max_tokens=max_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
                echo=False
            )
            return response['choices'][0]['text'].strip()
        except Exception as e:
            raise RuntimeError(f"Error generating response: {str(e)}") 