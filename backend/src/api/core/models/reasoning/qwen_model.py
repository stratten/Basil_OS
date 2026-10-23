import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Set

from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
import torch

from ..base_model import ModelMetadata, ModelState
from ..model_types import ModelCapability
from .base_reasoning import BaseReasoningModel

logger = logging.getLogger(__name__)

class QwenModel(BaseReasoningModel):
    """Local Qwen model implementation using transformers."""

    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        super().__init__(model_path, required_capabilities)
        self._model: Optional[AutoModelForCausalLM] = None
        self._tokenizer: Optional[AutoTokenizer] = None
        self._pipeline: Optional[pipeline] = None
        
        # Try to get context window from model config, fallback to 32K
        self.max_context_length = self._get_context_window_from_config() or 32768
        self.max_output_tokens = self._get_max_output_from_config() or 4000
        
        self.device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
        
        # Generation parameters optimized for Qwen3
        self.temperature = 0.7
        self.top_p = 0.8
        self.top_k = 20
        self.repetition_penalty = 1.05
    
    def _get_context_window_from_config(self) -> Optional[int]:
        """Get context window from the unified registry."""
        try:
            from ..models_registry import get_local_reasoning_models, get_on_disk_name
            
            # Extract model variant from path (e.g., "qwen3-4b" from path).
            model_name = self.model_path.name.lower()
            
            # Search through local reasoning models in the registry.
            for model_id, model_config in get_local_reasoning_models().items():
                on_disk_name = model_config.get("on_disk_name", "")
                # Check if variant name or on_disk_name matches the model path.
                if "-" in model_id:
                    _, variant = model_id.split("-", 1)
                else:
                    variant = model_id
                
                if variant.lower() in model_name or on_disk_name.lower() in model_name:
                    return model_config.get("context_window")
        except Exception as e:
            logger.debug(f"Could not load context window from registry: {e}")
        return None
    
    def _get_max_output_from_config(self) -> Optional[int]:
        """Get max output tokens from the unified registry."""
        try:
            from ..models_registry import get_local_reasoning_models
            
            model_name = self.model_path.name.lower()
            
            # Search through local reasoning models in the registry.
            for model_id, model_config in get_local_reasoning_models().items():
                on_disk_name = model_config.get("on_disk_name", "")
                # Check if variant name or on_disk_name matches the model path.
                if "-" in model_id:
                    _, variant = model_id.split("-", 1)
                else:
                    variant = model_id
                
                if variant.lower() in model_name or on_disk_name.lower() in model_name:
                    return model_config.get("max_output_tokens")
        except Exception as e:
            logger.debug(f"Could not load max output tokens from registry: {e}")
        return None

    async def load(self) -> None:
        """Load the Qwen model."""
        if self.state == ModelState.READY:
            logger.info("Qwen model already loaded")
            return

        logger.info(f"Loading Qwen model from {self.model_path}")
        self.state = ModelState.LOADING
        
        try:
            # Load tokenizer
            logger.info("Loading Qwen tokenizer...")
            self._tokenizer = AutoTokenizer.from_pretrained(
                str(self.model_path),
                trust_remote_code=True,
                use_fast=True
            )
            
            # Set pad token if not present
            if self._tokenizer.pad_token is None:
                self._tokenizer.pad_token = self._tokenizer.eos_token
            
            # Determine optimal device and dtype for DIRECT loading
            if hasattr(torch, 'mps') and torch.backends.mps.is_available():
                # 🚀 DIRECT MPS LOADING - MPS is confirmed available
                torch_dtype = torch.float16
                torch_device = torch.device("mps")
                device_map = None  # Don't use device_map for MPS
                logger.info("✅ MPS confirmed available - Using Direct MPS loading (Apple Silicon optimization)")
                use_mps_direct = True
                
            elif self.device == "cuda" and torch.cuda.is_available():
                # NVIDIA GPU optimization - confirmed available
                torch_dtype = torch.float16
                torch_device = torch.device("cuda")
                device_map = "auto"
                logger.info("✅ CUDA confirmed available - Using CUDA GPU acceleration")
                use_mps_direct = False
            else:
                # CPU fallback (no GPU or GPU not available)
                torch_dtype = torch.float32
                torch_device = torch.device("cpu")
                device_map = None
                if self.device == "mps":
                    logger.warning("⚠️ MPS was selected but not available, falling back to CPU")
                elif self.device == "cuda":
                    logger.warning("⚠️ CUDA was selected but not available, falling back to CPU")
                logger.info("Using CPU (no GPU acceleration available)")
                use_mps_direct = False
            
            # Load model with optimized settings
            logger.info("Loading Qwen model...")
            
            if use_mps_direct:
                # 🚀 Direct MPS: Load with device specification
                logger.info("Using Direct MPS loading path")
                self._model = AutoModelForCausalLM.from_pretrained(
                    str(self.model_path),
                    torch_dtype=torch_dtype,
                    trust_remote_code=True,
                    low_cpu_mem_usage=True,
                    use_cache=True,
                ).to(torch_device)  # Direct move to MPS after loading
            else:
                # Standard loading for CUDA/CPU
                logger.info("Using standard loading path")
                self._model = AutoModelForCausalLM.from_pretrained(
                    str(self.model_path),
                    device_map=device_map,
                    torch_dtype=torch_dtype,
                    trust_remote_code=True,
                    low_cpu_mem_usage=True,
                    use_cache=True,
                )
            
            # Set up device for pipeline based on model location
            if use_mps_direct:
                pipeline_device = "mps"  # Use string for MPS, not device number
            else:
                pipeline_device = -1  # CPU
                
            self._pipeline = pipeline(
                "text-generation",
                model=self._model,
                tokenizer=self._tokenizer,
                device=pipeline_device,
                torch_dtype=torch_dtype,
                return_full_text=False,  # Only return generated text
            )
            
            logger.info(f"Qwen model loaded successfully using {'Direct MPS' if use_mps_direct else 'standard'} loading")
            self.state = ModelState.READY
            
        except Exception as e:
            logger.error(f"Failed to load Qwen model: {e}")
            self.state = ModelState.ERROR
            raise RuntimeError(f"Failed to load Qwen model: {e}")

    async def unload(self) -> None:
        """Unload the model from memory."""
        logger.info("Unloading Qwen model")
        
        # Clear pipeline and model
        self._pipeline = None
        if self._model is not None:
            del self._model
            self._model = None
        if self._tokenizer is not None:
            del self._tokenizer
            self._tokenizer = None
        
        self.state = ModelState.UNLOADED
        
        # Force garbage collection
        import gc
        gc.collect()
        
        # Clear CUDA cache if using GPU
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    async def generate_response(
        self,
        prompt: str,
        context: Dict[str, Any] = None,
        max_tokens: int = 1024,
        temperature: float = None,
        top_p: float = None,
        top_k: int = None
    ) -> str:
        """Generate a response using the Qwen model."""
        if self.state != ModelState.READY:
            await self.load()
        
        # Use provided parameters or defaults
        temp = temperature if temperature is not None else self.temperature
        p = top_p if top_p is not None else self.top_p
        k = top_k if top_k is not None else self.top_k
        
        # Process context if provided
        if context:
            context_str = "\n".join(f"{key}: {value}" for key, value in context.items())
            full_prompt = f"{context_str}\n\n{prompt}"
        else:
            full_prompt = prompt
        
        # Format prompt for Qwen3 (uses ChatML format)
        formatted_prompt = f"<|im_start|>system\nYou are a helpful AI assistant.<|im_end|>\n<|im_start|>user\n{full_prompt}<|im_end|>\n<|im_start|>assistant\n"
        
        logger.info(f"Generating Qwen response for prompt (length: {len(full_prompt)} chars)")
        logger.info(f"Generation parameters: max_tokens={max_tokens}, temp={temp}, top_p={p}")
        
        # Handle temperature=0.0 case: use deterministic generation instead of sampling
        if temp <= 0.001:  # Close to zero - use deterministic generation
            use_sampling = False
            generation_params = {
                "max_new_tokens": max_tokens,
                "do_sample": False,  # Deterministic generation (greedy decoding)
                "pad_token_id": self._tokenizer.pad_token_id,
                "eos_token_id": self._tokenizer.eos_token_id,
                "truncation": True,
            }
            logger.info("Using deterministic generation (do_sample=False) for temperature ~0.0")
        else:
            use_sampling = True
            generation_params = {
                "max_new_tokens": max_tokens,
                "temperature": temp,
                "top_p": p,
                "do_sample": True,  # Sampling with temperature
                "pad_token_id": self._tokenizer.pad_token_id,
                "eos_token_id": self._tokenizer.eos_token_id,
                "truncation": True,
            }
            logger.info(f"Using sampling generation with temperature={temp}")
        
        try:
            # Generate response using pipeline with appropriate parameters
            logger.info("Starting pipeline generation...")
            result = await asyncio.to_thread(
                self._pipeline,
                formatted_prompt,
                **generation_params
            )
            logger.info("Pipeline generation completed successfully")
            
            # Extract generated text
            generated_text = result[0]["generated_text"]
            logger.info(f"Raw generated text length: {len(generated_text)} chars")
            
            # Clean up the response (remove any remaining special tokens)
            response = generated_text.replace("<|im_end|>", "").strip()
            
            logger.info(f"Generated Qwen response (length: {len(response)} chars)")
            return response
            
        except Exception as e:
            logger.error(f"Error generating Qwen response: {e}")
            return f"Error generating response: {e}"

    async def validate(self) -> bool:
        """Validate that the model is working correctly."""
        if self.state != ModelState.READY:
            logger.info("Loading Qwen model for validation...")
            await self.load()
        
        try:
            # Simple validation prompt
            prompt = "Hello! Can you help me solve this math problem: what is 7 + 8?"
            logger.info("Running Qwen validation with test prompt")
            
            response = await self.generate_response(prompt, max_tokens=50)
            
            # Check if we got a meaningful response
            if response and len(response) > 5 and "15" in response:
                logger.info("Qwen model validation successful")
                return True
            else:
                logger.warning(f"Qwen model validation failed: response was '{response}'")
                return False
        except Exception as e:
            logger.error(f"Qwen model validation failed: {e}")
            return False

    def get_metadata(self) -> ModelMetadata:
        """Get metadata about the Qwen model."""
        return ModelMetadata(
            name="Qwen3-4B",
            description="Qwen3-4B model with hybrid thinking modes and Apache 2.0 license",
            version="3.0",
            capabilities={ModelCapability.REASONING},
            parameters={
                "total_params": 4_000_000_000,  # 4B parameters
                "max_context_length": self.max_context_length,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "repetition_penalty": self.repetition_penalty,
                "device": self.device
            },
            source="qwen",
            requirements={
                "transformers": ">=4.36.0",
                "torch": ">=2.0.0"
            },
            memory_requirements="8GB",
            supports_gpu=True,
            context_window=self.max_context_length,
            max_output_tokens=self.max_output_tokens
        )

    def configure(self, **kwargs) -> None:
        """Configure model parameters."""
        super().configure(**kwargs)
        if 'temperature' in kwargs:
            self.temperature = float(kwargs['temperature'])
        if 'top_p' in kwargs:
            self.top_p = float(kwargs['top_p'])
        if 'top_k' in kwargs:
            self.top_k = int(kwargs['top_k'])
        if 'repetition_penalty' in kwargs:
            self.repetition_penalty = float(kwargs['repetition_penalty'])

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