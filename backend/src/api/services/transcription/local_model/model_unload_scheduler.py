"""Shared transcription model unload scheduling helpers."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def unload_model_after_delay(transcription_service, delay_seconds: int) -> None:
    """Schedule model unloading after a specified delay."""
    logger.info(f"Scheduling model unload after {delay_seconds} seconds")
    try:
        await asyncio.sleep(delay_seconds)
        if transcription_service.is_model_loaded():
            logger.info(f"Unloading transcription model after {delay_seconds}s delay")
            transcription_service.unload_model()
            logger.info("Model unload complete")
        else:
            logger.info("Model already unloaded, no action needed")
    except asyncio.CancelledError:
        logger.info("Model unload task canceled")
        raise
    except Exception as e:
        logger.error(f"Error during scheduled model unload: {e}")


def schedule_model_unload(
    transcription_service,
    delay_seconds: int,
    model_unload_task: Optional[asyncio.Task],
) -> Optional[asyncio.Task]:
    """Schedule model unloading and cancel any existing unload task."""
    if model_unload_task is not None and not model_unload_task.done():
        logger.info("Canceling existing model unload task")
        model_unload_task.cancel()
    if delay_seconds == 0:
        logger.info("Unloading model immediately")
        transcription_service.unload_model()
        return None
    return asyncio.create_task(unload_model_after_delay(transcription_service, delay_seconds))


def cancel_model_unload(model_unload_task: Optional[asyncio.Task]) -> Optional[asyncio.Task]:
    """Cancel any scheduled model unload."""
    if model_unload_task is not None and not model_unload_task.done():
        logger.info("Canceling model unload task")
        model_unload_task.cancel()
        return None
    return model_unload_task
