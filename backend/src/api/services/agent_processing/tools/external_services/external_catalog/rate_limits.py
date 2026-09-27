"""Rate-limit retry and progress handling for external_catalog."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)

RATE_LIMIT_RETRY_ATTEMPTS = 1
RATE_LIMIT_WAIT_BUFFER_SECONDS = 1
RATE_LIMIT_MAX_WAIT_SECONDS = 180
SLACK_RATE_LIMIT_FALLBACK_SECONDS = 60
GENERIC_RATE_LIMIT_FALLBACK_SECONDS = 30

# Run-scoped cache key under the agent runtime context dict. Stores
# expiry timestamps keyed by (server_url, tool_name) so a burst of
# concurrent retries waiting on the same provider/tool surfaces one
# user-visible "waiting and retrying" message instead of N duplicates.
RATE_LIMIT_NOTICE_CACHE_KEY = "external_rate_limit_notice_cache"


async def try_rate_limit_wait_and_retry(
    *,
    record,
    envelope: Dict[str, Any],
    redo: Callable[[], Awaitable[Dict[str, Any]]],
    tool_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Wait once on a retryable rate limit, tell the user, then retry."""
    if envelope.get("ok") is not False:
        return None
    error = envelope.get("error") or {}
    if error.get("kind") != "rate_limited" or not error.get("retryable"):
        return None

    wait_seconds = _extract_rate_limit_wait_seconds(record, error)
    retry_meta = {
        "attempts": RATE_LIMIT_RETRY_ATTEMPTS,
        "wait_seconds": wait_seconds,
        "provider": getattr(record, "friendly_name", None),
        "server_url": getattr(record, "server_url", None),
        "exhausted": False,
    }
    await _emit_rate_limit_progress(record, wait_seconds, tool_name=tool_name)
    await asyncio.sleep(wait_seconds)

    retry_envelope = await redo()
    if retry_envelope.get("ok"):
        result = retry_envelope.get("result")
        if isinstance(result, dict):
            result["rate_limit_retry"] = retry_meta
        return retry_envelope

    retry_error = retry_envelope.get("error") or {}
    if retry_error.get("kind") == "rate_limited":
        retry_meta["exhausted"] = True
        raw = retry_error.setdefault("raw", {})
        if isinstance(raw, dict):
            raw["rate_limit_retry"] = retry_meta
        retry_error["message"] = (
            f"{retry_error.get('message') or 'External service is still rate limited.'} "
            f"Basil waited {wait_seconds} second(s) and retried once, but the service is still rate limiting this request."
        )
    return retry_envelope


def _extract_rate_limit_wait_seconds(record, error: Dict[str, Any]) -> int:
    raw = error.get("raw") or {}
    candidates = [
        raw.get("retry_after"),
        (raw.get("headers") or {}).get("Retry-After") if isinstance(raw.get("headers"), dict) else None,
        (raw.get("headers") or {}).get("retry-after") if isinstance(raw.get("headers"), dict) else None,
    ]
    for candidate in candidates:
        try:
            wait = int(float(candidate))
        except (TypeError, ValueError):
            continue
        return max(1, min(wait + RATE_LIMIT_WAIT_BUFFER_SECONDS, RATE_LIMIT_MAX_WAIT_SECONDS))

    fallback = (
        SLACK_RATE_LIMIT_FALLBACK_SECONDS
        if _is_slack_server_url(getattr(record, "server_url", ""))
        else GENERIC_RATE_LIMIT_FALLBACK_SECONDS
    )
    return min(fallback, RATE_LIMIT_MAX_WAIT_SECONDS)


def _is_slack_server_url(server_url: str) -> bool:
    normalized = (server_url or "").lower().rstrip("/")
    return normalized == "basil-local://slack" or "mcp.slack.com" in normalized


def _coalescing_key_for_record(record, tool_name: Optional[str]) -> tuple:
    """Build the (provider, tool) key used to coalesce duplicate notices."""
    server_url = (getattr(record, "server_url", "") or "").lower().rstrip("/")
    return (server_url, tool_name or "")


def _should_emit_rate_limit_notice(
    record,
    tool_name: Optional[str],
    wait_seconds: int,
) -> bool:
    """Return True if this caller should emit a fresh rate-limit progress notice.

    Run-scoped coalescing: while a wait window is active for the same
    provider+tool combination, additional concurrent rate-limit retries
    (which would each emit identical text) are suppressed so the user
    sees one clean message per window instead of N duplicates. The
    check-and-set is synchronous within asyncio's single-threaded event
    loop, so two concurrent coroutines cannot both pass it.
    """
    try:
        from api.services.agent_processing.shared.agent_runtime_context import (
            get_current_agent_context,
        )

        context = get_current_agent_context()
    except Exception:
        return True
    if not isinstance(context, dict):
        return True

    cache = context.get(RATE_LIMIT_NOTICE_CACHE_KEY)
    if not isinstance(cache, dict):
        cache = {}
        context[RATE_LIMIT_NOTICE_CACHE_KEY] = cache

    now = time.monotonic()
    for stale_key in [k for k, expiry in cache.items() if expiry <= now]:
        cache.pop(stale_key, None)

    key = _coalescing_key_for_record(record, tool_name)
    if cache.get(key, 0) > now:
        return False
    cache[key] = now + max(1, int(wait_seconds))
    return True


async def _emit_rate_limit_progress(
    record,
    wait_seconds: int,
    *,
    tool_name: Optional[str] = None,
) -> None:
    if not _should_emit_rate_limit_notice(record, tool_name, wait_seconds):
        return
    message = (
        f"{getattr(record, 'friendly_name', 'External service')} is rate limiting this request. "
        f"Waiting {wait_seconds} second(s), then retrying."
    )
    try:
        from api.services.agent_processing.shared.agent_runtime_context import get_current_agent_context
        from api.services.agent_processing.lifecycle.runtime.workflow_status_notifier import (
            WorkflowStatusNotifier,
        )

        context = get_current_agent_context()
        notifier = context.get("status_notifier") if isinstance(context, dict) else None
        if notifier is None and isinstance(context, dict):
            websocket_manager = context.get("websocket_manager")
            agent_task_id = context.get("agent_task_id")
            if websocket_manager or agent_task_id:
                notifier = WorkflowStatusNotifier(
                    websocket_manager=websocket_manager,
                    agent_task_id=agent_task_id,
                    root_task_id=context.get("root_task_id"),
                    previous_task_id=context.get("previous_task_id"),
                )
        if notifier and hasattr(notifier, "send_agent_progress_update"):
            await notifier.send_agent_progress_update(message)
    except Exception as exc:
        logger.debug("Could not emit rate-limit progress update: %s", exc)
