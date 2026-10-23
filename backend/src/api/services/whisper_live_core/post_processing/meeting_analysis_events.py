"""Provisional item events for meeting analysis and the To-Do candidate hook."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from pydantic import BaseModel, ValidationError

from .meeting_analysis_models import (
    ActionItem,
    AnalysisMode,
    Decision,
    QuestionAnswer,
    SuggestedActionDraft,
    build_action_proposals,
)

logger = logging.getLogger(__name__)

ITEM_STREAM_MODELS: Dict[AnalysisMode, type[BaseModel]] = {
    AnalysisMode.ACTION_ITEMS: ActionItem,
    AnalysisMode.SUGGESTED_ACTIONS: SuggestedActionDraft,
    AnalysisMode.DECISIONS: Decision,
    AnalysisMode.QUESTIONS: QuestionAnswer,
}

EventCallback = Callable[[Dict[str, Any]], Awaitable[None]]
CountCallback = Callable[[str, int], Awaitable[None]]
TodoCandidateSubscriber = Callable[[Dict[str, Any]], Awaitable[None]]

_todo_candidate_subscribers: List[TodoCandidateSubscriber] = []


def subscribe_todo_candidates(subscriber: TodoCandidateSubscriber) -> Callable[[], None]:
    """Register for ``todo_candidate_streamed`` events; returns an unsubscribe function.

    This is the reserved hook for a later feature that starts work on a candidate while
    the meeting is still being analyzed. D3 itself registers no subscriber and starts
    nothing.
    """
    _todo_candidate_subscribers.append(subscriber)

    def unsubscribe() -> None:
        try:
            _todo_candidate_subscribers.remove(subscriber)
        except ValueError:
            pass

    return unsubscribe


class AnalysisItemSink:
    """Validates streamed elements and publishes provisional item events."""

    def __init__(
        self,
        *,
        meeting_id: str,
        event_callback: Optional[EventCallback] = None,
        count_callback: Optional[CountCallback] = None,
    ) -> None:
        self._meeting_id = meeting_id
        self._event_callback = event_callback
        self._count_callback = count_callback
        self._counts: Dict[str, int] = {}

    @property
    def enabled(self) -> bool:
        """True only when someone is listening, so unobserved runs never stream."""
        return bool(
            self._event_callback
            or self._count_callback
            or _todo_candidate_subscribers
        )

    async def begin_attempt(self, mode: AnalysisMode) -> None:
        await self.reset(mode)

    async def reset(self, mode: AnalysisMode) -> None:
        """Discard provisional items of an abandoned attempt."""
        had_items = self._counts.get(mode.value, 0) > 0
        self._counts[mode.value] = 0
        if had_items:
            await self._send(
                {
                    "type": "analysis_items_reset",
                    "meeting_id": self._meeting_id,
                    "mode": mode.value,
                }
            )

    async def emit_element(self, mode: AnalysisMode, element_json: str) -> None:
        """Validate one completed array element and publish it as provisional."""
        item_model = ITEM_STREAM_MODELS.get(mode)
        if item_model is None:
            return
        try:
            item = item_model.model_validate_json(element_json)
        except ValidationError:
            logger.debug("Skipping streamed %s element that failed validation", mode.value)
            return
        sequence = self._counts.get(mode.value, 0)
        self._counts[mode.value] = sequence + 1
        await self._send(
            {
                "type": "analysis_item",
                "meeting_id": self._meeting_id,
                "mode": mode.value,
                "sequence": sequence,
                "provisional": True,
                "item": item.model_dump(mode="json"),
            }
        )
        if self._count_callback is not None:
            try:
                await self._count_callback(mode.value, sequence + 1)
            except Exception:
                logger.warning("Streamed-item count callback failed", exc_info=True)
        if mode == AnalysisMode.SUGGESTED_ACTIONS and isinstance(item, SuggestedActionDraft):
            await self._emit_todo_candidate(item)

    async def _emit_todo_candidate(self, draft: SuggestedActionDraft) -> None:
        proposals = build_action_proposals([draft], meeting_id=self._meeting_id)
        if not proposals:
            return
        candidate = proposals[0].model_dump(mode="json")
        event = {
            "type": "todo_candidate_streamed",
            "meeting_id": self._meeting_id,
            "stable_id": candidate["id"],
            "provisional": True,
            "candidate": candidate,
        }
        await self._send(event)
        for subscriber in list(_todo_candidate_subscribers):
            try:
                await subscriber(event)
            except Exception:
                logger.warning("To-Do candidate subscriber failed", exc_info=True)

    async def _send(self, event: Dict[str, Any]) -> None:
        if self._event_callback is None:
            return
        try:
            await self._event_callback(event)
        except Exception:
            logger.warning("Analysis event callback failed", exc_info=True)
