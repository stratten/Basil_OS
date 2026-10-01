"""Dispatch durable agent-requested follow-up checks back into their Agent Task chain."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

FOLLOW_UP_POLL_SECONDS = 30.0
FOLLOW_UP_BUSY_DEFER_SECONDS = 60
FOLLOW_UP_MAX_DEFERS = 60
FOLLOW_UP_MISSED_AFTER = timedelta(hours=24)
FOLLOW_UP_ORIGIN_TYPE = "agent_follow_up"
_TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "canceled"})


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def build_follow_up_prompt(follow_up: Dict[str, Any]) -> str:
    reason = str(follow_up.get("reason") or "").strip()
    reason_line = f"\nWhy: {reason}" if reason else ""
    return (
        "Scheduled follow-up check that you requested in an earlier turn of this task.\n"
        f"Check: {follow_up['instructions']}{reason_line}\n\n"
        "Use the earlier turns of this task for context, perform the check now, and report what you found. "
        "If the result is still not ready and checking again later is useful, you may call schedule_agent_follow_up again."
    )


def build_follow_up_display_markdown(follow_up: Dict[str, Any]) -> str:
    return f"**Follow-up check:** {follow_up['instructions']}"


class AgentFollowUpScheduler:
    """Polls ``agent_task_follow_ups`` and submits due rows as new chain turns."""

    def __init__(
        self,
        *,
        repository: Any,
        chain_reader: Any,
        submission_service: Any,
        poll_seconds: float = FOLLOW_UP_POLL_SECONDS,
        now_fn: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._repository = repository
        self._chain_reader = chain_reader
        self._submission_service = submission_service
        self._poll_seconds = float(poll_seconds)
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._task: Optional[asyncio.Task] = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> Dict[str, Any]:
        recovered = await self._repository.recover_interrupted_dispatches()
        if not self.is_running:
            self._task = asyncio.create_task(self._run_loop(), name="agent-follow-up-scheduler")
        return {"recovered_dispatches": recovered, "poll_seconds": self._poll_seconds}

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _run_loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Agent follow-up scheduler tick failed")
            await asyncio.sleep(self._poll_seconds)

    async def run_once(self) -> Dict[str, int]:
        now = self._now_fn()
        counts = {"submitted": 0, "deferred": 0, "failed": 0, "missed": 0, "canceled": 0}
        claimed = await self._repository.claim_due_follow_ups(now_iso=_iso(now))
        for follow_up in claimed:
            try:
                outcome = await self._dispatch(follow_up, now)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Agent follow-up %s dispatch failed", follow_up.get("id"))
                await self._repository.finish_without_submission(
                    follow_up["id"], status="failed", error_message=f"Dispatch error: {exc}"
                )
                outcome = "failed"
            counts[outcome] += 1
        return counts

    async def _dispatch(self, follow_up: Dict[str, Any], now: datetime) -> str:
        follow_up_id = follow_up["id"]
        try:
            due_at = datetime.fromisoformat(str(follow_up["due_at"]))
        except ValueError:
            due_at = now
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        if now - due_at > FOLLOW_UP_MISSED_AFTER:
            await self._repository.finish_without_submission(
                follow_up_id,
                status="missed",
                error_message="Basil was not running for more than 24 hours after this follow-up was due.",
            )
            return "missed"

        existing = await self._chain_reader.list_agent_tasks_by_origin(FOLLOW_UP_ORIGIN_TYPE, follow_up_id)
        if existing:
            await self._repository.mark_submitted(follow_up_id, follow_up_agent_task_id=str(existing[0].id))
            return "submitted"

        chain = await self._chain_reader.get_agent_task_chain(follow_up["root_task_id"])
        if not chain:
            await self._repository.finish_without_submission(
                follow_up_id, status="failed", error_message="The task chain no longer exists."
            )
            return "failed"
        latest_status = str(getattr(chain[-1], "status", "") or "")
        if latest_status == "canceled":
            await self._repository.finish_without_submission(
                follow_up_id, status="canceled", error_message="The task chain was canceled."
            )
            return "canceled"
        if latest_status not in _TERMINAL_TASK_STATUSES:
            return await self._defer(follow_up, now, f"The task chain is busy ({latest_status or 'unknown'}).")
        if self._submission_service is None:
            return await self._defer(follow_up, now, "Agent task submission is unavailable.")

        agent_task_id = str(uuid.uuid4())
        result = await self._submission_service.process_agent_task_direct(
            agent_task=build_follow_up_prompt(follow_up),
            display_prompt_markdown=build_follow_up_display_markdown(follow_up),
            agent_task_id=agent_task_id,
            root_task_id=follow_up["root_task_id"],
            origin_type=FOLLOW_UP_ORIGIN_TYPE,
            origin_id=follow_up_id,
        )
        result = result or {}
        if result.get("success") is False:
            if result.get("operation") == "canceled":
                return await self._defer(follow_up, now, "Submission was suppressed by a recent cancellation.")
            message = str(
                result.get("error") or result.get("message") or result.get("reasoning") or "Follow-up submission failed."
            )
            await self._repository.finish_without_submission(follow_up_id, status="failed", error_message=message)
            return "failed"
        await self._repository.mark_submitted(follow_up_id, follow_up_agent_task_id=agent_task_id)
        return "submitted"

    async def _defer(self, follow_up: Dict[str, Any], now: datetime, reason: str) -> str:
        if int(follow_up.get("defer_count") or 0) >= FOLLOW_UP_MAX_DEFERS:
            await self._repository.finish_without_submission(
                follow_up["id"],
                status="failed",
                error_message=f"{reason} Gave up after {FOLLOW_UP_MAX_DEFERS} attempts.",
            )
            return "failed"
        await self._repository.defer_follow_up(
            follow_up["id"],
            due_at=_iso(now + timedelta(seconds=FOLLOW_UP_BUSY_DEFER_SECONDS)),
            reason=reason,
        )
        return "deferred"


_scheduler: Optional[AgentFollowUpScheduler] = None


async def start_agent_follow_up_scheduler(
    *,
    repository: Any,
    chain_reader: Any,
    submission_service: Any,
) -> Dict[str, Any]:
    global _scheduler
    if _scheduler is not None:
        await _scheduler.stop()
    _scheduler = AgentFollowUpScheduler(
        repository=repository,
        chain_reader=chain_reader,
        submission_service=submission_service,
    )
    return await _scheduler.start()


async def stop_agent_follow_up_scheduler() -> None:
    global _scheduler
    scheduler, _scheduler = _scheduler, None
    if scheduler is not None:
        await scheduler.stop()
