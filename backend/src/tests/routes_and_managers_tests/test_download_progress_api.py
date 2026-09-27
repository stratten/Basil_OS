#!/usr/bin/env python3
"""
Test script to verify that the download progress API endpoints work correctly.
This script simulates a UI client polling for download progress.
"""

import os
import sys
import asyncio
import logging
import time
import json
import aiohttp
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("download_progress_api_test")

# Set the model type and variant
MODEL_TYPE = "llama32-3b-instruct"
VARIANT = "base"

# API base URL
API_BASE_URL = "http://localhost:8000"

async def poll_progress():
    """Poll the download progress endpoint."""
    url = f"{API_BASE_URL}/models/{MODEL_TYPE}/{VARIANT}/download/progress"
    
    try:
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            progress = data.get("progress", 0) * 100
                            
                            # Display progress bar
                            bar_length = 30
                            filled_length = int(bar_length * progress / 100)
                            bar = '█' * filled_length + '-' * (bar_length - filled_length)
                            logger.info(f"Progress: [{bar}] {progress:.1f}%")
                            
                            # If download is complete, exit
                            if progress >= 99.9:
                                logger.info("Download complete!")
                                return True
                        else:
                            error_text = await response.text()
                            logger.error(f"Error checking progress: {response.status} - {error_text}")
                except Exception as e:
                    logger.error(f"Error during progress check: {str(e)}")
                
                # Wait before checking again
                await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Progress checking interrupted by user")
        return False

async def poll_task_status():
    """Poll the task status endpoint."""
    url = f"{API_BASE_URL}/models/download/status"
    
    try:
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            tasks = data.get("tasks", [])
                            
                            if tasks:
                                logger.info(f"Found {len(tasks)} tasks:")
                                for task in tasks:
                                    model = task.get("model", "unknown")
                                    status = task.get("status", "unknown")
                                    progress = task.get("progress", 0) * 100
                                    
                                    if MODEL_TYPE in model:
                                        logger.info(f"Task for {model}: Status={status}, Progress={progress:.1f}%")
                                        
                                        # If download is complete, exit
                                        if status == "completed":
                                            logger.info("Download task complete!")
                                            return True
                            else:
                                logger.info("No tasks found")
                        else:
                            error_text = await response.text()
                            logger.error(f"Error checking task status: {response.status} - {error_text}")
                except Exception as e:
                    logger.error(f"Error during task status check: {str(e)}")
                
                # Wait before checking again
                await asyncio.sleep(2)
    except KeyboardInterrupt:
        logger.info("Task status checking interrupted by user")
        return False

async def main():
    """Run both polling functions in parallel."""
    logger.info("Starting download progress API test")
    
    # Run both polling functions in parallel
    await asyncio.gather(
        poll_progress(),
        poll_task_status()
    )
    
    logger.info("Download progress API test complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
        sys.exit(1) 