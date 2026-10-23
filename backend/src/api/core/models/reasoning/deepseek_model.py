from pathlib import Path
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline, LlamaTokenizer, PreTrainedTokenizerFast
from typing import Set, Dict, Any, Optional, List, Tuple
import asyncio
import os
import json
import logging
import subprocess
import sys
import time



from ..base_model import ModelMetadata, ModelState
from ..model_types import ModelCapability
from .base_reasoning import (
    BaseReasoningModel,
    ReasoningTruncatedError,
    has_unterminated_reasoning,
    strip_inline_reasoning,
)
from ..gpu_manager import GPUManager

# Global model cache to keep models loaded between requests
_MODEL_CACHE = {}

# R1-style reasoning markers for the DeepSeek family this adapter loads.
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"

class FallbackTokenizer:
    """Fallback tokenizer for when the model's tokenizer can't be loaded."""
    
    def __init__(self):
        """Initialize the fallback tokenizer."""
        logging.info("Initializing fallback tokenizer")
        self.base_tokenizer = None
        
        # Try loading different tokenizers in order of preference
        tokenizers_to_try = [
            "meta-llama/Llama-2-7b-hf",
            "microsoft/phi-2",
            "gpt2"
        ]
        
        for tokenizer_name in tokenizers_to_try:
            try:
                logging.info(f"Trying to load tokenizer: {tokenizer_name}")
                self.base_tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
                logging.info(f"Successfully loaded tokenizer: {tokenizer_name}")
                break
            except Exception as e:
                logging.warning(f"Failed to load tokenizer {tokenizer_name}: {e}")
        
        if self.base_tokenizer is None:
            raise ValueError("Failed to load any fallback tokenizer")
        
        # Set attributes based on the base tokenizer
        self.vocab_size = getattr(self.base_tokenizer, "vocab_size", 50257)  # Default to GPT-2 vocab size
        self.pad_token = getattr(self.base_tokenizer, "pad_token", "[PAD]")
        self.eos_token = getattr(self.base_tokenizer, "eos_token", "</s>")
        self.bos_token = getattr(self.base_tokenizer, "bos_token", "<s>")
        self.unk_token = getattr(self.base_tokenizer, "unk_token", "<unk>")
        
        # Set token IDs
        self.pad_token_id = getattr(self.base_tokenizer, "pad_token_id", 0)
        self.eos_token_id = getattr(self.base_tokenizer, "eos_token_id", 2)
        self.bos_token_id = getattr(self.base_tokenizer, "bos_token_id", 1)
        self.unk_token_id = getattr(self.base_tokenizer, "unk_token_id", 3)
    
    def __call__(self, *args, **kwargs):
        """Call the base tokenizer."""
        return self.base_tokenizer(*args, **kwargs)

class DeepSeekModel(BaseReasoningModel):
    """Implementation of the DeepSeek-R1-Distill-Qwen-7B reasoning model."""

    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        """Initialize the DeepSeek model."""
        super().__init__(model_path, required_capabilities)
        self.model_path = model_path
        self.model = None
        self.tokenizer = None
        self.pipeline = None
        self.device = "mps" if hasattr(torch, 'mps') and torch.backends.mps.is_available() else "cpu"
        
        # Check if GPU acceleration is available
        self.gpu_manager = GPUManager()
        self.gpu_capabilities = self.gpu_manager.capabilities
        
        # Log GPU capabilities
        print(f"[DeepSeek] GPU acceleration enabled with {self.gpu_capabilities['backend']} using {str(torch.float16)}")
        print(f"[DeepSeek] Memory optimizations: {self.gpu_capabilities.get('memory_optimizations', {})}")

    async def load(self) -> None:
        """Load the DeepSeek model."""
        if self.state == ModelState.READY:
            logging.info("DeepSeek model already loaded")
            return

        # Check if model is in cache
        cache_key = str(self.model_path)
        if cache_key in _MODEL_CACHE:
            logging.info(f"Using cached DeepSeek model for {self.model_path}")
            cached_model = _MODEL_CACHE[cache_key]
            self.model = cached_model.get("model")
            self.tokenizer = cached_model.get("tokenizer")
            self.pipeline = cached_model.get("pipeline")
            self.state = ModelState.READY
            return

        logging.info(f"Loading DeepSeek model from {self.model_path}")
        self.state = ModelState.LOADING
        
        await self._load_traditional()
        
        # Cache the model
        _MODEL_CACHE[cache_key] = {
            "model": self.model,
            "tokenizer": self.tokenizer,
            "pipeline": self.pipeline
        }
        logging.info(f"Cached DeepSeek model for future use")
        
        self.state = ModelState.READY

    async def _load_traditional(self) -> None:
        """Load the DeepSeek model using traditional HuggingFace methods."""
        logging.info("Loading tokenizer...")
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_path,
                trust_remote_code=True,
                use_fast=False
            )
        except Exception as e:
            logging.warning(f"Failed to load tokenizer with AutoTokenizer: {e}")
            try:
                self.tokenizer = LlamaTokenizer.from_pretrained(
                    self.model_path,
                    legacy=False
                )
            except Exception as e:
                logging.warning(f"Failed to load tokenizer with LlamaTokenizer: {e}")
                try:
                    self.tokenizer = LlamaTokenizer.from_pretrained(
                        self.model_path,
                        legacy=True
                    )
                except Exception as e:
                    logging.warning(f"Failed to load tokenizer with legacy LlamaTokenizer: {e}")
                    self.tokenizer = FallbackTokenizer()
                    logging.info("Using fallback tokenizer")

        # Ensure special tokens are set
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        logging.info("Loading model...")
        
        # Configure device and quantization
        device_map = "auto"
        torch_dtype = torch.float16
        
        if hasattr(torch, 'mps') and torch.backends.mps.is_available():
            logging.info("Using Metal acceleration for traditional loading")
            device_map = {"": "mps"}
        
        # Load model with optimized settings
        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            device_map=device_map,
            torch_dtype=torch_dtype,
            trust_remote_code=True,
            low_cpu_mem_usage=True,
            use_flash_attention_2=False,  # Disable flash attention which can be slow on some hardware
            use_cache=True,  # Enable KV caching for faster inference
        )
        
        logging.info("Creating text generation pipeline...")
        
        # Create an optimized pipeline
        self.pipeline = pipeline(
            "text-generation",
            model=self.model,
            tokenizer=self.tokenizer,
            device_map=device_map,
        )
        
        logging.info("DeepSeek model loaded successfully with traditional method")

    async def unload(self) -> None:
        """Unload the model from memory."""
        # Don't actually unload if we're caching
        cache_key = str(self.model_path)
        if cache_key in _MODEL_CACHE:
            print("[DeepSeek] Model is cached, skipping unload")
            return
            
        # Unload the model
        self.model = None
        self.tokenizer = None
        self.pipeline = None
        self.state = ModelState.UNLOADED
        
        # Force garbage collection
        import gc
        gc.collect()
        
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    async def generate_response(
        self, prompt: str, context: Dict[str, Any] = None, max_tokens: int = 1024, 
        temperature: float = 0.1, top_p: float = 0.95, top_k: int = 40, timeout: int = 30
    ) -> str:
        """Generate a response from the DeepSeek model."""
        if self.state != ModelState.READY:
            await self.load()
        
        # Process context if provided
        if context:
            context_str = "\n".join(f"{k}: {v}" for k, v in context.items())
            full_prompt = f"{context_str}\n\n{prompt}"
        else:
            full_prompt = prompt
        
        logging.info(f"Generating response for prompt (length: {len(full_prompt)} chars)")
        logging.info(f"Prompt preview: {full_prompt[:20]}...")
        
        start_time = time.time()
        try:
            # Traditional generation with optimized settings for factual responses
            generation_config = {
                "max_new_tokens": min(max_tokens, 50),  # Further limit tokens for faster generation
                "do_sample": temperature > 0,  # Only sample if temperature > 0
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "num_return_sequences": 1,
                "pad_token_id": self.tokenizer.pad_token_id,
                "eos_token_id": self.tokenizer.eos_token_id,
                "repetition_penalty": 1.1,  # Slight repetition penalty
                "return_full_text": True,  # Get the full text including prompt
                "use_cache": True,  # Enable KV caching for faster generation
            }
            
            # For very simple queries, use an even faster approach
            if len(full_prompt) < 100 and max_tokens < 30:
                logging.info("Using fast generation mode for short prompt and response")
                generation_config["max_new_tokens"] = min(max_tokens, 30)
                generation_config["do_sample"] = False  # Force greedy decoding for maximum speed
            
            response = self.pipeline(full_prompt, **generation_config)[0]["generated_text"]
            
            # Remove the prompt from the response
            if response.startswith(full_prompt):
                response = response[len(full_prompt):]
        
        except Exception as e:
            logging.error(f"Error generating response: {e}")
            return f"Error generating response: {e}"
        
        # Clean up the response. Replacing only the closing tag used to leave the
        # entire reasoning body in the returned text, passing chain-of-thought off
        # as the answer; R1-style models open a <think> block before answering.
        if has_unterminated_reasoning(response, _THINK_OPEN, _THINK_CLOSE):
            raise ReasoningTruncatedError(
                f"Generation stopped inside the model's reasoning block after "
                f"{len(response)} chars without emitting an answer; "
                f"max_new_tokens={generation_config['max_new_tokens']} is below "
                "what this model needs to reason and then answer"
            )
        response = strip_inline_reasoning(response, _THINK_OPEN, _THINK_CLOSE).strip()
        
        generation_time = time.time() - start_time
        logging.info(f"Generated response (length: {len(response)} chars)")
        logging.info(f"Response preview: {response[:30]}...")
        logging.info(f"Generation completed in {generation_time:.2f} seconds")
        
        return response

    def _generate(self, prompt: str, max_tokens: int = 1024) -> str:
        """Synchronous method for generating text (required by abstract base class)."""
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.generate_response(prompt, max_tokens=max_tokens))
        finally:
            loop.close()

    async def _generate_async(self, prompt: str, max_tokens: int = 1024) -> str:
        """Asynchronous method for generating text (required by abstract base class)."""
        return await self.generate_response(prompt, max_tokens=max_tokens)

    async def validate(self) -> bool:
        """Validate that the model is working correctly."""
        if self.state != ModelState.READY:
            logging.info("Loading model for validation...")
            await self.load()
        
        try:
            # Simple validation prompt
            prompt = "Hello, can you help me solve this math problem: what is 12 + 15?"
            logging.info("Running validation with test prompt")
            
            response = await self.generate_response(prompt, max_tokens=50)
            
            # Check if we got some kind of meaningful response
            if response and len(response) > 10:
                logging.info("Model validation successful")
                return True
            else:
                logging.info("Model validation failed: response too short")
                return False
        except Exception as e:
            logging.error(f"Model validation failed: {e}")
            return False

    def get_metadata(self) -> ModelMetadata:
        """Get metadata about the model."""
        return ModelMetadata(
            name="DeepSeek-R1-Distill-Qwen-7B",
            description="DeepSeek-R1-Distill-Qwen-7B reasoning model",
            version="1.0",
            capabilities={ModelCapability.REASONING},
            context_length=4096,
            parameters=7_000_000_000,  # 7B parameters
        ) 