import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, Set

from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
import torch

from ..base_model import ModelMetadata, ModelState
from ..model_types import ModelCapability
from .base_reasoning import BaseReasoningModel

class PhiModel(BaseReasoningModel):
    """Local Phi model implementation."""

    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        super().__init__(model_path, required_capabilities)
        self._model: Optional[AutoModelForCausalLM] = None
        self._tokenizer: Optional[AutoTokenizer] = None
        self._pipeline: Optional[pipeline] = None
        # Default settings
        self.max_context_length = 2048
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    async def load(self) -> None:
        """Load the Phi model."""
        try:
            self.state = ModelState.LOADING
            print(f"[PHI MODEL] Loading model from {self.model_path}")
            print(f"[PHI MODEL] Using device: {self.device}")
            
            # Wrap blocking operations in asyncio.to_thread
            # Use native transformers support (4.53.1 has native Phi-3.5 support)
            self._tokenizer = await asyncio.to_thread(
                AutoTokenizer.from_pretrained,
                self.model_path,
                trust_remote_code=False,  # Use native support instead of remote code
                use_fast=True
            )
            self._model = await asyncio.to_thread(
                AutoModelForCausalLM.from_pretrained,
                self.model_path,
                device_map=self.device,
                trust_remote_code=False,  # Use native support instead of remote code
                torch_dtype=torch.float16
            )
            self._pipeline = await asyncio.to_thread(
                pipeline,
                "text-generation",
                model=self._model,
                tokenizer=self._tokenizer,
                trust_remote_code=False  # Use native support instead of remote code
            )
            print("[PHI MODEL] Model loaded successfully")
            self.state = ModelState.READY
        except Exception as e:
            self.state = ModelState.ERROR
            self._error = f"Failed to load Phi model: {str(e)}"
            print(f"[PHI MODEL] Error loading model: {str(e)}")

    async def unload(self) -> None:
        """Unload the Phi model."""
        async def _cleanup():
            if self._model is not None:
                del self._model
                self._model = None
            if self._tokenizer is not None:
                del self._tokenizer
                self._tokenizer = None
            if self._pipeline is not None:
                del self._pipeline
                self._pipeline = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        
        await asyncio.to_thread(_cleanup)
        self.state = ModelState.UNLOADED
        print("[PHI MODEL] Model unloaded successfully")

    def get_metadata(self) -> ModelMetadata:
        """Get model metadata."""
        return ModelMetadata(
            name="Phi",
            version="3.5",
            source="microsoft",
            capabilities={ModelCapability.REASONING},
            description="Microsoft Phi model for reasoning tasks",
            parameters={
                "max_context_length": self.max_context_length,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "device": self.device
            },
            requirements={
                "transformers": ">=4.36.0",
                "torch": ">=2.0.0"
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
        """Generate a response using the Phi model."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        try:
            # Combine context with prompt if provided
            if context:
                context_str = "\n".join(f"{k}: {v}" for k, v in context.items())
                full_prompt = f"{context_str}\n\n{prompt}"
            else:
                full_prompt = prompt

            # Log the full prompt without truncation
            print(f"[PHI MODEL] Generating response for prompt (length: {len(full_prompt)} chars)")
            print(f"[PHI MODEL] PROMPT: {full_prompt}")
            
            outputs = self._pipeline(
                full_prompt,
                max_new_tokens=max_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
                do_sample=True,
                num_return_sequences=1,
                pad_token_id=self._tokenizer.eos_token_id
            )
            
            generated_text = outputs[0]["generated_text"]
            # Remove the prompt from the generated text
            response = generated_text[len(full_prompt):].strip()
            
            # Log the full response without truncation
            print(f"[PHI MODEL] Generated response (length: {len(response)} chars)")
            print(f"[PHI MODEL] RESPONSE: {response}")
            
            return response

        except Exception as e:
            print(f"[PHI MODEL] Error generating response: {str(e)}")
            raise RuntimeError(f"Failed to generate response: {str(e)}")

    def validate(self) -> bool:
        """Validate model functionality."""
        if not self.is_loaded:
            return False
            
        try:
            # Just check if the model and tokenizer are loaded properly
            if self._model is None or self._tokenizer is None or self._pipeline is None:
                self._error = "Model components not properly loaded"
                return False
            return True
        except Exception as e:
            self._error = f"Validation failed: {str(e)}"
            return False

    def configure(self, **kwargs) -> None:
        """Configure model parameters."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                print(f"[PHI MODEL] Warning: Unknown parameter {key}")

    def _generate(self, prompt: str, max_tokens: int) -> str:
        """Internal method for synchronous text generation."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        outputs = self._pipeline(
            prompt,
            max_new_tokens=max_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            do_sample=True,
            num_return_sequences=1,
            pad_token_id=self._tokenizer.eos_token_id
        )
        
        generated_text = outputs[0]["generated_text"]
        # Remove the prompt from the generated text
        response = generated_text[len(prompt):].strip()
        return response

    async def _generate_async(self, prompt: str, max_tokens: int) -> str:
        """Internal method for asynchronous text generation."""
        # Use asyncio.to_thread to run the synchronous generation in a separate thread
        return await asyncio.to_thread(self._generate, prompt, max_tokens) 