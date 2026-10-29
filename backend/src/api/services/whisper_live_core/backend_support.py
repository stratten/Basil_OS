import importlib.util
import logging
import platform

from api.core.runtime.hardware_capability_service import HardwareCapabilityService

logger = logging.getLogger(__name__)


def module_available(module_name):
    """Return True if the given module can be imported."""
    return importlib.util.find_spec(module_name) is not None


def mlx_backend_available(warn_on_missing = False):
    profile = HardwareCapabilityService().get_profile()
    is_macos = profile.platform == "Darwin"
    is_arm = profile.machine == "arm64"
    available = profile.mlx_whisper_available
    if not available and warn_on_missing and is_macos and is_arm:
        logger.warning(
            "=" * 50
            + "\nMLX Whisper not found but you are on Apple Silicon. "
              "Consider installing mlx-whisper for better performance: "
              "`pip install mlx-whisper`\n"
            + "=" * 50
        )
    return available


def faster_backend_available(warn_on_missing = False):
    profile = HardwareCapabilityService().get_profile()
    available = profile.faster_whisper_available
    if not available and warn_on_missing and platform.system() != "Darwin":
        logger.warning(
            "=" * 50
            + "\nFaster-Whisper not found. Consider installing faster-whisper "
              "for better performance: `pip install faster-whisper`\n"
            + "=" * 50
        )
    return available
