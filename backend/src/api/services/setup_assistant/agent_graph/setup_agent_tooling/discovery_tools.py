"""Read-only setup discovery tool handlers."""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar

from api.routes.setup_assistant.models import SetupAgentEvent, SetupAgentEventKind

logger = logging.getLogger(__name__)


T = TypeVar("T")


def _record_narration_emitted(factory) -> None:
    """Stamp the factory's monotonic narration clock.

    Both agent-emitted (`narrate_progress`) and tool-emitted narrations call
    this so the staleness guard in :func:`emit_tool_narration_if_stale` and
    :func:`slow_setup_tool` reflects the actual most-recent user-visible line.
    """
    setattr(factory, "last_narration_emitted_at", time.monotonic())


async def emit_tool_narration(factory, message: str) -> None:
    """Emit a ``progress_narration`` event from inside a tool implementation.

    Slow setup tools call this directly when they want to narrate explicitly.
    The reducer treats tool-emitted narrations identically to agent-emitted
    ones; the ``source`` field is informational metadata for future filtering.
    """
    try:
        await factory.event_emitter(
            SetupAgentEvent(
                kind=SetupAgentEventKind.progress_narration,
                payload={"message": message, "source": "tool"},
            )
        )
        _record_narration_emitted(factory)
    except Exception as exc:  # pragma: no cover - narration must never break a tool
        logger.warning("Tool narration emission failed: %s", exc)


async def emit_tool_narration_if_stale(
    factory,
    message: str,
    *,
    stale_ms: int = 1500,
) -> None:
    """Emit a tool narration only when no narration has fired recently.

    Prevents stamping over a fresh agent-emitted narration that landed within
    ``stale_ms`` milliseconds — which is the typical window for "agent
    narrated, then immediately called a slow tool". If the agent did not
    narrate, the tool covers for it.
    """
    last_at = getattr(factory, "last_narration_emitted_at", None)
    if last_at is not None:
        elapsed_ms = (time.monotonic() - last_at) * 1000.0
        if elapsed_ms < stale_ms:
            return
    await emit_tool_narration(factory, message)


def slow_setup_tool(
    opening: str,
    *,
    failure: Optional[str] = None,
    stale_ms: int = 1500,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Mark a setup tool as slow and give it automatic narration coverage.

    The decorator emits ``opening`` as a tool narration (subject to the
    staleness guard so it does not replace a fresh agent narration), runs the
    wrapped coroutine, and — if ``failure`` is provided — emits that failure
    narration when the underlying tool raises. The original exception is
    re-raised either way so callers see real failures.

    Usage::

        @slow_setup_tool(
            opening="Looking through your sent mail for a representative sample.",
            failure="I couldn't read your sent mail — moving on without that.",
        )
        async def discover_setup_writing_sample_candidates(factory, ...):
            ...
    """

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapped(factory, *args, **kwargs) -> T:
            await emit_tool_narration_if_stale(factory, opening, stale_ms=stale_ms)
            try:
                return await fn(factory, *args, **kwargs)
            except Exception:
                if failure:
                    await emit_tool_narration(factory, failure)
                raise

        return wrapped

    return decorator


# Backwards-compatible alias for callers that prefer the private name.
_emit_tool_narration = emit_tool_narration


async def discover_setup_connections(factory) -> Dict[str, Any]:
    return (await factory.discovery_service.collect_connection_catalog_facts()).model_dump(mode="json")


async def discover_setup_local_models(factory) -> Dict[str, Any]:
    return (await factory.discovery_service.collect_model_catalog_facts()).model_dump(mode="json")


async def discover_setup_profile(factory) -> Dict[str, Any]:
    return (await factory.discovery_service.collect_low_risk_setup_facts()).model_dump(mode="json")


async def discover_setup_permissions(factory) -> Dict[str, Any]:
    return factory.context_catalog_service.build_platform_permission_catalog()


@slow_setup_tool(
    opening="Checking which email apps are installed and running.",
)
async def discover_setup_email_clients(factory) -> Dict[str, Any]:
    return (await factory.discovery_service.collect_email_client_facts()).model_dump(mode="json")


@slow_setup_tool(
    opening="Looking through your sent mail for a representative writing sample.",
    failure="I couldn't read your sent mail just now — moving on without that signal.",
)
async def discover_setup_writing_sample_candidates(
    factory,
    days_back: int = 14,
    limit: int = 25,
) -> Dict[str, Any]:
    result = await factory.discovery_service.collect_sent_email_metadata_facts(
        days_back=days_back,
        limit=limit,
    )
    return result.model_dump(mode="json")
