"""Reads this Mac's memory, chip, free disk space and download-server reachability for express setup."""

from __future__ import annotations

import asyncio
import socket

from api.core.models.model_download.disk_space import detected_free_disk_gb, format_gb
from api.core.runtime.hardware_capability_service import HardwareCapabilityService

from .models import DeviceSummary

DOWNLOAD_HOST = "huggingface.co"
NETWORK_TIMEOUT_SECONDS = 3.0


def read_device_summary() -> DeviceSummary:
    profile = HardwareCapabilityService().get_profile()
    free_gb = detected_free_disk_gb()
    chip = profile.chip_label or ("Apple silicon" if profile.is_apple_silicon else "Intel")
    parts = [chip, f"{profile.total_ram_gb} GB of memory"]
    if free_gb is not None:
        parts.append(f"{format_gb(free_gb)} GB free")
    return DeviceSummary(
        total_ram_gb=profile.total_ram_gb,
        memory_tier=profile.memory_tier,
        chip_label=profile.chip_label,
        is_apple_silicon=profile.is_apple_silicon,
        free_disk_gb=free_gb,
        summary=", ".join(parts),
    )


def _can_reach_download_host() -> bool:
    try:
        with socket.create_connection((DOWNLOAD_HOST, 443), timeout=NETWORK_TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


async def can_reach_download_host() -> bool:
    """True when this Mac can open a connection to the model download server."""
    return await asyncio.to_thread(_can_reach_download_host)
