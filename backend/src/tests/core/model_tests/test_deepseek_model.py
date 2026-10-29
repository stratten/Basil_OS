#!/usr/bin/env python3
"""
DeepSeek Model Direct Test Tool

This script directly tests the DeepSeek model implementation in isolation,
without going through the API layer.
"""

import os
import sys
import asyncio
import logging
from pathlib import Path
import time

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

# Import the DeepSeek model and required types
from api.core.models.reasoning.deepseek_model import DeepSeekModel
from api.core.models.model_types import ModelCapability

async def test_deepseek_model():
    """Test the DeepSeek model loading and generation."""
    logging.info("Testing DeepSeek model loading...")
    
    # Path to the model
    model_path = Path(os.path.expanduser("~/.basil/models/deepseek-r1-qwen-7b-base"))
    logging.info(f"Model path: {model_path}")
    
    # Create the model instance
    logging.info("Creating DeepSeek model instance...")
    model = DeepSeekModel(model_path=model_path, required_capabilities={ModelCapability.REASONING})
    
    try:
        # Load the model
        logging.info("Loading model...")
        start_time = asyncio.get_event_loop().time()
        await model.load()
        end_time = asyncio.get_event_loop().time()
        loading_time = end_time - start_time
        logging.info(f"Model loaded successfully in {loading_time:.2f} seconds!")
        
        # Check which loading method was used
        if model.llm is not None:
            logging.info("Model was loaded using vLLM")
        else:
            logging.info("Model was loaded using traditional method")
        
        # Test simple generation
        test_prompt = "Please solve this simple math problem: 2 + 2 = ? Provide only the numerical answer."
        logging.info(f"Testing simple generation with prompt: '{test_prompt}'")
        logging.info(f"Generating response for prompt (length: {len(test_prompt)} chars)")
        logging.info(f"Prompt preview: {test_prompt[:20]}...")
        
        start_time = time.time()
        # Use more aggressive parameters for faster generation
        response = await model.generate_response(
            test_prompt, 
            max_tokens=20,  # Reduce max tokens further
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
        logging.error(f"Error testing DeepSeek model: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    # Run the test
    logging.info("Starting DeepSeek model test")
    success = asyncio.run(test_deepseek_model())
    
    # Exit with appropriate code
    logging.info(f"Test completed with success={success}")
    sys.exit(0 if success else 1) 