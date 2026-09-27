import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, Set

from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
import torch

from ..base_model import ModelMetadata, ModelState
from ..model_types import ModelCapability
from .base_reasoning import BaseReasoningModel

class MistralModel(BaseReasoningModel):
    """Local Mistral model implementation."""

    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        super().__init__(model_path, required_capabilities)
        self._model: Optional[AutoModelForCausalLM] = None
        self._tokenizer: Optional[AutoTokenizer] = None
        self._pipeline: Optional[pipeline] = None
        # Default settings
        self.max_context_length = 2048  # Keep context length reasonable for better performance
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        # Instruction template
        self.instruction_template = """<s>[INST] {instruction} [/INST]"""

    async def load(self) -> None:
        """Load the Mistral model."""
        try:
            self.state = ModelState.LOADING
            print(f"[MISTRAL MODEL] Loading model from {self.model_path}")
            print(f"[MISTRAL MODEL] Using device: {self.device}")
            
            # Wrap blocking operations in asyncio.to_thread
            self._tokenizer = await asyncio.to_thread(
                AutoTokenizer.from_pretrained,
                self.model_path,
                trust_remote_code=True
            )
            
            # Use bfloat16 precision to reduce memory usage
            dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
            
            self._model = await asyncio.to_thread(
                AutoModelForCausalLM.from_pretrained,
                self.model_path,
                device_map=self.device,
                torch_dtype=dtype,
                trust_remote_code=True
            )
            
            self._pipeline = await asyncio.to_thread(
                pipeline,
                "text-generation",
                model=self._model,
                tokenizer=self._tokenizer,
                trust_remote_code=True
            )
            
            print("[MISTRAL MODEL] Model loaded successfully")
            self.state = ModelState.READY
        except Exception as e:
            self.state = ModelState.ERROR
            self._error = f"Failed to load Mistral model: {str(e)}"
            print(f"[MISTRAL MODEL] Error loading model: {str(e)}")

    async def unload(self) -> None:
        """Unload the Mistral model."""
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
        print("[MISTRAL MODEL] Model unloaded successfully")

    def get_metadata(self) -> ModelMetadata:
        """Get model metadata."""
        return ModelMetadata(
            name="Mistral",
            version="7B-v0.3",
            source="mistralai",
            capabilities={ModelCapability.REASONING},
            description="Mistral 7B v0.3 with extended vocabulary",
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
            memory_requirements="32GB",  # Updated based on actual model files (14.5GB) plus overhead for loading and generation
            supports_gpu=True
        )

    async def generate_response(
        self,
        prompt: str,
        context: Dict[str, Any] = None,
        max_tokens: int = 1000
    ) -> str:
        """Generate a response using the Mistral model."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        try:
            # Combine context with prompt if provided
            if context:
                context_str = "\n".join(f"{k}: {v}" for k, v in context.items())
                full_prompt = f"{context_str}\n\n{prompt}"
            else:
                full_prompt = prompt

            # Format with instruction template
            formatted_prompt = self.instruction_template.format(instruction=full_prompt)
            
            # Log the full prompt without truncation
            print(f"[MISTRAL MODEL] Generating response for prompt (length: {len(formatted_prompt)} chars)")
            print(f"[MISTRAL MODEL] PROMPT: {formatted_prompt}")
            
            outputs = self._pipeline(
                formatted_prompt,
                max_new_tokens=max_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
                do_sample=True,
                num_return_sequences=1,
                pad_token_id=self._tokenizer.eos_token_id
            )
            
            generated_text = outputs[0]["generated_text"]
            
            # Extract response, which follows the [/INST] tag
            if "[/INST]" in generated_text:
                response = generated_text.split("[/INST]", 1)[1].strip()
            else:
                # Fallback: remove the input prompt
                response = generated_text[len(formatted_prompt):].strip()
            
            # Log the full response without truncation
            print(f"[MISTRAL MODEL] Generated response (length: {len(response)} chars)")
            print(f"[MISTRAL MODEL] RESPONSE: {response}")
            
            return response

        except Exception as e:
            print(f"[MISTRAL MODEL] Error generating response: {str(e)}")
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
                print(f"[MISTRAL MODEL] Warning: Unknown parameter {key}")

    def _generate(self, prompt: str, max_tokens: int) -> str:
        """Internal method for synchronous text generation."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        formatted_prompt = self.instruction_template.format(instruction=prompt)
        
        outputs = self._pipeline(
            formatted_prompt,
            max_new_tokens=max_tokens,
            temperature=self.temperature,
            top_p=self.top_p,
            do_sample=True,
            num_return_sequences=1,
            pad_token_id=self._tokenizer.eos_token_id
        )
        
        generated_text = outputs[0]["generated_text"]
        
        # Extract response, which follows the [/INST] tag
        if "[/INST]" in generated_text:
            response = generated_text.split("[/INST]", 1)[1].strip()
        else:
            # Fallback: remove the input prompt
            response = generated_text[len(formatted_prompt):].strip()
            
        return response

    async def _generate_async(self, prompt: str, max_tokens: int) -> str:
        """Internal method for asynchronous text generation."""
        # Use asyncio.to_thread to run the synchronous generation in a separate thread
        return await asyncio.to_thread(self._generate, prompt, max_tokens) 