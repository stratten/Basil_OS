"""Lifecycle gate helpers for wake-word agent task orchestration."""

import asyncio
import logging
from typing import List, Optional

from .frontend_state_queries import resolve_main_event_loop

logger = logging.getLogger(__name__)


# Safety timeout for an unowned wake-capture lifecycle key. If audio_routes never
# takes ownership (e.g., the Swift upload never arrives), the key is released so
# wake detection can recover. Sized generously to absorb slow transcription /
# network blips that previously triggered the 10s false resume.
WAKE_CAPTURE_SAFETY_TIMEOUT_SECONDS: float = 120.0


def acquire_lifecycle(service, key: str, source: str) -> None:
    """Acquire a lifecycle slot. The backend gate is "busy" while any key is held."""
    if not key:
        return
    with service._lifecycle_lock:
        already_held = key in service._active_lifecycle_keys
        service._active_lifecycle_keys.add(key)
        held_count = len(service._active_lifecycle_keys)
    if not already_held:
        logger.info(
            f"🔒 [LIFECYCLE] acquired '{key}' (source={source}, busy_count={held_count})"
        )
    sync_idle_event(service, False)


def release_lifecycle(service, key: str, reason: str) -> None:
    """Release a lifecycle slot. Triggers wake resume when the gate becomes idle."""
    if not key:
        return
    with service._lifecycle_lock:
        was_present = key in service._active_lifecycle_keys
        service._active_lifecycle_keys.discard(key)
        became_idle = was_present and not service._active_lifecycle_keys
        held_count = len(service._active_lifecycle_keys)
    if was_present:
        logger.info(
            f"🔓 [LIFECYCLE] released '{key}' (reason={reason}, busy_count={held_count})"
        )
    if became_idle:
        sync_idle_event(service, True)
        schedule_idle_resume(service, reason)


def transfer_lifecycle(service, old_key: str, new_key: str, reason: str) -> None:
    """Atomically swap one lifecycle key for another (e.g., capture -> task)."""
    if old_key == new_key:
        return
    with service._lifecycle_lock:
        had_old = old_key in service._active_lifecycle_keys
        service._active_lifecycle_keys.discard(old_key)
        if new_key:
            service._active_lifecycle_keys.add(new_key)
        held_count = len(service._active_lifecycle_keys)
    if had_old or new_key:
        logger.info(
            f"🔁 [LIFECYCLE] transferred '{old_key}' -> '{new_key}' "
            f"(reason={reason}, busy_count={held_count})"
        )


def is_lifecycle_busy(service) -> bool:
    with service._lifecycle_lock:
        return bool(service._active_lifecycle_keys)


def lifecycle_snapshot(service) -> List[str]:
    with service._lifecycle_lock:
        return sorted(service._active_lifecycle_keys)


def consume_active_wake_capture_key(service) -> Optional[str]:
    """Atomically retrieve and clear the active wake-capture key.

    Caller takes ownership of releasing (or transferring) the returned key.
    Used by audio_routes to bridge the gate from "capturing audio" to
    "transcribing audio" without ever letting the gate become idle in
    between (which previously allowed wake to reopen during the gap).
    """
    with service._lifecycle_lock:
        key = service._active_wake_capture_key
        service._active_wake_capture_key = None
    return key


def sync_idle_event(service, target_idle: bool) -> None:
    """Set or clear the asyncio idle event from any thread."""
    loop = resolve_main_event_loop(service)
    if loop is None or loop.is_closed():
        try:
            if target_idle:
                if not service._lifecycle_idle_event.is_set():
                    service._lifecycle_idle_event.set()
            else:
                if service._lifecycle_idle_event.is_set():
                    service._lifecycle_idle_event.clear()
        except Exception:
            pass
        return
    try:
        if target_idle:
            loop.call_soon_threadsafe(service._lifecycle_idle_event.set)
        else:
            loop.call_soon_threadsafe(service._lifecycle_idle_event.clear)
    except RuntimeError:
        # Loop not running; nothing useful to do.
        pass
    except Exception as exc:
        logger.debug(f"Could not sync lifecycle idle event: {exc}")


def schedule_idle_resume(service, reason: str) -> None:
    """Schedule wake-detection resume on the main loop after lifecycle becomes idle."""
    loop = resolve_main_event_loop(service)
    if loop is None or loop.is_closed():
        logger.warning(
            f"Cannot schedule idle resume - main loop unavailable (reason={reason})"
        )
        return

    async def _resume_on_idle():
        # Brief delay to absorb rapid acquire/release flutter (e.g.,
        # transcription-key release immediately followed by task-key
        # acquire). Without this we would flap the wake listener.
        await asyncio.sleep(0.1)
        if service.is_lifecycle_busy():
            logger.debug(
                f"[LIFECYCLE] Skipping idle resume - gate became busy again (reason={reason})"
            )
            return
        if service._agent_task_cancelled:
            logger.info(
                f"[LIFECYCLE] Lifecycle idle (reason={reason}) - cancellation flag set, "
                "resuming immediately"
            )
        else:
            logger.info(
                f"🔓 [LIFECYCLE] Lifecycle idle (reason={reason}) - resuming wake-word listener"
            )
        try:
            await service._resume_wake_word_detection()
            await service._resume_listening_if_enabled()
        except Exception as resume_exc:
            logger.error(
                f"Failed to resume wake/listener after lifecycle idle: {resume_exc}",
                exc_info=True,
            )

    try:
        asyncio.run_coroutine_threadsafe(_resume_on_idle(), loop)
    except Exception as exc:
        logger.error(f"Failed to schedule idle resume coroutine: {exc}", exc_info=True)


def schedule_wake_capture_safety_release(
    service,
    capture_key: str,
    timeout: float = WAKE_CAPTURE_SAFETY_TIMEOUT_SECONDS,
) -> None:
    """Fallback release of the wake-capture key if no downstream handler takes over.

    Audio_routes is expected to consume the wake-capture key via
    ``consume_active_wake_capture_key()`` and either release it (no speech)
    or transfer it to a task key (success). If the Swift /process-audio
    upload never arrives the gate would otherwise stay busy forever; this
    timeout guarantees the listener can recover.
    """
    loop = resolve_main_event_loop(service)
    if loop is None or loop.is_closed():
        return

    async def _safety_release() -> None:
        await asyncio.sleep(timeout)
        with service._lifecycle_lock:
            still_held = capture_key in service._active_lifecycle_keys
            still_active = service._active_wake_capture_key == capture_key
        if not still_held:
            return
        logger.warning(
            f"⏱️ [LIFECYCLE] Safety release of '{capture_key}' after {timeout:.0f}s "
            "(audio_routes never took over)"
        )
        if still_active:
            with service._lifecycle_lock:
                service._active_wake_capture_key = None
        service.release_lifecycle(capture_key, "wake_capture_safety_timeout")

    try:
        asyncio.run_coroutine_threadsafe(_safety_release(), loop)
    except Exception as exc:
        logger.error(f"Failed to schedule wake-capture safety release: {exc}")
