"""Screenshot capture helpers for wake-word agent task orchestration."""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def set_current_screenshot_data(service, screenshot_data: Dict[str, Any]) -> None:
    """Set the current screenshot data for agent-task processing."""
    service._current_screenshot_data = screenshot_data


def capture_immediate_screenshot(service) -> Dict[str, Any]:
    """
    Immediately capture a screenshot using Swift WindowCaptureService.

    This is called the moment a wake word is detected to capture the current
    screen context before the user navigates away from the window.

    Returns:
        Dictionary with capture results and metadata
    """
    try:
        import httpx
        from ....core.config.api_settings import settings

        logger.info("🔍 Triggering immediate Swift window capture for wake word context")

        # Call our new Swift capture endpoint
        base_url = f"http://{settings.HOST}:{settings.PORT}"
        capture_url = f"{base_url}/capture/swift-window-immediate"

        # Use synchronous HTTP request since this is called from non-async context
        # and we want immediate capture
        import requests

        try:
            from ....core.security.backend_credentials import BACKEND_TOKEN_HEADER, load_host_token

            response = requests.post(capture_url, headers={BACKEND_TOKEN_HEADER: load_host_token()}, timeout=5.0)

            if response.status_code == 200:
                capture_data = response.json()

                if capture_data.get("success"):
                    logger.info(f"✅ Swift window capture successful: {capture_data.get('image_path')}")
                    logger.info(f"📱 Captured app: {capture_data.get('app_name')} - {capture_data.get('window_title')}")

                    return {
                        "success": True,
                        "image_path": capture_data.get("image_path"),
                        "app_name": capture_data.get("app_name", "Unknown"),
                        "window_title": capture_data.get("window_title", "Unknown"),
                        "capture_timestamp": capture_data.get("capture_timestamp"),
                        "capture_method": "swift_immediate"
                    }
                else:
                    error_msg = capture_data.get("error", "Unknown error")
                    logger.warning(f"⚠️ Swift capture reported failure: {error_msg}")

                    return {
                        "success": False,
                        "error": error_msg,
                        "image_path": None,
                        "capture_method": "swift_immediate_failed"
                    }
            else:
                logger.warning(f"⚠️ Swift capture endpoint returned {response.status_code}")
                return {
                    "success": False,
                    "error": f"Capture endpoint returned {response.status_code}",
                    "image_path": None,
                    "capture_method": "swift_immediate_failed"
                }

        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ Could not reach Swift capture endpoint: {e}")
            return {
                "success": False,
                "error": f"Could not reach capture endpoint: {str(e)}",
                "image_path": None,
                "capture_method": "swift_immediate_failed"
            }

    except Exception as e:
        logger.error(f"❌ Error during immediate screenshot capture: {e}")
        return {
            "success": False,
            "error": str(e),
            "image_path": None,
            "capture_method": "swift_immediate_error"
        }
