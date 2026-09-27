#!/usr/bin/env python3
"""
Llama-3.2-3B-Instruct GGUF Model Test Tool

This script tests the Llama-3.2-3B-Instruct GGUF model using our LlamaCppModel implementation.
"""

import os
import sys
import asyncio
import logging
from pathlib import Path
import time
import pytest

pytestmark = pytest.mark.manual

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Add the Basil directory to the Python path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(SCRIPT_DIR)

# Import the LlamaCppModel and required types
from api.core.models.reasoning.llama_cpp_model import LlamaCppModel
from api.core.models.model_types import ModelCapability

@pytest.mark.asyncio
async def test_llama32_model():
    """Test the Llama-3.2-3B-Instruct GGUF model loading and generation."""
    logging.info("Testing Llama-3.2-3B-Instruct GGUF model loading...")
    
    # Path to the model - adjust this to your GGUF model path
    model_path = Path(os.path.expanduser("~/.basil/models/Llama-3.2-3B-Instruct-Q6_K_L.gguf"))
    logging.info(f"Model path: {model_path}")
    
    # Check if the model file exists
    if not model_path.exists():
        logging.error(f"Model file not found at {model_path}")
        logging.info("Please download the model from: https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/blob/main/Llama-3.2-3B-Instruct-Q6_K_L.gguf")
        return False
    
    # Create the model instance
    logging.info("Creating LlamaCppModel instance...")
    model = LlamaCppModel(model_path=model_path, required_capabilities={ModelCapability.REASONING})
    
    try:
        # Load the model
        logging.info("Loading model...")
        start_time = asyncio.get_event_loop().time()
        await model.load()
        end_time = asyncio.get_event_loop().time()
        loading_time = end_time - start_time
        logging.info(f"Model loaded successfully in {loading_time:.2f} seconds!")
        
        # Test simple generation
        test_prompt = "Please solve this simple math problem: 2 + 2 = ? Provide only the numerical answer."
        logging.info(f"Testing simple generation with prompt: '{test_prompt}'")
        logging.info(f"Generating response for prompt (length: {len(test_prompt)} chars)")
        logging.info(f"Prompt preview: {test_prompt[:20]}...")
        
        start_time = time.time()
        # Use aggressive parameters for faster generation
        response = await model.generate_response(
            test_prompt, 
            max_tokens=20,  # Reduce max tokens for faster generation
            temperature=0.0,  # Use greedy decoding
            top_p=1.0,  # Disable top_p filtering
            top_k=1  # Most restrictive top_k
        )
        generation_time = time.time() - start_time
        
        logging.info(f"Generated response (length: {len(response)} chars)")
        logging.info(f"Full response: {response}")
        logging.info(f"Generation completed in {generation_time:.2f} seconds")
        logging.info(f"Result: {response}")
        
        # Unload the model
        logging.info("Unloading model...")
        await model.unload()
        logging.info("Model unloaded successfully!")
        
        return True
    except Exception as e:
        logging.error(f"Error testing Llama-3.2-3B-Instruct GGUF model: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    # Run the test
    logging.info("Starting Llama-3.2-3B-Instruct GGUF model test")
    success = asyncio.run(test_llama32_model())
    
    # Exit with appropriate code
    logging.info(f"Test completed with success={success}")
    sys.exit(0 if success else 1) 