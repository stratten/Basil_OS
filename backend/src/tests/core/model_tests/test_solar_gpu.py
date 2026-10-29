import sys
import os
import asyncio
import time
from pathlib import Path
import platform
import pytest

# Add the project root to Python path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.core.models.model_types import ModelCapability
from api.core.models.reasoning.solar_model import SolarModel
from api.core.models.gpu_manager import GPUManager
from api.core.services.model_service import ModelService, get_model_service


@pytest.mark.asyncio
async def test_solar_performance():
    """Test the performance of the SOLAR model with GPU acceleration."""
    print("\n" + "=" * 70)
    print("SOLAR MODEL GPU ACCELERATION TEST")
    print("=" * 70)
    
    # Check if we're on Apple Silicon
    is_apple_silicon = platform.system() == "Darwin" and platform.machine() == "arm64"
    print(f"Running on: {platform.system()} {platform.machine()}")
    print(f"Apple Silicon detected: {is_apple_silicon}")
    
    # Get GPU capabilities
    gpu_manager = GPUManager()
    print(f"GPU capabilities: {gpu_manager.capabilities}")
    
    # Test prompts of increasing complexity
    test_prompts = [
        "Explain the concept of recursion in programming.",
        "Write a Python function to calculate Fibonacci numbers using dynamic programming.",
        "Explain the differences between transformer models and recurrent neural networks in detail, including their architectures, training methods, and applications in natural language processing."
    ]
    
    # Get model service to access the model
    model_service = get_model_service()
    
    # Run tests for each prompt
    for i, prompt in enumerate(test_prompts):
        print(f"\nTest {i+1}: Prompt length {len(prompt)} characters")
        print(f"Prompt: {prompt[:50]}..." if len(prompt) > 50 else f"Prompt: {prompt}")
        
        try:
            # Load model and time the inference
            start_time = time.time()
            model = await model_service.load_model("solar", "base", {ModelCapability.REASONING})
            load_time = time.time() - start_time
            print(f"Model loaded in {load_time:.2f} seconds")
            
            # Check if GPU acceleration is actually enabled
            if hasattr(model, 'n_gpu_layers') and model.n_gpu_layers > 0:
                print(f"GPU acceleration active: {model.n_gpu_layers} layers")
            else:
                print("Running in CPU-only mode")
            
            # Generate response and measure time
            gen_start = time.time()
            response = await model.generate_response(prompt, max_tokens=200)
            gen_time = time.time() - gen_start
            
            print(f"Response generated in {gen_time:.2f} seconds")
            print(f"Response length: {len(response)} characters")
            print(f"First 100 chars: {response[:100]}...")
            
            tokens_per_second = 200 / gen_time
            print(f"Performance: {tokens_per_second:.2f} tokens/second")
            
            # Clean up for next test
            await model_service.unload_model("solar", "base")
            print("Model unloaded for next test")
            
        except Exception as e:
            print(f"Error during test: {e}")
    
    print("\n" + "=" * 70)
    print("TEST COMPLETED")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_solar_performance()) 