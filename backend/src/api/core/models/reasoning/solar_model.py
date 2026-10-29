from pathlib import Path
from typing import Any, Dict, Optional, Set
from llama_cpp import Llama
import asyncio
from typing import AsyncGenerator

from ..model_types import ModelCapability
from .base_reasoning import BaseReasoningModel
from ..base_model import ModelMetadata, ModelState
from ..gpu_manager import GPUManager
from ..token_utils import detect_context_window

# Import tokenizer conditionally to handle cases where it's not available
try:
    from transformers import AutoTokenizer
    TOKENIZER_AVAILABLE = True
except ImportError:
    TOKENIZER_AVAILABLE = False


class SolarModel(BaseReasoningModel):
    """Local SOLAR model implementation for GGUF format."""

    def __init__(self, model_path: Path, required_capabilities: Set[ModelCapability]):
        super().__init__(model_path, required_capabilities)
        self._model: Optional[Llama] = None
        
        # Try to detect context window from model path
        detected_ctx = detect_context_window(model_path)
        if detected_ctx:
            print(f"[SOLAR MODEL] Detected context window: {detected_ctx}")
            self.n_ctx = detected_ctx
        else:
            # Default settings for llama.cpp
            self.n_ctx = 4096  # SOLAR typically supports 4K context
            
        # Determine optimal thread count based on system
        self.n_threads = self._get_optimal_thread_count()
        self.n_gpu_layers = 0  # Default to CPU mode, will be updated if GPU is available
        
        # Default generation parameters
        self.temperature = 0.7
        self.top_p = 0.9
        self.instruction_template = """### Human: {instruction}

### Assistant: """

        # Try to load tokenizer if available
        self.tokenizer = None
        if TOKENIZER_AVAILABLE:
            try:
                self.tokenizer = AutoTokenizer.from_pretrained("Upstage/SOLAR-10.7B-Instruct-v1.0")
                print(f"[SOLAR MODEL] Loaded tokenizer: {self.tokenizer.__class__.__name__}")
            except Exception as e:
                print(f"[SOLAR MODEL] Failed to load tokenizer: {e}")
                
        # Initialize GPU configuration
        self._initialize_gpu_config()
        
    def _initialize_gpu_config(self) -> None:
        """Initialize GPU configuration based on available hardware."""
        try:
            # Get GPU capabilities from the GPU manager
            gpu_manager = GPUManager()
            model_config = gpu_manager.get_model_config("solar")
            
            # Store GPU memory optimizations
            self.gpu_memory_optimizations = model_config.get("memory_optimizations", {})
            
            # Only enable GPU acceleration if available
            if model_config.get("available", False) and model_config.get("backend") == "metal":
                self.n_gpu_layers = model_config.get("n_gpu_layers", 0)
                print(f"[SOLAR MODEL] GPU acceleration enabled: {self.n_gpu_layers} layers on {model_config.get('backend')}")
                if self.gpu_memory_optimizations:
                    print(f"[SOLAR MODEL] Memory optimizations: {self.gpu_memory_optimizations}")
            else:
                print("[SOLAR MODEL] GPU acceleration not available, using CPU only")
                self.n_gpu_layers = 0
        except Exception as e:
            # Fall back to CPU mode on any error
            print(f"[SOLAR MODEL] Error initializing GPU configuration: {e}")
            print("[SOLAR MODEL] Falling back to CPU mode")
            self.n_gpu_layers = 0
            self.gpu_memory_optimizations = {}

    def _get_optimal_thread_count(self) -> int:
        """Determine the optimal thread count based on system capabilities."""
        try:
            import multiprocessing
            # Get physical CPU count
            cpu_count = multiprocessing.cpu_count()
            
            # Use 75% of available cores on all systems, with a minimum of 6
            return max(6, min(int(cpu_count * 0.75), 16))
        except Exception as e:
            print(f"[SOLAR MODEL] Error determining optimal thread count: {e}")
            return 6  # Fall back to known good value on error

    async def load(self) -> None:
        """Load the SOLAR model."""
        try:
            self.state = ModelState.LOADING
            print(f"[SOLAR MODEL] Loading model from {self.model_path}")
            print(f"[SOLAR MODEL] Using {self.n_threads} threads")
            
            # Initialize with GPU acceleration if available
            if self.n_gpu_layers > 0:
                print(f"[SOLAR MODEL] Enabling GPU acceleration with {self.n_gpu_layers} layers")
                # Create parameter dictionary with GPU optimizations
                model_params = {
                    "model_path": str(self.model_path),
                    "n_ctx": self.n_ctx,
                    "n_threads": self.n_threads,
                    "n_gpu_layers": self.n_gpu_layers
                }
                
                # Add any memory optimizations
                if hasattr(self, 'gpu_memory_optimizations') and self.gpu_memory_optimizations:
                    for key, value in self.gpu_memory_optimizations.items():
                        model_params[key] = value
                
                self._model = Llama(**model_params)
            else:
                # Standard CPU initialization
                print("[SOLAR MODEL] Using CPU-only mode")
                self._model = Llama(
                    model_path=str(self.model_path),
                    n_ctx=self.n_ctx,
                    n_threads=self.n_threads,
                    n_gpu_layers=0
                )
            
            print("[SOLAR MODEL] Model loaded successfully")
            self.state = ModelState.READY
        except Exception as e:
            self.state = ModelState.ERROR
            self._error = f"Failed to load SOLAR model: {str(e)}"
            print(f"[SOLAR MODEL] Error loading model: {str(e)}")

    async def unload(self) -> None:
        """Unload the SOLAR model."""
        if self._model is not None:
            del self._model
            self._model = None
        self.state = ModelState.UNLOADED
        print("[SOLAR MODEL] Model unloaded successfully")

    def _generate(self, prompt: str, max_tokens: int = 1000) -> str:
        """Synchronous generation method."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")

        try:
            # Format the prompt with the instruction template
            full_prompt = self.instruction_template.format(instruction=prompt)

            response = self._model(
                full_prompt,
                max_tokens=max_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
                echo=False,
                stop=["### Human:", "### Assistant:"],
                repeat_penalty=1.1,
                frequency_penalty=0.1,
                presence_penalty=0.1
            )
            return response['choices'][0]['text'].strip()
        except Exception as e:
            raise RuntimeError(f"Failed to generate response: {str(e)}")

    async def _generate_async(self, prompt: str, max_tokens: int = 1000) -> str:
        """Asynchronous generation method."""
        return self._generate(prompt, max_tokens)

    async def _generate_response_streaming(self, prompt: str, max_tokens: int = 1000) -> AsyncGenerator[str, None]:
        """Generate a response with streaming.
        
        Args:
            prompt: The prompt to generate from
            max_tokens: Maximum number of tokens to generate
            
        Yields:
            Tokens as they are generated
        """
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")

        try:
            # Format the prompt with the instruction template
            full_prompt = self.instruction_template.format(instruction=prompt)
            
            # Create a queue for streaming tokens
            queue = asyncio.Queue()
            
            # Define callback function to receive tokens
            def callback(token):
                # Add token to the queue
                asyncio.run_coroutine_threadsafe(queue.put(token), asyncio.get_event_loop())
                return True  # Continue generation
            
            # Start generation in a separate thread
            generation_task = asyncio.create_task(self._stream_in_thread(
                full_prompt, 
                max_tokens, 
                callback
            ))
            
            # Yield tokens as they become available
            while True:
                # Check if generation is complete
                if generation_task.done() and queue.empty():
                    break
                    
                try:
                    # Get token with timeout
                    token = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield token
                    queue.task_done()
                except asyncio.TimeoutError:
                    # No token available yet, check if generation is done
                    if generation_task.done():
                        break
                    # Otherwise continue waiting
                    continue
                    
            # Check for any errors in generation
            if generation_task.done():
                try:
                    await generation_task
                except Exception as e:
                    logger.error(f"Error in streaming generation: {e}")
                    raise
                    
        except Exception as e:
            logger.error(f"Error in streaming generation: {e}")
            raise RuntimeError(f"Failed to generate streaming response: {str(e)}")
    
    async def _stream_in_thread(self, prompt, max_tokens, callback):
        """Run streaming generation in a separate thread."""
        def _generate_with_callback():
            try:
                self._model(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    echo=False,
                    stop=["### Human:", "### Assistant:"],
                    repeat_penalty=1.1,
                    frequency_penalty=0.1,
                    presence_penalty=0.1,
                    stream=True,
                    callback=callback
                )
            except Exception as e:
                logger.error(f"Error in streaming thread: {e}")
                raise
                
        # Run in a thread pool
        await asyncio.to_thread(_generate_with_callback)

    def get_metadata(self) -> ModelMetadata:
        """Get model metadata."""
        return ModelMetadata(
            name="solar",
            version="base",
            source="huggingface",
            capabilities={ModelCapability.REASONING},
            description="SOLAR model in GGUF format",
            parameters={
                "context_length": self.n_ctx,
                "n_gpu_layers": self.n_gpu_layers
            },
            requirements={"llama-cpp-python": ">=0.2.0"},
            memory_requirements="8GB",
            supports_gpu=True
        )

    def validate(self) -> bool:
        """Validate model functionality."""
        if not self.is_loaded:
            return False
        try:
            # Simple test generation
            test_prompt = "Say 'hello'."
            response = self._generate(test_prompt, max_tokens=10)
            return len(response) > 0
        except Exception:
            return False

    async def generate_response(
        self,
        prompt: str,
        context: Dict[str, Any] = None,
        max_tokens: int = 1000
    ) -> str:
        """Generate a response using SOLAR."""
        if not self.is_loaded:
            raise RuntimeError("Model is not loaded")

        if not prompt or not prompt.strip():
            raise ValueError("Prompt cannot be empty")

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
            print(f"[SOLAR MODEL] Generating response for prompt (length: {len(full_prompt)} chars)")
            print(f"[SOLAR MODEL] PROMPT: {full_prompt}")
            
            result = await self._generate_async(full_prompt, max_tokens)
            
            # Log the full response without truncation
            print(f"[SOLAR MODEL] Generated response (length: {len(result)} chars)")
            print(f"[SOLAR MODEL] RESPONSE: {result}")
            
            return result
        except Exception as e:
            print(f"[SOLAR MODEL] Error generating response: {str(e)}")
            raise RuntimeError(f"Failed to generate response: {str(e)}") 