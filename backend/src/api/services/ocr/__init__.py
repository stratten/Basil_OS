"""OCR service package for text extraction from images."""

from .ocr_service import OCRService
from .ocr_routes import ocr_router

__all__ = ["OCRService", "ocr_router"] 