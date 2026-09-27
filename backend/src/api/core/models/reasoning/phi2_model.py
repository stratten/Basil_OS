from pathlib import Path
from typing import Any, Dict, Optional, Set

from llama_cpp import Llama

from ..base_model import ModelMetadata, ModelState
from ..model_types import ModelCapability
from .base_reasoning import BaseReasoningModel
from ...logging.api_logger import api_logger


class Phi2Model(BaseReasoningModel):
    """Local Phi-2 model implementation for GGUF format."""

    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        super().__init__(model_path, required_capabilities)
        self._llm: Optional[Llama] = None
        # Default settings for llama.cpp
        self.n_ctx = 2048
        self.n_threads = 4
        self.n_gpu_layers = 0  # CPU only by default
        # Default generation parameters
        self.temperature = 0.7  # Slightly higher temperature for more creative responses
        self.top_p = 0.9  # Keep relatively high for coherent outputs
        # Instruction template for Phi-2
        self.instruction_template = """Below is an instruction that describes a task. Write a response that appropriately completes the request.

### Instruction:
{instruction}

### Response:
"""

    async def load(self) -> None:
        """Load the Phi-2 model."""
        try:
            self.state = ModelState.LOADING
            print(f"[PHI2 MODEL] Loading model from {self.model_path}")
            print(f"[PHI2 MODEL] Using {self.n_threads} threads")
            self._llm = Llama(
                model_path=str(self.model_path),
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                n_gpu_layers=self.n_gpu_layers
            )
            print("[PHI2 MODEL] Model loaded successfully")
            self.state = ModelState.READY
        except Exception as e:
            self.state = ModelState.ERROR
            self._error = f"Failed to load Phi-2 model: {str(e)}"
            print(f"[PHI2 MODEL] Error loading model: {str(e)}")

    async def unload(self) -> None:
        """Unload the Phi-2 model."""
        if self._llm is not None:
            del self._llm
            self._llm = None
        self.state = ModelState.UNLOADED
        print("[PHI2 MODEL] Model unloaded successfully")

    def get_metadata(self) -> ModelMetadata:
        """Get model metadata."""
        return ModelMetadata(
            name="Phi",
            version="2",
            source="microsoft",
            capabilities={ModelCapability.REASONING},
            description="Microsoft Phi-2 model for reasoning tasks",
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
            memory_requirements="8GB",
            supports_gpu=True
        )

    async def generate_response(
        self,
        prompt: str,
        context: Dict[str, Any] = None,
        max_tokens: int = 1000
    ) -> str:
        """Generate a response using Phi-2."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        try:
            # Combine context with prompt if provided
            if context:
                context_str = "\n".join(f"{k}: {v}" for k, v in context.items())
                instruction = f"{context_str}\n\n{prompt}"
            else:
                instruction = prompt

            # Format the prompt with the instruction template
            full_prompt = self.instruction_template.format(instruction=instruction)

            # Log the full prompt without truncation
            print(f"[PHI2 MODEL] Generating response for prompt (length: {len(full_prompt)} chars)")
            print(f"[PHI2 MODEL] PROMPT: {full_prompt}")
            
            response = self._llm(
                full_prompt,
                max_tokens=max_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
                echo=False,
                stop=["###", "Instruction:", "Response:", "Human:", "Assistant:"],  # Stop tokens to prevent model from continuing
                repeat_penalty=1.1,  # Slight penalty for repetition
                frequency_penalty=0.1,  # Slight penalty for frequent tokens
                presence_penalty=0.1  # Slight penalty for presence of tokens
            )
            result = response['choices'][0]['text'].strip()
            
            # Log the full response without truncation
            print(f"[PHI2 MODEL] Generated response (length: {len(result)} chars)")
            print(f"[PHI2 MODEL] RESPONSE: {result}")
            
            return result
        except Exception as e:
            print(f"[PHI2 MODEL] Error generating response: {str(e)}")
            raise RuntimeError(f"Failed to generate response: {str(e)}")

    def validate(self) -> bool:
        """Validate model functionality."""
        if not self.is_loaded:
            return False
            
        try:
            # Just check if the model is loaded properly
            if self._llm is None:
                self._error = "Model not properly loaded"
                return False
            return True
        except Exception as e:
            self._error = f"Validation failed: {str(e)}"
            return False

    def configure(self, **kwargs) -> None:
        """Configure model parameters."""
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
        # Use the synchronous method since llama.cpp doesn't support async
        return self._generate(prompt, max_tokens) 