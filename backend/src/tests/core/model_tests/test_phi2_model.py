#!/usr/bin/env python3
"""
Phi-2 Model Direct Test Tool

This script tests the Microsoft Phi-2 model, which is smaller (2.7B parameters)
and might be faster than DeepSeek for simple tasks.
"""

import os
import sys
import time
import torch
import pytest
from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

_RUNTIME_VALIDATION_ENV = "RUN_PHI2_RUNTIME_VALIDATION"

pytestmark = pytest.mark.skipif(
    os.getenv(_RUNTIME_VALIDATION_ENV) != "1",
    reason=f"Set {_RUNTIME_VALIDATION_ENV}=1 to download and run the Phi-2 runtime validation.",
)

# Configure logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

def test_phi2_model():
    """Test the Phi-2 model loading and generation."""
    logging.info("Testing Phi-2 model loading...")
    
    # Check for Metal acceleration
    if hasattr(torch, 'mps') and torch.backends.mps.is_available():
        device = "mps"
        logging.info("Using Metal acceleration for Phi-2 model")
    else:
        device = "cpu"
        logging.info("Using CPU for Phi-2 model")
    
    # Load the model
    start_time = time.time()
    logging.info("Loading Phi-2 tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained("microsoft/phi-2", trust_remote_code=True)
    
    logging.info("Loading Phi-2 model...")
    model = AutoModelForCausalLM.from_pretrained(
        "microsoft/phi-2",
        torch_dtype=torch.float16,
        device_map={"": device},
        trust_remote_code=True,
    )
    
    # Create pipeline
    logging.info("Creating text generation pipeline...")
    pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        device_map={"": device},
    )
    
    loading_time = time.time() - start_time
    logging.info(f"Model loaded successfully in {loading_time:.2f} seconds!")
    
    # Test simple generation
    test_prompt = "Please solve this simple math problem: 2 + 2 = ? Provide only the numerical answer."
    logging.info(f"Testing simple generation with prompt: '{test_prompt}'")
    
    # Generation parameters
    generation_config = {
        "max_new_tokens": 20,
        "do_sample": False,
        "temperature": 0.1,
        "return_full_text": True
    }
    
    # Generate response
    start_time = time.time()
    outputs = pipe(test_prompt, **generation_config)
    response = outputs[0]["generated_text"][len(test_prompt):]
    generation_time = time.time() - start_time
    
    logging.info(f"Generated response (length: {len(response)} chars)")
    logging.info(f"Full response: {response}")
    logging.info(f"Generation completed in {generation_time:.2f} seconds")
    
    return True

if __name__ == "__main__":
    # Run the test
    logging.info("Starting Phi-2 model test")
    success = test_phi2_model()
    
    # Exit with appropriate code
    logging.info(f"Test completed with success={success}")
    sys.exit(0 if success else 1) 