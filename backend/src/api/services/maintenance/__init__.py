"""Background maintenance schedulers (asyncio-native).

Replaces the Huey periodic-task layer that previously owned things like
reasoning capture cleanup. Schedulers are owned by the FastAPI app and
attached to `app.state` for lifecycle management.

`CaptureManagementService` doesn't have a handle on the FastAPI `app`
(it's instantiated via a route Depends()), so it can't reach the scheduler
through `app.state`. To let it ask for an immediate re-evaluation when the
user toggles the "auto cleanup" setting, we expose a tiny module-level
registry: the FastAPI `startup_event` calls `register_capture_cleanup_scheduler`
once it constructs the scheduler, and the service later calls
`kick_capture_cleanup_scheduler()` (no-op when nothing is registered, e.g.
in unit tests).
"""

from __future__ import annotations

from typing import Optional

from .capture_cleanup_scheduler import CaptureCleanupScheduler
from .legacy_memvid_cleanup import cleanup_legacy_memvid_data
from .model_artifact_pruner import prune_redundant_embedding_artifacts
from .orphan_cleanup import cleanup_huey_orphans

__all__ = [
    "CaptureCleanupScheduler",
    "register_capture_cleanup_scheduler",
    "get_capture_cleanup_scheduler",
    "kick_capture_cleanup_scheduler",
    "cleanup_huey_orphans",
    "cleanup_legacy_memvid_data",
    "prune_redundant_embedding_artifacts",
]

_registered_scheduler: Optional[CaptureCleanupScheduler] = None


def register_capture_cleanup_scheduler(scheduler: Optional[CaptureCleanupScheduler]) -> None:
    """Register (or clear, with `None`) the singleton scheduler instance.

    Called once from the FastAPI startup hook in `api/main.py` and
    `basil_api.py`. Calling with `None` during shutdown is optional but
    keeps the registry clean if the process is otherwise long-lived (tests).
    """
    global _registered_scheduler
    _registered_scheduler = scheduler


def get_capture_cleanup_scheduler() -> Optional[CaptureCleanupScheduler]:
    return _registered_scheduler


def kick_capture_cleanup_scheduler() -> bool:
    """Wake the registered scheduler so settings changes apply immediately.

    Returns False (and is otherwise a no-op) when no scheduler is registered
    -- e.g. inside unit tests that import the service without booting
    FastAPI. Returns True when the kick was delivered.
    """
    if _registered_scheduler is None:
        return False
    _registered_scheduler.kick()
    return True
