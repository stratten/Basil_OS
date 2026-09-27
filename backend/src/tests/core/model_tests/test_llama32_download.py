#!/usr/bin/env python3
"""
Test script for downloading the Llama-3.2-3B-Instruct model through the model downloader pipeline.
"""

import os
import sys
import asyncio
import logging
from pathlib import Path
import time
import aiohttp
import tempfile
import shutil
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

# Import the ModelDownloader and LlamaCppModel
from api.core.models.model_downloader import ModelDownloader
from api.core.models.reasoning.llama_cpp_model import LlamaCppModel
from api.core.models.model_types import ModelCapability

async def progress_callback(progress: float):
    """Callback to display download progress."""
    percent = int(progress * 100)
    bar_length = 30
    filled_length = int(bar_length * progress)
    bar = '█' * filled_length + '-' * (bar_length - filled_length)
    print(f'\rDownload progress: [{bar}] {percent}%', end='', flush=True)
    if progress >= 1.0:
        print()  # New line after completion

async def direct_download_model():
    """Directly download the model file using aiohttp."""
    logging.info("Attempting direct download of Llama-3.2-3B-Instruct model")
    
    # Model details
    model_url = "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q6_K_L.gguf"
    models_dir = Path.home() / ".basil" / "models"
    model_path = models_dir / "llama32-3b-instruct-base.gguf"
    
    # Create models directory if it doesn't exist
    models_dir.mkdir(parents=True, exist_ok=True)
    
    # Create a temporary directory for the download
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        temp_file = temp_path / "Llama-3.2-3B-Instruct-Q6_K_L.gguf"
        
        logging.info(f"Created temporary directory: {temp_path}")
        
        try:
            # Configure timeout and connection settings
            timeout = aiohttp.ClientTimeout(total=3600)  # 1 hour timeout
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                start_time = time.time()
                logging.info(f"Starting download from {model_url}")
                
                async with session.get(model_url) as response:
                    if response.status != 200:
                        logging.error(f"Failed to download model: HTTP {response.status}")
                        return False
                    
                    total_size = int(response.headers.get("content-length", 0))
                    chunk_size = 1024 * 1024  # 1MB chunks
                    downloaded = 0
                    
                    logging.info(f"Total file size: {total_size / (1024*1024):.2f} MB")
                    
                    with open(temp_file, "wb") as f:
                        async for chunk in response.content.iter_chunked(chunk_size):
                            if chunk:  # Filter out keep-alive chunks
                                f.write(chunk)
                                downloaded += len(chunk)
                                progress = downloaded / total_size if total_size > 0 else 0
                                
                                # Log progress every 5%
                                if int(progress * 100) % 5 == 0:
                                    elapsed = time.time() - start_time
                                    speed = downloaded / elapsed / 1024 / 1024 if elapsed > 0 else 0
                                    eta = (total_size - downloaded) / (speed * 1024 * 1024) if speed > 0 else 0
                                    logging.info(f"Progress: {progress:.1%} ({downloaded/(1024*1024):.1f}/{total_size/(1024*1024):.1f} MB) - Speed: {speed:.2f} MB/s - ETA: {eta:.0f}s")
                                
                                await progress_callback(progress)
                
                download_time = time.time() - start_time
                logging.info(f"Download completed in {download_time:.2f} seconds")
                
                # Move the file to the final location
                if model_path.exists():
                    logging.info(f"Removing existing model file: {model_path}")
                    model_path.unlink()
                
                logging.info(f"Moving file from {temp_file} to {model_path}")
                shutil.copy2(temp_file, model_path)
                logging.info(f"File successfully moved to: {model_path}")
                
                return True
                
        except asyncio.TimeoutError:
            logging.error("Download timed out after 1 hour")
            return False
        except Exception as e:
            logging.error(f"Error during download: {type(e).__name__}: {str(e)}", exc_info=True)
            return False

@pytest.mark.asyncio
async def test_llama32_download_and_use():
    """Test downloading and using the Llama-3.2-3B-Instruct model."""
    logging.info("Testing Llama-3.2-3B-Instruct model download and usage")
    
    # Initialize the model downloader
    models_dir = Path.home() / ".basil" / "models"
    downloader = ModelDownloader(models_dir)
    
    model_type = "llama32-3b-instruct"
    variant = "base"
    
    # Check if model is already installed
    installed_models = downloader.get_installed_models()
    if model_type in installed_models and variant in installed_models[model_type]["variants"]:
        logging.info(f"Model {model_type}-{variant} is already installed")
        model_path = Path(installed_models[model_type]["variants"][variant]["path"])
    else:
        # Try direct download first
        logging.info("Attempting direct download method")
        success = await direct_download_model()
        
        if success:
            logging.info("Direct download successful")
            model_path = models_dir / "llama32-3b-instruct-base.gguf"
        else:
            # Fall back to the model downloader
            logging.info("Direct download failed, falling back to model downloader")
            try:
                model_path = await downloader.download_model(
                    model_type=model_type,
                    variant=variant,
                    progress_callback=progress_callback
                )
                logging.info(f"Model downloaded successfully to {model_path}")
            except Exception as e:
                logging.error(f"Failed to download model: {e}", exc_info=True)
                return False
    
    # Test the model
    logging.info(f"Testing model with LlamaCppModel implementation")
    model = LlamaCppModel(model_path=model_path, required_capabilities={ModelCapability.REASONING})
    
    try:
        # Load the model
        logging.info("Loading model...")
        await model.load()
        logging.info("Model loaded successfully!")
        
        # Test simple generation
        test_prompt = "Please solve this simple math problem: 2 + 2 = ? Provide only the numerical answer."
        logging.info(f"Testing generation with prompt: '{test_prompt}'")
        
        response = await model.generate_response(
            test_prompt, 
            max_tokens=20,
            temperature=0.0,
            top_p=1.0,
            top_k=1
        )
        
        logging.info(f"Generated response: {response}")
        
        # Unload the model
        logging.info("Unloading model...")
        await model.unload()
        logging.info("Model unloaded successfully!")
        
        return True
    except Exception as e:
        logging.error(f"Error testing model: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    # Run the test
    logging.info("Starting Llama-3.2-3B-Instruct model download and test")
    success = asyncio.run(test_llama32_download_and_use())
    
    # Exit with appropriate code
    logging.info(f"Test completed with success={success}")
    sys.exit(0 if success else 1) 