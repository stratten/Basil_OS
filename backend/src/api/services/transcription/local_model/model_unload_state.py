"""Shared state for the WebSocket-managed transcription unload task."""

from __future__ import annotations

import asyncio
from typing import Optional

from api.services.transcription.local_model.model_unload_scheduler import cancel_model_unload

model_unload_task: Optional[asyncio.Task] = None


def cancel_scheduled_model_unload() -> None:
    """Cancel the current scheduled transcription model unload task, if present."""
    global model_unload_task
    model_unload_task = cancel_model_unload(model_unload_task)
