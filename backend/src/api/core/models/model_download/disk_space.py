"""Free disk space checks for model downloads.

A download peaks at about twice the model's size, because the files are fetched into the Hugging Face cache and copied into Basil's models folder before the cache copy is removed (see ``hf_cache_cleanup``). These helpers turn a registry size into the free space a download needs, read the free space on the models volume, and credit what a previous attempt already left in the cache, so a retry after a failed copy is not asked for more room than it needs.
"""

from __future__ import annotations

import math
import re
import shutil
from pathlib import Path
from typing import Optional

#: Free space a download needs, as a multiple of the model's size: the cache copy plus the installed copy.
DOWNLOAD_DISK_PEAK_MULTIPLIER = 2.0
#: Extra free space on top of the peak, for other writes to the same volume while the download runs.
DOWNLOAD_DISK_MARGIN_GB = 2.0

_BYTES_PER_GB = 1024 ** 3


class InsufficientDiskSpaceError(Exception):
    """A download was refused because the models volume does not have the free space it needs.

    The message is written for the person using the app, so routes can show it as is.
    """

    def __init__(self, model_id: str, display_name: str, required_gb: float, free_gb: float) -> None:
        self.model_id = model_id
        self.display_name = display_name
        self.required_gb = required_gb
        self.free_gb = free_gb
        super().__init__(disk_shortfall_message(display_name, required_gb, free_gb))


def format_gb(value: float) -> str:
    """Format a size in GB for people: one decimal below 10 GB, whole numbers above."""
    return f"{value:.1f}" if value < 10 else f"{value:.0f}"


def disk_shortfall_message(display_name: str, required_gb: float, free_gb: float) -> str:
    """Say plainly that a model will not fit, how much room it needs, and how much to free."""
    to_free_gb = max(1, math.ceil(required_gb - free_gb))
    return (
        f"Not enough free disk space to download {display_name}. "
        f"It needs about {format_gb(required_gb)} GB free while it installs, and this Mac has {format_gb(free_gb)} GB free. "
        f"Free up about {to_free_gb} GB and try again."
    )


def larger_model_blocked_message(preferred_name: str, fallback_name: str, required_gb: float, free_gb: float) -> str:
    """Say that this Mac has the memory for a much more capable model but not the disk space to download it, and strongly recommend freeing the space."""
    to_free_gb = max(1, math.ceil(required_gb - free_gb))
    return (
        f"This Mac has the memory to run {preferred_name}, which is much more capable than {fallback_name}, but it needs about {format_gb(required_gb)} GB free while it installs and this Mac has {format_gb(free_gb)} GB free. "
        f"Basil strongly recommends freeing up about {to_free_gb} GB and using {preferred_name}. Until then Basil will offer {fallback_name}."
    )


def detected_free_disk_gb(path: Optional[Path] = None) -> Optional[float]:
    """Free space in GB on the volume that holds ``path``, or None when it cannot be read.

    ``path`` defaults to Basil's models folder. A folder that does not exist yet is measured through its nearest existing parent, because they share a volume.
    """
    try:
        probe = Path(path) if path is not None else Path.home() / ".basil" / "models"
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        return shutil.disk_usage(probe).free / _BYTES_PER_GB
    except Exception:
        return None


def parse_registry_size_gb(size: object) -> Optional[float]:
    """Read a registry size such as "20GB" or "5.6GB" as GB, or None when it is not in GB."""
    match = re.match(r"\s*(\d+(?:\.\d+)?)\s*GB\s*$", str(size or ""), re.IGNORECASE)
    return float(match.group(1)) if match else None


def download_disk_required_gb(size: object, cached_gb: float = 0.0) -> Optional[float]:
    """Free space in GB needed to download a model of registry ``size``, or None when the size cannot be read.

    ``cached_gb`` is what a previous attempt already left in the Hugging Face cache. It cuts the download that is still to come, but the installed copy still needs the model's full size, so the need never drops below that.
    """
    size_gb = parse_registry_size_gb(size)
    if size_gb is None:
        return None
    peak_gb = max(size_gb * DOWNLOAD_DISK_PEAK_MULTIPLIER - max(cached_gb, 0.0), size_gb)
    return peak_gb + DOWNLOAD_DISK_MARGIN_GB


def cached_repo_gb(repo_id: Optional[str], cache_dir: Optional[Path] = None) -> float:
    """GB a model repo already holds in the Hugging Face cache, including a partial download, or 0 when none or unreadable.

    Only the repo's ``blobs`` folder is measured, because that is where finished and partial files live. A cache layout that keeps contents elsewhere reports 0, which makes the check stricter and never looser.
    """
    if not repo_id:
        return 0.0
    try:
        if cache_dir is None:
            from huggingface_hub import constants

            cache_dir = Path(constants.HF_HUB_CACHE)
        blobs = Path(cache_dir) / ("models--" + repo_id.replace("/", "--")) / "blobs"
        if not blobs.is_dir():
            return 0.0
        return sum(entry.stat().st_size for entry in blobs.iterdir() if entry.is_file()) / _BYTES_PER_GB
    except Exception:
        return 0.0
