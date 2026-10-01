#!/usr/bin/env python3
import sys
import os
import asyncio
import logging
import time
import json
import aiohttp
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.core.security.backend_credentials import BACKEND_TOKEN_HEADER, load_host_token  # noqa: E402

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("download_progress_checker")

# Set the model type and variant
MODEL_TYPE = "llama32-3b-instruct"
VARIANT = "base"

async def check_progress():
    """Check the download progress for the specified model."""
    logger.info(f"Checking download progress for {MODEL_TYPE}-{VARIANT}")
    
    # API endpoint for checking download progress
    api_url = "http://localhost:8000/models/{model_type}/{variant}/download/progress"
    url = api_url.format(model_type=MODEL_TYPE, variant=VARIANT)
    
    try:
        async with aiohttp.ClientSession(headers={BACKEND_TOKEN_HEADER: load_host_token()}) as session:
            while True:
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            progress = data.get("progress", 0) * 100
                            logger.info(f"Download progress: {progress:.1f}%")
                            
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
                await asyncio.sleep(5)
    except KeyboardInterrupt:
        logger.info("Progress checking interrupted by user")
        return False

async def check_task_status():
    """Check the status of the task queue download."""
    logger.info(f"Checking task status for {MODEL_TYPE}-{VARIANT}")
    
    # API endpoint for checking task status
    api_url = "http://localhost:8000/models/download/status"
    
    try:
        async with aiohttp.ClientSession(headers={BACKEND_TOKEN_HEADER: load_host_token()}) as session:
            while True:
                try:
                    async with session.get(api_url) as response:
                        if response.status == 200:
                            data = await response.json()
                            logger.info(f"Task status: {json.dumps(data, indent=2)}")
                            
                            # If we have a specific task for our model
                            tasks = data.get("tasks", [])
                            for task in tasks:
                                if MODEL_TYPE in task.get("model", ""):
                                    status = task.get("status")
                                    progress = task.get("progress", 0) * 100
                                    logger.info(f"Task for {MODEL_TYPE}: Status={status}, Progress={progress:.1f}%")
                                    
                                    if status == "complete":
                                        logger.info("Download task complete!")
                                        return True
                        else:
                            error_text = await response.text()
                            logger.error(f"Error checking task status: {response.status} - {error_text}")
                except Exception as e:
                    logger.error(f"Error during task status check: {str(e)}")
                
                # Wait before checking again
                await asyncio.sleep(5)
    except KeyboardInterrupt:
        logger.info("Task status checking interrupted by user")
        return False

async def main():
    """Run both progress checks in parallel."""
    logger.info("Starting download progress monitoring")
    
    # Run both checks in parallel
    await asyncio.gather(
        check_progress(),
        check_task_status()
    )
    
    logger.info("Download progress monitoring complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Monitoring interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")
        sys.exit(1) 