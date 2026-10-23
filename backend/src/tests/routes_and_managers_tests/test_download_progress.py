#!/usr/bin/env python3
"""
Test script for verifying progress reporting during model downloads.
This script simulates both direct API calls and task queue downloads.
"""

import os
import sys
import asyncio
import logging
import time
from pathlib import Path
import json
import uuid
import aiohttp
import tempfile
import shutil
import pytest

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

# Import the necessary modules
from api.core.models import model_downloader as model_downloader_module
from api.core.models.model_downloader import ModelDownloader

@pytest.mark.asyncio
async def test_direct_download_progress():
    """Test progress reporting for direct downloads."""
    logging.info("Testing progress reporting for direct downloads")
    
    # Create a test file to download
    test_file_size = 10 * 1024 * 1024  # 10MB
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_file.write(os.urandom(test_file_size))
        test_file_path = temp_file.name
    
    logging.info(f"Created test file: {test_file_path} ({test_file_size / (1024*1024):.2f} MB)")
    
    # Create a simple HTTP server to serve the test file
    from aiohttp import web
    
    async def handle_download(request):
        return web.FileResponse(test_file_path)
    
    app = web.Application()
    app.router.add_get('/test_file', handle_download)
    
    # Start the server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 8080)
    await site.start()
    
    logging.info("Test server started at http://localhost:8080/test_file")
    
    try:
        # Track progress updates
        progress_updates = []
        
        async def progress_callback(progress):
            progress_updates.append(progress)
            logging.info(f"Progress update: {progress:.2%}")
        
        # Download the test file
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            logging.info("Starting test download")
            
            async with session.get('http://localhost:8080/test_file') as response:
                if response.status != 200:
                    logging.error(f"Failed to download test file: HTTP {response.status}")
                    return False
                
                total_size = int(response.headers.get('content-length', 0))
                chunk_size = 1024 * 256  # 256KB chunks to get more progress updates
                downloaded = 0
                
                with tempfile.NamedTemporaryFile(delete=False) as output_file:
                    async for chunk in response.content.iter_chunked(chunk_size):
                        if chunk:
                            output_file.write(chunk)
                            downloaded += len(chunk)
                            progress = downloaded / total_size if total_size > 0 else 0
                            await progress_callback(progress)
                            
                            # Simulate slower download to see progress updates
                            await asyncio.sleep(0.1)
            
            download_time = time.time() - start_time
            logging.info(f"Download completed in {download_time:.2f} seconds")
            
            # Verify progress updates
            if len(progress_updates) < 5:
                pytest.fail(f"Too few progress updates: {len(progress_updates)}")
            
            if progress_updates[-1] < 0.99:
                pytest.fail(f"Final progress update not complete: {progress_updates[-1]:.2%}")
            
            logging.info(f"Received {len(progress_updates)} progress updates")
            logging.info(f"Progress updates: {[f'{p:.2f}' for p in progress_updates[:5]]}... (first 5)")
            
            return True
    finally:
        # Clean up
        await runner.cleanup()
        os.unlink(test_file_path)
        logging.info("Test server stopped and test file removed")

@pytest.mark.asyncio
async def test_model_downloader_progress(monkeypatch, tmp_path):
    """Test progress reporting in the ModelDownloader class."""
    logging.info("Testing progress reporting in ModelDownloader")
    
    # Initialize the model downloader
    models_dir = tmp_path / "models"
    model_id = "test_model-test"
    model_config = {
        "display_name": "Test Model",
        "download_url": "http://localhost:8080/test_file",
        "on_disk_name": "test_model",
    }
    monkeypatch.setattr(
        model_downloader_module,
        "get_model",
        lambda requested_model_id: model_config if requested_model_id == model_id else None,
    )
    downloader = ModelDownloader(models_dir)
    monkeypatch.setattr(
        downloader,
        "_get_model_path_for_id",
        lambda requested_model_id: models_dir / "test_model.bin",
    )
    
    # Create a test file to download
    test_file_size = 10 * 1024 * 1024  # 10MB
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        temp_file.write(os.urandom(test_file_size))
        test_file_path = temp_file.name
    
    logging.info(f"Created test file: {test_file_path} ({test_file_size / (1024*1024):.2f} MB)")
    
    # Create a simple HTTP server to serve the test file
    from aiohttp import web
    
    async def handle_download(request):
        return web.FileResponse(test_file_path)
    
    app = web.Application()
    app.router.add_get('/test_file', handle_download)
    
    # Start the server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 8080)
    await site.start()
    
    logging.info("Test server started at http://localhost:8080/test_file")
    
    try:
        # Track progress updates
        progress_updates = []
        
        async def progress_callback(progress, _status, _metadata):
            progress_updates.append(progress)
            logging.info(f"Progress update: {progress:.2%}")
        
        # Download the model
        try:
            model_path = await downloader.download_model(
                model_type="test_model",
                variant="test",
                progress_callback=progress_callback
            )
            
            logging.info(f"Model downloaded to: {model_path}")
            
            # Verify progress updates
            if len(progress_updates) < 5:
                pytest.fail(f"Too few progress updates: {len(progress_updates)}")
            
            if progress_updates[-1] < 0.99:
                pytest.fail(f"Final progress update not complete: {progress_updates[-1]:.2%}")
            
            logging.info(f"Received {len(progress_updates)} progress updates")
            logging.info(f"Progress updates: {[f'{p:.2f}' for p in progress_updates[:5]]}... (first 5)")
            
            assert model_path.exists(), "downloaded model artifact should exist"
        except Exception as e:
            logging.error(f"Error downloading model: {e}", exc_info=True)
            raise
    finally:
        # Clean up
        await runner.cleanup()
        os.unlink(test_file_path)
        if models_dir.exists():
            shutil.rmtree(models_dir)
        logging.info("Test server stopped and test files removed")

if __name__ == "__main__":
    # Run the tests
    logging.info("Starting download progress tests")
    
    # Run the direct download test
    direct_test_success = asyncio.run(test_direct_download_progress())
    logging.info(f"Direct download test completed with success={direct_test_success}")
    
    # Run the model downloader test
    model_test_success = asyncio.run(test_model_downloader_progress())
    logging.info(f"Model downloader test completed with success={model_test_success}")
    
    # Exit with appropriate code
    success = direct_test_success and model_test_success
    logging.info(f"All tests completed with success={success}")
    sys.exit(0 if success else 1) 