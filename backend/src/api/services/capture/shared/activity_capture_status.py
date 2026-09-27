"""Shared status values for automatic activity capture processing."""

from enum import Enum


class ActivityCaptureStatus(Enum):
    """Status of activity capture records."""

    PENDING = "PENDING"  # Screenshot taken, awaiting OCR and AI processing
    OCR_COMPLETE = "OCR_COMPLETE"  # OCR done, awaiting AI analysis
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"  # Fully processed
    FAILED = "FAILED"
