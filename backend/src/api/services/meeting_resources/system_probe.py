"""Reads processor and memory pressure for the resource advisor."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SystemMetrics:
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    total_memory_gb: float = 0.0


def prime_system_metrics() -> None:
    """The first non-blocking ``cpu_percent`` call always reads zero, so take it once at startup."""
    try:
        import psutil

        psutil.cpu_percent(interval=None)
    except Exception as error:
        logger.debug("Resource advisor could not prime processor sampling: %s", error)


def read_system_metrics() -> SystemMetrics:
    """Current processor and memory use; zeros when the platform cannot report them."""
    try:
        import psutil

        memory = psutil.virtual_memory()
        return SystemMetrics(
            cpu_percent=float(psutil.cpu_percent(interval=None)),
            memory_percent=float(memory.percent),
            total_memory_gb=float(memory.total) / (1024.0 ** 3),
        )
    except Exception as error:
        logger.debug("Resource advisor could not read system metrics: %s", error)
        return SystemMetrics()
