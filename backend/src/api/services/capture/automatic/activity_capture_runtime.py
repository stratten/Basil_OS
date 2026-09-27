"""Runtime holder for automatic activity-capture services."""

from __future__ import annotations

import logging
from typing import Optional

from api.core.knowledge.sqlite.sqlite_knowledge_service import SQLiteKnowledgeService
from api.services.capture.automatic.automatic_activity_capture_service import (
    AutomaticActivityCaptureService,
)
from api.services.capture.automatic.automatic_activity_processing_service import (
    AutomaticActivityProcessingService,
)

logger = logging.getLogger(__name__)

automatic_capture_service: Optional[AutomaticActivityCaptureService] = None
automatic_processing_service: Optional[AutomaticActivityProcessingService] = None


async def initialize_automatic_activity_services(
    knowledge_service: SQLiteKnowledgeService,
    model_service,
    image_processor,
) -> None:
    """Initialize the global automatic activity services."""
    global automatic_capture_service, automatic_processing_service

    logger.info("🔄 Starting Automatic Activity Services initialization...")

    try:
        if automatic_capture_service is None:
            logger.info("📸 Creating AutomaticActivityCaptureService instance...")
            automatic_capture_service = AutomaticActivityCaptureService(knowledge_service)
            logger.info("✅ Automatic capture service initialized successfully")
        else:
            logger.warning("⚠️  Automatic capture service already initialized")

        if automatic_processing_service is None:
            logger.info("🔄 Creating AutomaticActivityProcessingService instance...")
            automatic_processing_service = AutomaticActivityProcessingService(
                knowledge_service,
                model_service,
                image_processor,
            )
            logger.info("✅ Automatic processing service initialized successfully")
        else:
            logger.warning("⚠️  Automatic processing service already initialized")

        # Start the processing service (always runs for scheduled processing)
        await automatic_processing_service.start_processing_service()
        logger.info("🔄 Automatic processing service started")

    except Exception as e:
        logger.error(f"❌ Failed to initialize Automatic Activity Services: {e}", exc_info=True)
        raise


async def cleanup_automatic_activity_services() -> None:
    """Clean up the global automatic activity services."""
    global automatic_capture_service, automatic_processing_service

    logger.info("🧹 Cleaning up Automatic Activity Services...")

    if automatic_capture_service is not None:
        try:
            await automatic_capture_service.stop_activity_capture()
            logger.info("🛑 Automatic capture service stopped")
        except Exception as e:
            logger.error(f"Error stopping capture service: {e}")
        automatic_capture_service = None

    if automatic_processing_service is not None:
        try:
            await automatic_processing_service.stop_processing_service()
            logger.info("🛑 Automatic processing service stopped")
        except Exception as e:
            logger.error(f"Error stopping processing service: {e}")
        automatic_processing_service = None

    logger.info("✅ Automatic Activity Services cleaned up successfully")


def get_automatic_capture_service_instance() -> Optional[AutomaticActivityCaptureService]:
    """Get the capture service instance (can be None)."""
    return automatic_capture_service


def get_activity_capture_scheduler() -> Optional[AutomaticActivityCaptureService]:
    """Return the automatic capture service used by settings updates."""
    return automatic_capture_service


def get_automatic_processing_service_instance() -> Optional[AutomaticActivityProcessingService]:
    """Get the processing service instance (can be None)."""
    return automatic_processing_service
