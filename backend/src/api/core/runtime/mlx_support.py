"""Whether this Mac can run models through Apple's MLX engine."""

from __future__ import annotations

import functools
import importlib.util
import platform
from typing import Any, Mapping

MLX_HANDLER = "mlx"


@functools.lru_cache(maxsize=1)
def _mlx_packages_installed() -> bool:
    """Whether the mlx and mlx_lm packages can be found. Cached because the registry asks on every lookup; installing a package needs a backend restart anyway."""
    return importlib.util.find_spec("mlx") is not None and importlib.util.find_spec("mlx_lm") is not None


def mlx_runtime_available() -> bool:
    """True on an Apple Silicon Mac where both mlx and mlx_lm are installed.

    This only looks for the packages. It never imports them, so it is cheap and never loads Metal.
    """
    if platform.system() != "Darwin" or platform.machine().lower() not in {"arm64", "aarch64"}:
        return False
    return _mlx_packages_installed()


def model_runtime_available(model_config: Mapping[str, Any]) -> bool:
    """False only for an MLX-handler model on a Mac that cannot run MLX. Every other model is unaffected."""
    if model_config.get("handler") != MLX_HANDLER:
        return True
    return mlx_runtime_available()
