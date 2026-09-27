from fastapi import APIRouter, HTTPException, Body, Depends
from pydantic import BaseModel, Field
from pathlib import Path
import os
import aiofiles
from typing import Annotated

from ..core.logging.api_logger import api_logger

# Define the router
router = APIRouter(
    prefix="/api/v1/startup",
    tags=["Startup Status"],
)

# Define the path for the status file
# User's home directory -> .basil -> runtime -> app_startup_status.txt
STATUS_FILE_DIR = Path.home() / ".basil" / "runtime"
STATUS_FILE_PATH = STATUS_FILE_DIR / "app_startup_status.txt"

# Ensure the directory exists
os.makedirs(STATUS_FILE_DIR, exist_ok=True)

class StartupStatusUpdate(BaseModel):
    message: str = Field(..., description="The startup message to display.", example="Loading AI models...")

@router.post("/status", summary="Update startup status message", status_code=204, response_model=None)
async def update_startup_status(
    status_update: StartupStatusUpdate = Body(...)
) -> None:
    """
    Receives a startup message and writes it to the status file.
    This endpoint is typically called by the startup script (`dev.sh` or similar).
    """
    try:
        full_message = status_update.message # In the future, we could add timestamps here if needed
        async with aiofiles.open(STATUS_FILE_PATH, mode="w", encoding="utf-8") as f:
            await f.write(full_message)
        api_logger.info(f"[STARTUP_STATUS] Updated status to: '{full_message}' at {STATUS_FILE_PATH}")
    except Exception as e:
        api_logger.error(f"[STARTUP_STATUS] Error writing status file {STATUS_FILE_PATH}: {e}")
        # We don't want to fail the whole startup if this logging fails,
        # but we should be aware. For now, just log it.
        # Consider if a 500 error is appropriate if the client *depends* on this for UI.
        # For a shell script calling this, a 204 even on failure might be fine to not halt the script.
    return None # Returns 204 No Content on success

@router.get("/status", summary="Get current startup status message", response_model=StartupStatusUpdate)
async def get_startup_status():
    """
    Reads the latest startup message from the status file.
    This endpoint is polled by the Swift UI.
    """
    if not STATUS_FILE_PATH.exists():
        api_logger.warning(f"[STARTUP_STATUS] Status file not found: {STATUS_FILE_PATH}. Returning default.")
        return StartupStatusUpdate(message="Initializing...") # Default message if file doesn't exist

    try:
        async with aiofiles.open(STATUS_FILE_PATH, mode="r", encoding="utf-8") as f:
            message_content = await f.read()
        api_logger.debug(f"[STARTUP_STATUS] Read status: '{message_content.strip()}' from {STATUS_FILE_PATH}")
        return StartupStatusUpdate(message=message_content.strip())
    except Exception as e:
        api_logger.error(f"[STARTUP_STATUS] Error reading status file {STATUS_FILE_PATH}: {e}")
        raise HTTPException(status_code=500, detail="Could not read startup status file.")

# Helper to initialize the status file on first run or if it's missing
async def initialize_status_file_if_needed():
    if not STATUS_FILE_PATH.exists():
        try:
            async with aiofiles.open(STATUS_FILE_PATH, mode="w", encoding="utf-8") as f:
                await f.write("Initializing...")
            api_logger.info(f"[STARTUP_STATUS] Initialized status file at {STATUS_FILE_PATH}")
        except Exception as e:
            api_logger.error(f"[STARTUP_STATUS] Could not initialize status file at {STATUS_FILE_PATH}: {e}")

# Note: Depending on your FastAPI app structure, you might call initialize_status_file_if_needed()
# during app startup (e.g., in a startup event handler in your main.py or app factory).
# For now, the GET endpoint handles the "file not found" case by returning a default. 