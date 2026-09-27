"""Current-context capture service for ambient suggestions."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from api.core.logging.api_logger import api_logger
from api.services.capture.shared.window_capture_bridge import request_swift_window_capture
from api.services.ocr.ocr_service import OCRService

from .models import AmbientContextEnvelope


class AmbientSuggestionCaptureService:
    """Capture current window context and OCR text for ambient suggestions."""

    def __init__(self, ocr_service: Optional[OCRService] = None) -> None:
        self.ocr_service = ocr_service or OCRService(development_mode=True)
        self.logger = api_logger.getChild("ambient_suggestion_capture")

    async def capture_current_context(self) -> AmbientContextEnvelope:
        """Capture the current window and return a typed context envelope."""
        capture_id = str(uuid.uuid4())
        timestamp = datetime.now()
        capture_result = await request_swift_window_capture("ambient suggestion")

        if not capture_result or not capture_result.get("success"):
            message = capture_result.get("message", "Unknown capture failure") if capture_result else "No capture result"
            raise RuntimeError(f"Ambient suggestion capture failed: {message}")

        app_name = capture_result.get("app_name") or "Unknown"
        window_title = capture_result.get("window_title") or ""
        image_path = capture_result.get("image_path")
        ocr_text = ""

        if image_path:
            ocr_result = self.ocr_service.extract_text(image_path)
            if ocr_result.status == "success":
                ocr_text = ocr_result.processed_text or ocr_result.cleaned_text or ocr_result.raw_text or ""
            else:
                self.logger.warning("Ambient OCR failed for %s: %s", image_path, ocr_result.status)

        structured_context: Dict[str, Any] = {
            "capture_method": capture_result.get("capture_method"),
            "has_image": capture_result.get("has_image", bool(image_path)),
        }
        fingerprint = self._build_fingerprint(app_name, window_title, ocr_text, structured_context)

        return AmbientContextEnvelope(
            capture_id=capture_id,
            timestamp=timestamp,
            app_name=app_name,
            window_title=window_title,
            image_path=image_path,
            ocr_text=ocr_text,
            structured_context=structured_context,
            content_fingerprint=fingerprint,
        )

    @staticmethod
    def _build_fingerprint(
        app_name: str,
        window_title: str,
        ocr_text: str,
        structured_context: Dict[str, Any],
    ) -> str:
        normalized = "\n".join(
            [
                app_name.strip().lower(),
                window_title.strip().lower(),
                " ".join(ocr_text.split()).lower(),
                str(structured_context.get("source_identifier", "")),
            ]
        )
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
